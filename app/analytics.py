"""Joins Meta spend/leads with LP-CRM approve/buyout rates and unit economics."""
from dataclasses import dataclass, replace
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import economics as eco
from app.models import AdStat, AudienceStat, CrmOrder, Product
from app.settings_store import get_economics, get_test_protocol

APPROVED_STATES = ("approved", "shipped", "bought", "returned")


@dataclass
class CrmRates:
    orders: int
    approve_rate: float | None
    buyout_rate: float | None


@dataclass
class ProductSummary:
    code: str
    name: str
    status: str
    spend: float
    leads: int
    cpl: float | None
    approve_rate: float
    buyout_rate: float
    rates_source: str  # 'crm' | 'default'
    crm_orders: int
    breakeven_cpl: float
    target_cpl: float
    profit_uah: float | None
    romi: float | None
    verdict: str | None  # profitable | thin | loss


def crm_rates(db: Session, product_code: str | None = None, since: date | None = None) -> CrmRates:
    q = select(CrmOrder.status, func.count()).group_by(CrmOrder.status)
    if product_code:
        q = q.where(CrmOrder.product_code == product_code)
    if since:
        q = q.where(CrmOrder.created_at >= since)
    counts = dict(db.execute(q).all())
    decided = sum(counts.get(s, 0) for s in ("approved", "shipped", "bought", "returned", "cancelled"))
    approved = sum(counts.get(s, 0) for s in APPROVED_STATES)
    finished = counts.get("bought", 0) + counts.get("returned", 0)
    total = sum(counts.values())
    return CrmRates(
        orders=total,
        approve_rate=approved / decided if decided else None,
        buyout_rate=counts.get("bought", 0) / finished if finished else None,
    )


def product_params(db: Session, code: str, since: date | None = None) -> tuple[eco.EconomicsParams, str, int]:
    base = get_economics(db)
    min_orders = int(get_test_protocol(db)["min_orders_for_product_rates"])
    r = crm_rates(db, code, since)
    if r.orders >= min_orders and r.approve_rate is not None and r.buyout_rate is not None:
        return replace(base, approve_rate=r.approve_rate, buyout_rate=r.buyout_rate), "crm", r.orders
    return base, "default", r.orders


def product_summaries(db: Session, since: date | None = None, until: date | None = None) -> list[ProductSummary]:
    q = select(AdStat.product_code, func.sum(AdStat.spend), func.sum(AdStat.leads)).group_by(AdStat.product_code)
    if since:
        q = q.where(AdStat.day >= since)
    if until:
        q = q.where(AdStat.day <= until)
    rows = {code: (spend or 0.0, leads or 0) for code, spend, leads in db.execute(q).all()}
    products = {p.code: p for p in db.scalars(select(Product))}
    out = []
    for code in sorted(set(rows) | set(products), key=lambda c: -(rows.get(c, (0, 0))[0])):
        if code is None:
            continue
        spend, leads = rows.get(code, (0.0, 0))
        p = products.get(code)
        params, source, n = product_params(db, code, since)
        cpl = spend / leads if leads else None
        out.append(ProductSummary(
            code=code, name=p.name if p else code, status=p.status if p else "active",
            spend=spend, leads=leads, cpl=cpl,
            approve_rate=params.approve_rate, buyout_rate=params.buyout_rate, rates_source=source, crm_orders=n,
            breakeven_cpl=eco.breakeven_cpl_usd(params), target_cpl=eco.target_cpl_usd(params),
            profit_uah=eco.profit_per_lead_uah(params, cpl) * leads if cpl is not None else None,
            romi=eco.romi(params, cpl) if cpl is not None else None,
            verdict=eco.status(params, cpl) if cpl is not None else None,
        ))
    return out


def unassigned_spend(db: Session) -> float:
    return db.scalar(select(func.coalesce(func.sum(AdStat.spend), 0)).where(AdStat.product_code.is_(None))) or 0.0


def audience_table(db: Session) -> list[dict]:
    q = (select(AudienceStat.age, AudienceStat.gender, func.sum(AudienceStat.spend), func.sum(AudienceStat.leads),
                func.sum(AudienceStat.clicks), func.sum(AudienceStat.impressions))
         .group_by(AudienceStat.age, AudienceStat.gender).order_by(AudienceStat.age, AudienceStat.gender))
    rows = []
    total_spend = 0.0
    for age, gender, spend, leads, clicks, imps in db.execute(q).all():
        total_spend += spend or 0
        rows.append({"age": age, "gender": gender, "spend": spend or 0, "leads": leads or 0,
                     "cpl": (spend / leads) if leads else None,
                     "ctr": (clicks / imps) if imps else None})
    for r in rows:
        r["share"] = r["spend"] / total_spend if total_spend else 0
    return rows


def evaluate_test(db: Session, product: Product) -> dict:
    """Apply the test protocol to a product in testing."""
    proto = get_test_protocol(db)
    since = product.test_started
    params, source, n = product_params(db, product.code, since)
    q = select(func.coalesce(func.sum(AdStat.spend), 0), func.coalesce(func.sum(AdStat.leads), 0)).where(
        AdStat.product_code == product.code)
    if since:
        q = q.where(AdStat.day >= since)
    spend, leads = db.execute(q).one()
    target, be = eco.target_cpl_usd(params), eco.breakeven_cpl_usd(params)
    kill_spend = proto["kill_spend_multiplier"] * target
    cpl = spend / leads if leads else None
    r = crm_rates(db, product.code, since)
    if spend < kill_spend:
        verdict, reason = "running", f"ще замало даних: спенд ${spend:.2f} з ${kill_spend:.2f}"
    elif cpl is None or cpl > be:
        verdict, reason = "kill", "ліди дорожчі за беззбиток" if cpl else "немає лідів після kill-спенду"
    elif cpl <= target and (r.approve_rate is None or r.approve_rate >= proto["min_approve_for_scale"]):
        verdict = "scale"
        reason = "CPL у цілі" + ("" if r.approve_rate is not None else "; апрув ще невідомий — перевірте в LP-CRM")
    else:
        verdict, reason = "iterate", "CPL між ціллю і беззбитком або низький апрув: нові креативи/офер ще 2 дні"
    return {"spend": spend, "leads": leads, "cpl": cpl, "target": target, "breakeven": be,
            "kill_spend": kill_spend, "approve": r.approve_rate, "verdict": verdict, "reason": reason,
            "rates_source": source}
