"""Exit liquidity: execution costs and joint exits on shared venues (blueprint section 7.2).

Two ways to price selling `size` USD on a venue:
- executable quotes (snapshot exit_venues.*.quotes): the all-in loss fraction is interpolated
  linearly between the quoted sizes, anchored at (0, 0) and made non-decreasing in size. Real
  liquidity has cliffs (sUSDe: 0.09% at 2m, 12.9% at 5m) that no single depth can represent.
  Beyond the largest quote, the curve is extended with the constant-product proxy calibrated on
  that last quote: an extrapolation, reported as such.
- proxy: constant-product depth, haircut = size^2 / (depth + size).

A crisis that removes a share r of the depth is applied the same way to both:
cost_k(size) = k x cost(size / k), k = 1 - r. For the proxy this is exactly
haircut(size, k x depth); for quotes it assumes the order book shrinks uniformly.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.risk.model import Venue


def haircut(size_usd, depth_usd):
    """Constant-product proxy: total execution loss of selling size into effective depth.

    Average price discount = size / (depth + size); total haircut = size^2 / (depth + size).
    A labeled proxy, not a universal law; used when no executable quote covers the size.
    """
    return size_usd * size_usd / (depth_usd + size_usd)


def crisis_depth(depth_usd, reduction_pct):
    return depth_usd * (1 - reduction_pct)


def curve_loss_fraction(curve: tuple[tuple[float, float], ...], size: float) -> float:
    """All-in loss fraction at `size` USD from executable quotes (see module docstring)."""
    if size <= 0:
        return 0.0
    prev_size, prev_loss, floor = 0.0, 0.0, 0.0
    for quoted_size, quoted_loss in curve:
        quoted_loss = max(quoted_loss, floor)  # a bigger trade never costs a smaller fraction
        if size <= quoted_size:
            return prev_loss + (quoted_loss - prev_loss) * (size - prev_size) / (quoted_size - prev_size)
        prev_size, prev_loss, floor = quoted_size, quoted_loss, quoted_loss
    if prev_loss <= 0:
        return 0.0
    depth = prev_size * (1 / prev_loss - 1)  # constant product through the last quote
    return size / (depth + size)


def exit_cost(venue: Venue, size_usd: float, depth_factor: float = 1.0) -> float:
    """Price impact (USD) of selling size_usd on the venue when its depth is scaled by depth_factor."""
    k = depth_factor * venue.depth_scale
    if not venue.curve:
        return haircut(size_usd, venue.effective_depth_usd * k)
    if k <= 0:
        return size_usd
    return size_usd * curve_loss_fraction(venue.curve, size_usd / k)


def coverage(venue: Venue, size_usd: float, depth_factor: float = 1.0) -> str:
    """How the cost at this size is known: quoted (within the quoted sizes), extrapolated or proxy."""
    if not venue.curve:
        return "proxy"
    equivalent = size_usd / (depth_factor * venue.depth_scale) if depth_factor * venue.depth_scale > 0 else float("inf")
    return "quoted" if equivalent <= venue.curve[-1][0] else "extrapolated"


def coverage_note(venue: Venue, size_usd: float, depth_factor: float = 1.0) -> str | None:
    """Warning when the size is priced beyond the largest executable quote."""
    if coverage(venue, size_usd, depth_factor) != "extrapolated":
        return None
    largest = venue.curve[-1][0]
    k = depth_factor * venue.depth_scale
    equivalent = f" (like {size_usd / k:,.0f} USD in today's book)" if k != 1 else ""
    return (f"{venue.venue_id}: selling {size_usd:,.0f} USD with {k:.0%} of normal depth left{equivalent} is beyond the "
            f"largest executable quote ({largest:,.0f} USD); cost extrapolated with the constant-product proxy "
            "through that quote.")


def joint_haircuts(sizes_by_venue: dict[str, list[float]], venues: dict[str, Venue],
                   depth_factor: float = 1.0) -> dict[str, float]:
    """Cost of selling every position on a venue at once (sizes summed, priced once)."""
    return {vid: exit_cost(venues[vid], sum(sizes), depth_factor) for vid, sizes in sizes_by_venue.items()}


def group_by_venue(items: list[tuple[str, float]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for venue, size in items:
        grouped[venue].append(size)
    return dict(grouped)
