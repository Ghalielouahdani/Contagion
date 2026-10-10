"""Local assistant model adapter.

The referenced no-cost-ai repository is a catalog rather than an SDK. Its
developer API list includes Ollama, which is the safe no-cost option here
because portfolio/risk data stays on localhost instead of leaving the machine.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("defi_contagion.assistant")

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
RISK_BY_SCENARIO = {
    "usde_depeg": "risk_result",
    "liquidity_crisis": "risk_result_liquidity",
    "combined_crisis": "risk_result_combined",
    "governance_change": "risk_result_governance",
    "carry_squeeze": "risk_result_carry",
    "node_shock": "risk_result_node_shock",
}


class AssistantModelError(RuntimeError):
    """Raised when the local model is unreachable or returns no text."""


def answer_assistant(body: dict[str, Any], files: dict[str, Any], fixture_set: str) -> dict[str, Any]:
    context = build_assistant_context(body, files, fixture_set)
    model_request = build_ollama_request(body.get("message", ""), context)
    try:
        text, raw_response = call_local_ollama(model_request)
        return {
            "message": text,
            "actions": [],
            "source": "local-ollama",
            "provider": "no-cost-ai/ollama-local",
            "model": model_request["model"],
            "raw_response_preview": raw_response[:1200],
        }
    except AssistantModelError as exc:
        logger.warning("[assistant] local model unavailable; using deterministic fallback: %s", exc)
        return {
            "message": f"Offline fallback: {deterministic_fallback(body, context)}",
            "actions": [],
            "source": "deterministic-fallback",
            "fallback_reason": str(exc),
        }


def build_assistant_context(body: dict[str, Any], files: dict[str, Any], fixture_set: str) -> dict[str, Any]:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    portfolio = data.get("portfolio") or files.get("portfolio") or {}
    graph = data.get("graph") or files.get("dependency_graph") or {}
    market = data.get("marketSnapshot") or data.get("market_snapshot") or files.get("market_snapshot") or {}
    risk = data.get("risk") or files.get(RISK_BY_SCENARIO.get(str(body.get("scenario")), "risk_result")) or files.get("risk_result") or {}
    decision = data.get("decision") or files.get("decision_result") or {}
    decisions = data.get("decisions") or ({decision.get("position_id"): decision} if decision.get("position_id") else {})
    return {
        "fixture_set": fixture_set,
        "current_view": body.get("view"),
        "scenario": body.get("scenario"),
        "selected_position": body.get("selected_position") or body.get("selectedPosition"),
        "inspected_exit_fraction": body.get("inspected_exit_fraction") or body.get("inspectedExitFraction"),
        "scenario_inputs": body.get("scenario_inputs") or body.get("scenarioInputs") or {},
        "portfolio": {
            "portfolio_id": portfolio.get("portfolio_id"),
            "as_of": portfolio.get("as_of"),
            "quote_currency": portfolio.get("quote_currency"),
            "positions": portfolio.get("positions", []),
        },
        "market_snapshot": {
            "as_of": market.get("as_of"),
            "prices": market.get("prices", market.get("assets", [])),
            "protocol_metrics": market.get("protocol_metrics", market.get("protocols", [])),
        },
        "dependency_graph": {
            "nodes": graph.get("nodes", [])[:80],
            "edges": graph.get("edges", [])[:120],
        },
        "risk": risk,
        "decision": decision,
        "decisions": decisions,
    }


def build_ollama_request(message: str, context: dict[str, Any]) -> dict[str, Any]:
    model = os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    system = (
        "You are the DeFi Contagion dashboard assistant. Answer only from the provided on-screen JSON. "
        "Never invent numbers, IDs, health factors, exit costs, or recommendations. If a field is missing, say it is missing. "
        "Be concise, specific, and mention the relevant position IDs or scenario inputs when useful."
    )
    user = (
        "Current on-screen data follows as JSON. Ground the answer strictly in it.\n"
        f"{json.dumps(context, separators=(',', ':'), default=str)[:30000]}\n\n"
        f"User question: {message}"
    )
    return {
        "url": local_ollama_url(),
        "model": model,
        "payload": {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {"temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.25"))},
        },
    }


def local_ollama_url() -> str:
    base = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise AssistantModelError("OLLAMA_BASE_URL must point to local http://127.0.0.1, localhost, or ::1")
    return f"{base}/api/chat"


def call_local_ollama(request: dict[str, Any]) -> tuple[str, str]:
    raw_payload = json.dumps(request["payload"], ensure_ascii=False)
    logger.info("[assistant] local Ollama raw request: %s", raw_payload)
    http_request = urllib.request.Request(
        request["url"],
        data=raw_payload.encode("utf-8"),
        headers={"content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.warning("[assistant] local Ollama HTTP error %s: %s", exc.code, detail)
        raise AssistantModelError(f"HTTP {exc.code}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("[assistant] local Ollama network error: %r", exc)
        raise AssistantModelError(repr(exc)) from exc

    logger.info("[assistant] local Ollama raw response: %s", raw_response)
    try:
        parsed = json.loads(raw_response)
        text = parsed["message"]["content"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AssistantModelError(f"unexpected Ollama response: {raw_response[:500]}") from exc
    if not str(text).strip():
        raise AssistantModelError("local Ollama returned an empty answer")
    return str(text).strip(), raw_response


def deterministic_fallback(body: dict[str, Any], context: dict[str, Any]) -> str:
    message = str(body.get("message", "")).lower()
    selected = context.get("selected_position")
    risk_positions = (context.get("risk") or {}).get("positions", [])
    decisions = context.get("decisions") or {}
    selected_risk = next((position for position in risk_positions if position.get("position_id") == selected), None)
    selected_decision = decisions.get(selected) or context.get("decision") or {}

    if "risk" in message or "most" in message:
        ranked = sorted(risk_positions, key=lambda p: float(p.get("conditional_loss_usd") or 0), reverse=True)
        if ranked:
            top = ranked[0]
            return (
                f"{top.get('position_id')} has the largest visible conditional loss "
                f"(${float(top.get('conditional_loss_usd') or 0):,.0f}) in the current screen data."
            )
    if selected_risk and ("health" in message or "ltv" in message or "drop" in message):
        return (
            f"For {selected}, the visible conditional loss is "
            f"${float(selected_risk.get('conditional_loss_usd') or 0):,.0f}. "
            "Any exact health-factor explanation needs the health-factor fields present in the displayed risk data."
        )
    if selected_decision and ("verdict" in message or "stay" in message or "exit" in message or "reduce" in message):
        return (
            f"For {selected_decision.get('position_id', selected)}, the visible recommendation is "
            f"{selected_decision.get('recommendation', 'missing')} with exit fraction "
            f"{selected_decision.get('recommended_exit_fraction', 'missing')}. "
            f"Reason: {selected_decision.get('reason', 'missing')}"
        )
    return "The local model is not reachable. I can still use the deterministic controls and fixture data once the backend/model is running."
