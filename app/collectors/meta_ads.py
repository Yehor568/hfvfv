"""Meta Marketing API: daily campaign stats and age/gender breakdown for our ad accounts."""
import json
from datetime import date, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AdStat, AudienceStat, Product
from app.naming import guess_product_name, product_code

LEAD_ACTIONS = ("offsite_conversion.fb_pixel_lead", "lead", "onsite_conversion.lead_grouped")


class MetaApiError(RuntimeError):
    pass


def leads_from_actions(actions: list[dict] | None) -> int:
    """Pick the first lead action type present (avoids double counting pixel + aggregated lead)."""
    by_type = {a.get("action_type"): a.get("value") for a in actions or []}
    for t in LEAD_ACTIONS:
        if t in by_type:
            return int(float(by_type[t]))
    return 0


class MetaClient:
    def __init__(self, token: str | None = None, version: str | None = None, http: httpx.Client | None = None):
        s = get_settings()
        self.token = token or s.meta_access_token
        self.base = f"https://graph.facebook.com/{version or s.meta_api_version}"
        self.http = http or httpx.Client(timeout=60)
        if not self.token:
            raise MetaApiError("META_ACCESS_TOKEN is not set")

    def _paged(self, path: str, params: dict):
        url, params = f"{self.base}/{path}", {**params, "access_token": self.token}
        while url:
            r = self.http.get(url, params=params)
            body = r.json()
            if r.status_code != 200 or "error" in body:
                raise MetaApiError(body.get("error", {}).get("message", r.text))
            yield from body.get("data", [])
            url, params = body.get("paging", {}).get("next"), None

    def campaign_daily(self, account_id: str, since: date, until: date):
        return self._paged(f"act_{account_id}/insights", {
            "level": "campaign", "time_increment": 1, "limit": 500,
            "fields": "campaign_id,campaign_name,spend,impressions,clicks,actions",
            "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        })

    def audience(self, account_id: str, since: date, until: date):
        return self._paged(f"act_{account_id}/insights", {
            "level": "account", "breakdowns": "age,gender", "limit": 500,
            "fields": "spend,impressions,clicks,actions",
            "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        })


def ensure_product(db: Session, code: str, campaign_name: str) -> None:
    if code and not db.get(Product, code):
        db.add(Product(code=code, name=guess_product_name(campaign_name)))
        db.flush()


def upsert_campaign_rows(db: Session, account_id: str, rows) -> int:
    n = 0
    for row in rows:
        day = date.fromisoformat(row["date_start"])
        code = product_code(row.get("campaign_name", ""))
        if code:
            ensure_product(db, code, row["campaign_name"])
        existing = db.scalar(select(AdStat).where(AdStat.day == day, AdStat.campaign_id == row["campaign_id"]))
        stat = existing or AdStat(day=day, campaign_id=row["campaign_id"], ad_account_id=account_id)
        stat.campaign_name = row.get("campaign_name", "")
        stat.product_code = code
        stat.spend = float(row.get("spend", 0) or 0)
        stat.impressions = int(row.get("impressions", 0) or 0)
        stat.clicks = int(row.get("clicks", 0) or 0)
        stat.leads = leads_from_actions(row.get("actions"))
        stat.source = "api"
        if not existing:
            db.add(stat)
        n += 1
    db.commit()
    return n


def upsert_audience_rows(db: Session, account_id: str, period: str, rows) -> int:
    n = 0
    for row in rows:
        key = dict(ad_account_id=account_id, period=period, age=row["age"], gender=row["gender"])
        existing = db.scalar(select(AudienceStat).filter_by(**key))
        stat = existing or AudienceStat(**key)
        stat.spend = float(row.get("spend", 0) or 0)
        stat.impressions = int(row.get("impressions", 0) or 0)
        stat.clicks = int(row.get("clicks", 0) or 0)
        stat.leads = leads_from_actions(row.get("actions"))
        if not existing:
            db.add(stat)
        n += 1
    db.commit()
    return n


def sync(db: Session, days: int = 90, client: MetaClient | None = None, accounts: list[str] | None = None) -> dict:
    client = client or MetaClient()
    accounts = accounts or get_settings().ad_account_ids
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=days - 1)
    result = {}
    for acc in accounts:
        try:
            n = upsert_campaign_rows(db, acc, client.campaign_daily(acc, since, until))
            a = upsert_audience_rows(db, acc, f"last_{days}d", client.audience(acc, since, until))
            result[acc] = {"campaign_days": n, "audience_rows": a}
        except MetaApiError as e:
            db.rollback()
            result[acc] = {"error": str(e)}
    return result
