"""LP-CRM orders: CSV import (reliable) and API client.

The API client is UNVERIFIED: LP-CRM docs were not reachable while writing it. Method name and
parameters are configurable; run `python -m app.cli lpcrm-probe` on the server first and adjust
LPCRM_ORDERS_METHOD / field names if the response differs.
"""
import csv
import io
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import CrmOrder, Product

COLUMN_ALIASES = {
    "order_id": ("order_id", "id", "id замовлення", "№", "номер", "номер заказа", "номер замовлення", "заказ"),
    "created_at": ("created_at", "date", "дата", "дата створення", "дата создания", "дата заказа"),
    "product_id": ("product_id", "id товару", "id товара", "артикул"),
    "product": ("product", "товар", "товари", "товары", "назва товару", "название товара", "products"),
    "status": ("status", "статус"),
}
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                "%d.%m.%Y")


def parse_date(value: str | None) -> datetime | None:
    value = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def normalize_status(raw: str, status_map: dict) -> str:
    raw_l = (raw or "").strip().lower()
    if raw_l in status_map:
        return status_map[raw_l]
    for key, value in status_map.items():
        if key and key in raw_l:
            return value
    return "unknown"


def resolve_product(db: Session, product_id: str | None, name: str) -> str | None:
    if product_id:
        digits = re.sub(r"\D", "", str(product_id))
        if digits:
            return f"id{int(digits)}"
    name_l = (name or "").strip().lower()
    if not name_l:
        return None
    for p in db.query(Product).all():
        aliases = [a.strip().lower() for a in (p.crm_aliases or "").split(",") if a.strip()]
        if p.name and p.name.lower() == name_l:
            aliases.append(name_l)
        if any(a == name_l or a in name_l for a in aliases):
            return p.code
    return None


def _map_columns(header: list[str]) -> dict:
    cols = {}
    norm = [h.strip().lower() for h in header]
    for field, aliases in COLUMN_ALIASES.items():
        for i, h in enumerate(norm):
            if h in aliases:
                cols[field] = i
                break
    missing = {"order_id", "status"} - set(cols)
    if missing:
        raise ValueError(f"CSV: не знайдено колонки {sorted(missing)}. Є: {header}")
    return cols


def upsert_order(db: Session, status_map: dict, order_id: str, created_at, product_id, product_name, status_raw):
    order = db.get(CrmOrder, str(order_id)) or CrmOrder(order_id=str(order_id))
    order.created_at = created_at if isinstance(created_at, datetime) or created_at is None else parse_date(created_at)
    order.product_name = product_name or ""
    order.product_code = resolve_product(db, product_id, product_name)
    order.status_raw = status_raw or ""
    order.status = normalize_status(status_raw, status_map)
    db.merge(order)


def import_csv(db: Session, content: bytes | str, status_map: dict) -> dict:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader)
    cols = _map_columns(header)

    def get(row, field):
        i = cols.get(field)
        return row[i].strip() if i is not None and i < len(row) else None

    n, unknown = 0, set()
    for row in reader:
        if not row or not get(row, "order_id"):
            continue
        status_raw = get(row, "status") or ""
        upsert_order(db, status_map, get(row, "order_id"), parse_date(get(row, "created_at")),
                     get(row, "product_id"), get(row, "product") or "", status_raw)
        if normalize_status(status_raw, status_map) == "unknown":
            unknown.add(status_raw)
        n += 1
    db.commit()
    return {"orders": n, "unknown_statuses": sorted(unknown)}


class LpCrmClient:
    def __init__(self, domain: str | None = None, key: str | None = None, http: httpx.Client | None = None,
                 orders_method: str = "getOrdersByTime"):
        s = get_settings()
        self.domain = (domain or s.lpcrm_domain).replace("https://", "").strip("/")
        self.key = key or s.lpcrm_api_key
        self.http = http or httpx.Client(timeout=60)
        self.orders_method = orders_method
        if not self.domain or not self.key:
            raise RuntimeError("LPCRM_DOMAIN / LPCRM_API_KEY are not set")

    def call(self, method: str, **params) -> dict:
        r = self.http.post(f"https://{self.domain}/api/{method}.html", data={"key": self.key, **params})
        r.raise_for_status()
        return r.json()

    def orders(self, since: datetime, until: datetime) -> list[dict]:
        body = self.call(self.orders_method, created_from=since.strftime("%Y-%m-%d %H:%M:%S"),
                         created_to=until.strftime("%Y-%m-%d %H:%M:%S"))
        data = body.get("data", body)
        return list(data.values()) if isinstance(data, dict) else list(data or [])


def sync_api(db: Session, status_map: dict, days: int = 90, client: LpCrmClient | None = None) -> dict:
    client = client or LpCrmClient()
    until = datetime.now()
    orders = client.orders(until - timedelta(days=days), until)
    n = 0
    for o in orders:
        products = o.get("products") or [{}]
        first = products[0] if isinstance(products, list) else next(iter(products.values()), {})
        upsert_order(db, status_map, o.get("order_id") or o.get("id"), parse_date(o.get("order_time") or o.get("created_at")),
                     first.get("product_id"), first.get("name") or first.get("product_name") or "",
                     str(o.get("status_name") or o.get("status") or ""))
        n += 1
    db.commit()
    return {"orders": n}
