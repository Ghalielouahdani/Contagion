"""backend/execution/exit_cost.py — P3 : estimateur de coût de sortie interchangeable (section 7.2).

Coût de sortie = frais de la venue + gas + impact de prix, au prix d'AVANT le choc.

L'impact de prix vient de la première source qui répond, dans l'ordre de priorité :
    executable (devis réel) → pool_reserves (état de la pool) → proxy (size² / (depth + size)).

Une source est une fonction  source(venue_id, venue, size_usd) -> Decimal | None
qui renvoie l'impact de prix en USD (positif, hors frais de venue et gas), ou None si
elle n'a pas de prix pour cette taille. Seul le proxy est fourni ; P1 branche les autres :

    estimator = ExitCostEstimator(executable=ma_fonction_de_devis)
"""
from dataclasses import dataclass
from decimal import Decimal as D

PRIORITY = ("executable", "pool_reserves", "proxy")
# Vocabulaire du snapshot (P1, quote_method) → vocabulaire de decision_result (P3, quote_status)
DECLARED_METHOD = {"executable_quote": "executable", "pool_reserves": "pool_reserves", "proxy": "proxy"}


def proxy_impact(venue_id, venue, size):
    """Proxy produit constant sur la profondeur effective : size² / (depth + size)."""
    depth = venue.get("effective_depth_usd")
    if depth is None or D(depth) <= 0:
        return None
    return size * size / (D(depth) + size)


@dataclass(frozen=True)
class ExitQuote:
    fees_usd: D
    gas_usd: D
    price_impact_usd: D
    quote_status: str

    @property
    def total_usd(self):
        return self.fees_usd + self.gas_usd + self.price_impact_usd


class ExitCostEstimator:
    def __init__(self, executable=None, pool_reserves=None, proxy=proxy_impact):
        self.sources = {"executable": executable, "pool_reserves": pool_reserves, "proxy": proxy}

    def quote(self, venue_id, venue, size):
        """Coût de vendre `size` USD (> 0) sur la venue, ou None si aucun prix n'est disponible."""
        if venue is None or venue.get("fee_rate") is None or venue.get("gas_usd") is None:
            return None
        for status in PRIORITY:
            source = self.sources[status]
            impact = source(venue_id, venue, size) if source else None
            if impact is not None:
                return ExitQuote(size * D(venue["fee_rate"]), D(venue["gas_usd"]), D(impact), status)
        return None


DEFAULT_ESTIMATOR = ExitCostEstimator()
