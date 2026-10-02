import json
from datetime import date
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import AdStat, AudienceStat, Candidate, Product

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed.json"


def load_seed(db: Session, path: Path = SEED_FILE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    day = date.fromisoformat(data["period_end"])
    db.execute(delete(AdStat).where(AdStat.source == "seed"))
    for p in data["products"]:
        prod = db.get(Product, p["code"]) or Product(code=p["code"])
        prod.name, prod.category = p["name"], p["category"]
        db.merge(prod)
        db.add(AdStat(day=day, ad_account_id="seed", campaign_id=f"seed-{p['code']}",
                      campaign_name=f"{p['code']} {p['name']} (агрегат 90 днів)", product_code=p["code"],
                      spend=p["spend"], leads=p["leads"], source="seed"))
    db.execute(delete(AudienceStat).where(AudienceStat.period == "seed"))
    for age, gender, spend, leads in data["audience"]:
        db.add(AudienceStat(ad_account_id=data["audience_account"], period="seed", age=age, gender=gender,
                            spend=spend, leads=leads))
    added = 0
    existing = {c.name for c in db.query(Candidate).all()}
    for c in data["candidates"]:
        if c["name"] not in existing:
            db.add(Candidate(**c))
            added += 1
    db.commit()
    return {"products": len(data["products"]), "audience_rows": len(data["audience"]), "candidates_added": added}
