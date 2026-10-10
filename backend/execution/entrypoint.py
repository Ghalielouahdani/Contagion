"""backend/execution/entrypoint.py — P3 : point d'entrée unique pour POST /api/v1/decide (P4).

    status, body = handle_decide_request(request_json)

Ne lève jamais d'exception : renvoie (code HTTP, corps JSON). Voir README.md pour le format.
"""
import copy
from decimal import Decimal, InvalidOperation

from .decision import decide_portfolio, decide_position, load_contracts
from .sensitivity import sensitivity

SCHEMA_VERSION = "1.0"
SCENARIOS = {"usde_depeg": False, "liquidity_crisis": True}   # scenario_id → fichiers _liquidity ?
INPUT_KEYS = ("portfolio", "market_snapshot", "risk_result", "scenario_request")
INCLUDES = {"sensitivity", "portfolio_summary"}


def error(status, code, message):
    return status, {"status": "error", "error": {"code": code, "message": message}}


def handle_decide_request(request):
    if not isinstance(request, dict):
        return error(422, "invalid_request", "Request body must be a JSON object.")
    if request.get("schema_version") != SCHEMA_VERSION:
        return error(400, "unsupported_schema_version",
                     f"schema_version must be {SCHEMA_VERSION!r}, got {request.get('schema_version')!r}.")
    position_id = request.get("position_id")
    if not position_id:
        return error(422, "invalid_request", "position_id is required.")
    probability = request.get("probability")
    if probability is not None:
        try:
            if not isinstance(probability, str):
                raise TypeError
            Decimal(probability)
        except (TypeError, InvalidOperation):
            return error(422, "invalid_request",
                         f'probability must be a decimal string such as "0.15", or null; got {probability!r}.')
    include = set(request.get("include") or [])
    if include - INCLUDES:
        return error(422, "invalid_request", f"Unknown include: {sorted(include - INCLUDES)}; allowed: {sorted(INCLUDES)}.")

    # Mode live : P4 transmet les JSON de P1/P2. Mode fixture : on charge demo_ethena_01.
    inputs = request.get("inputs")
    if inputs is not None:
        missing = [k for k in INPUT_KEYS if k not in inputs]
        if missing:
            return error(422, "invalid_request", f"inputs is missing: {', '.join(missing)}.")
        mode = "live"
        portfolio, snapshot = inputs["portfolio"], inputs["market_snapshot"]
        risk_result, scenario_request = inputs["risk_result"], inputs["scenario_request"]
    else:
        scenario_id = request.get("scenario_id")
        if scenario_id not in SCENARIOS:
            return error(422, "invalid_request", f"scenario_id must be one of {sorted(SCENARIOS)}, got {scenario_id!r}.")
        mode = "fixture"
        c = load_contracts(liquidity=SCENARIOS[scenario_id])
        portfolio, snapshot, risk_result, scenario_request = (
            c["portfolio"], c["snapshot"], c["risk_result"], c["scenario_request"])

    if request.get("portfolio_id") != portfolio.get("portfolio_id"):
        return error(404, "unknown_portfolio",
                     f"portfolio_id {request.get('portfolio_id')!r} does not match {portfolio.get('portfolio_id')!r}.")
    if position_id not in {p["position_id"] for p in portfolio.get("positions", [])}:
        return error(404, "unknown_position", f"position_id {position_id!r} is not in portfolio {portfolio['portfolio_id']!r}.")

    # La probabilité vient de l'utilisateur (curseur du dashboard) ; sinon celle de scenario_request.
    if "probability" in request:
        scenario_request = copy.deepcopy(scenario_request)
        scenario_request["assumptions"]["probability"] = request["probability"]
        scenario_request["assumptions"]["source_type"] = "user_scenario"

    try:
        body = {"status": "ok", "mode": mode,
                "decision": decide_position(portfolio, snapshot, risk_result, scenario_request, position_id)}
        if "sensitivity" in include:
            body["sensitivity"] = sensitivity(portfolio, snapshot, risk_result, scenario_request, position_id)
        if "portfolio_summary" in include:
            body["portfolio_summary"] = decide_portfolio(portfolio, snapshot, risk_result, scenario_request)["summary"]
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:   # entrées incohérentes ou incomplètes
        detail = exc.args[0] if exc.args else type(exc).__name__
        return error(422, "invalid_inputs", f"Cannot compute decision: {detail}")
    return 200, body
