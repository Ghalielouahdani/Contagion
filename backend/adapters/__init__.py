"""Protocol adapters (owner: P1). See README.md and backend/adapters/base.py for the interface."""

from __future__ import annotations


def default_adapters() -> list:
    """Adapters in dispatch order: the first one that accepts an entity handles it."""
    from backend.adapters.aave import AaveAdapter
    from backend.adapters.collateral import CollateralScanAdapter
    from backend.adapters.ethena import EthenaAdapter
    from backend.adapters.morpho import MorphoAdapter
    from backend.adapters.pendle import PendleAdapter
    from backend.adapters.tokens import Erc20Adapter, Erc4626Adapter

    morpho, aave = MorphoAdapter(), AaveAdapter()
    return [
        EthenaAdapter(),
        PendleAdapter(),
        morpho,
        aave,
        CollateralScanAdapter(morpho, aave),
        Erc4626Adapter(),
        Erc20Adapter(),
    ]
