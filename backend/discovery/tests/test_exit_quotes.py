"""Exit quote curves at cascade sizes, with the aggregator replaced by a deterministic book."""

from backend.discovery import exit_quotes


def fake_route(depth_usd: float):
    """Constant-product book of depth_usd per side, quoting USDC (6 decimals) for an 18-decimal token at 1 USD."""
    def route(sell, buy, amount_raw):
        size = amount_raw / 10**18
        out = size * depth_usd / (depth_usd + size)
        return {"amountOut": str(int(out * 10**6)), "gasUsd": "3.5"}
    return route


def test_curve_reaches_cascade_sizes_and_matches_the_contract(monkeypatch):
    monkeypatch.setattr(exit_quotes, "_route", fake_route(10_000_000))
    monkeypatch.setattr(exit_quotes.time, "sleep", lambda _: None)
    venue = exit_quotes.quote_curve("USDe", 1.0)
    sizes = [float(q["size_usd"]) for q in venue["quotes"]]
    losses = [float(q["loss_pct"]) for q in venue["quotes"]]
    assert sizes[-1] >= 150_000_000  # covers liquidation-sized selling, not just the fund's own size
    assert losses == sorted(losses) and losses[-1] > 90  # loss in percent, growing with size
    assert set(venue) >= {"asset", "quote_method", "effective_depth_usd", "fee_rate", "gas_usd", "source_type", "quotes"}
    assert venue["quote_method"] == "executable_quote" and venue["gas_usd"] == "3.50"


def test_proxy_depth_recovers_a_constant_product_book(monkeypatch):
    monkeypatch.setattr(exit_quotes, "_route", fake_route(10_000_000))
    monkeypatch.setattr(exit_quotes.time, "sleep", lambda _: None)
    depth = float(exit_quotes.quote_curve("USDe", 1.0)["effective_depth_usd"])
    assert abs(depth - 10_000_000) / 10_000_000 < 0.01


def test_orders_better_than_the_reference_price_are_floored_at_zero_loss(monkeypatch):
    monkeypatch.setattr(exit_quotes, "_route", lambda s, b, amount: {"amountOut": str(int(amount / 10**18 * 1.001 * 10**6))})
    monkeypatch.setattr(exit_quotes.time, "sleep", lambda _: None)
    assert all(q["loss_pct"] == "0.0000" for q in exit_quotes.quote_curve("USDe", 1.0)["quotes"])
