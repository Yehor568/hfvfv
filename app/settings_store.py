"""Business parameters editable from the dashboard, stored in the `settings` table."""
from dataclasses import asdict, fields

from sqlalchemy.orm import Session

from app.economics import EconomicsParams
from app.models import Setting
from app.scoring import DEFAULT_WEIGHTS, ScoringConfig, validate_weights

DEFAULT_TEST = {
    "daily_budget_usd": 14.0,
    "days": 3,
    "scale_budget_usd": 50.0,
    "min_approve_for_scale": 0.60,
    "kill_spend_multiplier": 3.0,
    "min_orders_for_product_rates": 30,
}

# LP-CRM statuses are configured per account; map their names to our categories.
DEFAULT_STATUS_MAP = {
    "новий": "new", "новый": "new", "new": "new",
    "прийнято": "approved", "принят": "approved", "підтверджено": "approved", "подтвержден": "approved",
    "відправлено": "shipped", "отправлен": "shipped",
    "отримано": "bought", "получен": "bought", "завершено": "bought", "оплачено": "bought", "викуплено": "bought",
    "повернення": "returned", "возврат": "returned", "відмова на пошті": "returned", "невикуп": "returned",
    "відміна": "cancelled", "отмена": "cancelled", "скасовано": "cancelled", "брак": "cancelled",
    "дубль": "cancelled", "недозвон": "cancelled",
}


def _get(db: Session, key: str, default):
    row = db.get(Setting, key)
    return row.value if row else default


def _put(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.commit()


def get_economics(db: Session) -> EconomicsParams:
    stored = _get(db, "economics", {})
    names = {f.name for f in fields(EconomicsParams)}
    return EconomicsParams(**{k: float(v) for k, v in stored.items() if k in names})


def save_economics(db: Session, params: EconomicsParams) -> None:
    _put(db, "economics", asdict(params))


def get_scoring(db: Session) -> ScoringConfig:
    stored = _get(db, "scoring", {})
    return ScoringConfig(
        weights={**DEFAULT_WEIGHTS, **stored.get("weights", {})},
        test_threshold=int(stored.get("test_threshold", 70)),
        watch_threshold=int(stored.get("watch_threshold", 55)),
    )


def save_scoring(db: Session, cfg: ScoringConfig) -> None:
    validate_weights(cfg.weights)
    _put(db, "scoring", {"weights": cfg.weights, "test_threshold": cfg.test_threshold,
                         "watch_threshold": cfg.watch_threshold})


def get_test_protocol(db: Session) -> dict:
    return {**DEFAULT_TEST, **_get(db, "test_protocol", {})}


def save_test_protocol(db: Session, values: dict) -> None:
    _put(db, "test_protocol", {k: float(values[k]) for k in DEFAULT_TEST if k in values})


def get_status_map(db: Session) -> dict:
    return _get(db, "crm_status_map", DEFAULT_STATUS_MAP)


def save_status_map(db: Session, mapping: dict) -> None:
    _put(db, "crm_status_map", {k.strip().lower(): v for k, v in mapping.items() if k.strip()})
