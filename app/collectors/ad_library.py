"""Meta Ad Library API (ads_archive): how many advertisers run a product and for how long.

Limitation of the official API: commercial ads are returned only for ads delivered in the EU/UK
(DSA transparency). For the US the public API returns political/issue ads only, so US checks go
through the manual Ad Library website for now.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings

EU_COUNTRIES = ("DE", "PL", "IT", "FR", "ES", "CZ", "RO", "NL", "AT")
MAX_ADS = 500


class AdLibraryError(RuntimeError):
    pass


def summarize(ads: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    long_running = 0
    pages = set()
    titles = []
    for ad in ads:
        pages.add(ad.get("page_id") or ad.get("page_name"))
        start = ad.get("ad_delivery_start_time")
        if start:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                long_running += 1
        for t in ad.get("ad_creative_link_titles") or []:
            if t and t not in titles and len(titles) < 10:
                titles.append(t)
    return {"active_ads": len(ads), "long_running_ads": long_running, "advertisers": len(pages),
            "sample_titles": titles}


def search(query: str, country: str, http: httpx.Client | None = None, token: str | None = None) -> dict:
    s = get_settings()
    token = token or s.meta_access_token
    if not token:
        raise AdLibraryError("META_ACCESS_TOKEN is not set")
    http = http or httpx.Client(timeout=60)
    url = f"https://graph.facebook.com/{s.meta_api_version}/ads_archive"
    params = {
        "access_token": token, "search_terms": query, "ad_reached_countries": json.dumps([country]),
        "ad_active_status": "ACTIVE", "ad_type": "ALL", "limit": 100,
        "fields": "id,page_id,page_name,ad_delivery_start_time,ad_creative_link_titles",
    }
    ads: list[dict] = []
    while url and len(ads) < MAX_ADS:
        r = http.get(url, params=params)
        body = r.json()
        if r.status_code != 200 or "error" in body:
            raise AdLibraryError(body.get("error", {}).get("message", r.text))
        ads.extend(body.get("data", []))
        url, params = body.get("paging", {}).get("next"), None
    return summarize(ads[:MAX_ADS])
