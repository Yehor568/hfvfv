"""Unit economics: the same formulas as model/Product_Hunter_Model.xlsx (sheet «Економіка»)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EconomicsParams:
    product_margin_uah: float = 300.0      # sale price - purchase price
    upsell_margin_uah: float = 250.0       # average upsell margin per order
    upsell_commission: float = 0.23        # share of upsell margin paid to operators
    approve_rate: float = 0.64             # confirmed / leads
    buyout_rate: float = 0.82              # received / shipped
    return_cost_uah: float = 150.0         # cost of one refused parcel
    order_cost_uah: float = 23.0           # cost per confirmed order
    uah_per_usd: float = 41.5
    profit_reserve: float = 0.40           # target CPL = break-even * (1 - reserve)


def full_margin_uah(p: EconomicsParams) -> float:
    return p.product_margin_uah + p.upsell_margin_uah * (1 - p.upsell_commission)


def income_per_confirmed_uah(p: EconomicsParams) -> float:
    return p.buyout_rate * full_margin_uah(p) - (1 - p.buyout_rate) * p.return_cost_uah - p.order_cost_uah


def breakeven_cpl_uah(p: EconomicsParams) -> float:
    return p.approve_rate * income_per_confirmed_uah(p)


def breakeven_cpl_usd(p: EconomicsParams) -> float:
    return breakeven_cpl_uah(p) / p.uah_per_usd


def target_cpl_usd(p: EconomicsParams) -> float:
    return breakeven_cpl_usd(p) * (1 - p.profit_reserve)


def profit_per_lead_uah(p: EconomicsParams, cpl_usd: float) -> float:
    return breakeven_cpl_uah(p) - cpl_usd * p.uah_per_usd


def romi(p: EconomicsParams, cpl_usd: float) -> float:
    if cpl_usd <= 0:
        return 0.0
    return profit_per_lead_uah(p, cpl_usd) / (cpl_usd * p.uah_per_usd)


def status(p: EconomicsParams, cpl_usd: float) -> str:
    """'profitable' | 'thin' | 'loss'"""
    if cpl_usd <= target_cpl_usd(p):
        return "profitable"
    if cpl_usd <= breakeven_cpl_usd(p):
        return "thin"
    return "loss"
