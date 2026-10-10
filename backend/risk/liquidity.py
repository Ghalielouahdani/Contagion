"""Exit liquidity: execution haircuts and joint exits on shared venues (blueprint section 7.2)."""

from __future__ import annotations

from collections import defaultdict


def haircut(size_usd, depth_usd):
    """Constant-product proxy: total execution loss of selling size into effective depth.

    Average price discount = size / (depth + size); total haircut = size^2 / (depth + size).
    A labeled proxy, not a universal law; replace with executable quotes when available.
    """
    return size_usd * size_usd / (depth_usd + size_usd)


def crisis_depth(depth_usd, reduction_pct):
    return depth_usd * (1 - reduction_pct)


def joint_haircuts(sizes_by_venue: dict[str, list[float]], depth_by_venue: dict[str, float]) -> dict[str, float]:
    """Haircut of selling every position on a venue at once (sizes summed, priced once)."""
    return {venue: haircut(sum(sizes), depth_by_venue[venue]) for venue, sizes in sizes_by_venue.items()}


def group_by_venue(items: list[tuple[str, float]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for venue, size in items:
        grouped[venue].append(size)
    return dict(grouped)
