"""The exported report must remain grounded in the existing dataset and code."""
import hashlib
import json

from backend.risk.backtest import document, run


def test_export_identifies_exact_input_and_ex_post_limitations():
    result = document.build()
    key = str(run.DATA.relative_to(document.ROOT))
    assert result["provenance"]["sha256"][key] == hashlib.sha256(run.DATA.read_bytes()).hexdigest()
    assert result["status"] == "partial_ex_post_validation_not_predictive_backtest"
    assert result["coverage"]["chainlink_usde_usd"]["observations"] == len(run.load().chainlink)
    assert result["results"] == run.run_all()
    assert any("+/-2 hours" in item for item in result["limitations"])
    assert any("current aggregator phase" in item for item in result["limitations"])
    json.dumps(result, allow_nan=False)


def test_report_distinguishes_price_proxy_from_actual_liquidations():
    report = document.markdown(document.build())
    assert "liquidations historiques effectivement observées" in report
    assert "9 jours" in report
    assert "pire écart PT" in report
