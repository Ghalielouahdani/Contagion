"""Stored fixture results are regenerated from the engine, except golden expectations."""

import json
import shutil
from decimal import Decimal as D
from pathlib import Path

from backend.risk.regenerate import regenerate

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def copy_set(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / name
    shutil.copytree(FIXTURES / name, folder)
    return folder


def test_golden_results_are_never_overwritten(tmp_path):
    folder = copy_set(tmp_path, "demo_ethena_01")
    golden = json.loads((folder / "risk_result.json").read_text())
    tampered = {**golden, "warnings": ["hand-written expectation"]}
    (folder / "risk_result.json").write_text(json.dumps(tampered))
    (folder / "risk_result_cascade.json").unlink()

    regenerate(folder, surface=False)

    assert json.loads((folder / "risk_result.json").read_text()) == tampered  # untouched
    assert (folder / "risk_result_cascade.json").exists()  # missing result added
    assert "risk_result_cascade" in json.loads((folder / "manifest.json").read_text())["files"]


def test_non_golden_results_follow_the_engine(tmp_path):
    folder = copy_set(tmp_path, "verified_lending_2026_10_10")
    (folder / "risk_result.json").write_text(json.dumps({"stale": True}))
    regenerate(folder, surface=False)
    result = json.loads((folder / "risk_result.json").read_text())
    assert result["scenario_id"] == "usde_depeg" and D(result["portfolio"]["total_conditional_loss_usd"]) > 0


def test_cascade_amplification_is_measured_on_the_most_hit_asset():
    cascade = json.loads((FIXTURES / "verified_lending_2026_10_10" / "risk_result_cascade.json").read_text())["cascade"]
    ratios = [D(cascade["final_moves"][a]) / D(m) for a, m in cascade["initial_moves"].items() if D(m) != 0]
    assert abs(D(cascade["amplification"]) - max(ratios)) < D("0.001")
    assert D(cascade["amplification"]) > 1
    # Amplification uses final prices, after arbitrage; do not confuse it with
    # the within-round trough, which can be much deeper despite a later rebound.
    assert any(D(cascade["trough_moves"][a]) < D(cascade["final_moves"][a]) for a in cascade["initial_moves"])
