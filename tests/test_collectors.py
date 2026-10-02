from datetime import date, datetime, timezone

import httpx

from app.analytics import crm_rates, product_summaries, evaluate_test
from app.collectors import ad_library, lpcrm, meta_ads
from app.models import AdStat, Product
from app.settings_store import DEFAULT_STATUS_MAP


def mock_http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_leads_from_actions_no_double_count():
    acts = [{"action_type": "lead", "value": "7"}, {"action_type": "offsite_conversion.fb_pixel_lead", "value": "5"}]
    assert meta_ads.leads_from_actions(acts) == 5
    assert meta_ads.leads_from_actions(None) == 0


def test_meta_sync_with_paging(db):
    pages = {
        "insights1": {"data": [{"date_start": "2026-09-30", "campaign_id": "1", "spend": "10.5", "impressions": "1000",
                                "clicks": "50", "campaign_name": "id260_Max_rk1_блендер_16.09_50$",
                                "actions": [{"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"}]}],
                      "paging": {"next": "https://graph.facebook.com/v21.0/next-page"}},
        "insights2": {"data": [{"date_start": "2026-09-30", "campaign_id": "2", "spend": "3", "campaign_name": "no code"}]},
        "audience": {"data": [{"age": "55-64", "gender": "female", "spend": "8", "actions": []}]},
    }

    def handler(req: httpx.Request):
        if "next-page" in str(req.url):
            return httpx.Response(200, json=pages["insights2"])
        if req.url.params.get("breakdowns"):
            return httpx.Response(200, json=pages["audience"])
        return httpx.Response(200, json=pages["insights1"])

    client = meta_ads.MetaClient(token="t", version="v21.0", http=mock_http(handler))
    res = meta_ads.sync(db, days=7, client=client, accounts=["123"])
    assert res["123"] == {"campaign_days": 2, "audience_rows": 1}
    assert db.get(Product, "id260").name == "блендер"
    rows = db.query(AdStat).all()
    assert {r.product_code for r in rows} == {"id260", None}
    # idempotent
    meta_ads.sync(db, days=7, client=client, accounts=["123"])
    assert db.query(AdStat).count() == 2


def test_meta_error_is_reported(db):
    client = meta_ads.MetaClient(token="t", http=mock_http(
        lambda r: httpx.Response(400, json={"error": {"message": "Invalid token"}})))
    assert meta_ads.sync(db, client=client, accounts=["1"]) == {"1": {"error": "Invalid token"}}


def test_ad_library_summary():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    ads = [{"page_id": "a", "ad_delivery_start_time": "2026-08-01", "ad_creative_link_titles": ["X"]},
           {"page_id": "a", "ad_delivery_start_time": "2026-09-30T10:00:00+0000"},
           {"page_id": "b", "ad_delivery_start_time": "2026-07-01"}]
    s = ad_library.summarize(ads, now)
    assert s == {"active_ads": 3, "long_running_ads": 2, "advertisers": 2, "sample_titles": ["X"]}


def test_ad_library_search(monkeypatch):
    def handler(req):
        assert req.url.params["ad_reached_countries"] == '["DE"]'
        return httpx.Response(200, json={"data": [{"page_id": "p", "ad_delivery_start_time": "2020-01-01"}]})
    res = ad_library.search("vibration plate", "DE", http=mock_http(handler), token="t")
    assert res["active_ads"] == 1 and res["long_running_ads"] == 1


CSV = """ID замовлення;Дата;ID товару;Товар;Статус
1;01.09.2026 10:00;72;Подрібнювач;Отримано
2;01.09.2026 11:00;72;Подрібнювач;Повернення
3;02.09.2026;72;Подрібнювач;Відміна
4;02.09.2026;;Блендер Zepline;Відправлено
5;03.09.2026;72;Подрібнювач;Щось нове
"""


def test_crm_csv_import_and_rates(db):
    db.add(Product(code="id260", name="Блендер", crm_aliases="блендер zepline"))
    db.commit()
    res = lpcrm.import_csv(db, CSV.encode("utf-8-sig"), DEFAULT_STATUS_MAP)
    assert res == {"orders": 5, "unknown_statuses": ["Щось нове"]}
    r = crm_rates(db, "id72")
    assert r.orders == 4
    assert r.approve_rate == 2 / 3  # bought + returned out of decided (incl. cancelled)
    assert r.buyout_rate == 0.5
    assert crm_rates(db, "id260").orders == 1
    lpcrm.import_csv(db, CSV, DEFAULT_STATUS_MAP)  # re-import does not duplicate
    assert crm_rates(db).orders == 5


def test_lpcrm_api_client_parsing(db):
    def handler(req):
        assert req.url.path == "/api/getOrdersByTime.html"
        assert b"key=k" in req.content
        return httpx.Response(200, json={"status": "ok", "data": {"10": {
            "order_id": "10", "order_time": "2026-09-01 10:00:00", "status_name": "Отримано",
            "products": [{"product_id": "72", "name": "Подрібнювач"}]}}})
    cl = lpcrm.LpCrmClient(domain="x.lp-crm.biz", key="k", http=mock_http(handler))
    assert lpcrm.sync_api(db, DEFAULT_STATUS_MAP, client=cl) == {"orders": 1}
    assert crm_rates(db, "id72").buyout_rate == 1.0


def test_product_rates_switch_to_crm_and_test_verdict(db):
    db.add(Product(code="id72", name="Подрібнювач", status="testing", test_started=date(2026, 9, 1)))
    db.add(AdStat(day=date(2026, 9, 2), ad_account_id="1", campaign_id="c", campaign_name="id72", product_code="id72",
                  spend=40.0, leads=20))
    db.commit()
    s = product_summaries(db)[0]
    assert s.rates_source == "default" and s.verdict == "profitable"
    v = evaluate_test(db, db.get(Product, "id72"))
    assert v["verdict"] == "scale" and v["cpl"] == 2.0
