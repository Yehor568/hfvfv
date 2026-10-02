import secrets
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from datetime import date

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from urllib.parse import quote
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import analytics, economics as eco, scoring
from app.collectors import ad_library, lpcrm
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.economics import EconomicsParams
from app.models import AdLibraryCheck, Candidate, Product
from app.settings_store import (DEFAULT_TEST, get_economics, get_scoring, get_status_map, get_test_protocol,
                                save_economics, save_scoring, save_status_map, save_test_protocol)

BASE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Product Hunter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
security = HTTPBasic(auto_error=False)

VERDICT = {"profitable": ("✅ прибутковий", "ok"), "thin": ("⚠️ тонка маржа", "warn"), "loss": ("❌ збиток", "bad")}
DECISION = {"test": ("В тест", "ok"), "watch": ("Спостерігати", "warn"), "reject": ("Відкинути", "bad")}
TEST_VERDICT = {"running": ("Йде тест", "muted"), "kill": ("Стоп", "bad"), "scale": ("Масштабувати", "ok"),
                "iterate": ("Нові креативи", "warn")}
templates.env.globals.update(VERDICT=VERDICT, DECISION=DECISION, TEST_VERDICT=TEST_VERDICT,
                             BLOCKS=scoring.BLOCKS, BLOCK_LABELS=scoring.BLOCK_LABELS)


def usd(v):
    return "—" if v is None else f"${v:,.2f}"


def uah(v):
    return "—" if v is None else f"{v:,.0f} ₴".replace(",", " ")


def pct(v):
    return "—" if v is None else f"{v * 100:.1f}%"


templates.env.filters.update(usd=usd, uah=uah, pct=pct)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def auth(creds: HTTPBasicCredentials | None = Depends(security)):
    s = get_settings()
    if not s.dashboard_password:
        return
    ok = creds and secrets.compare_digest(creds.username, s.dashboard_user) and secrets.compare_digest(
        creds.password, s.dashboard_password)
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


def back_to_settings(msg: str):
    return RedirectResponse(f"/settings?msg={quote(msg)}", status.HTTP_303_SEE_OTHER)


def render(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)


def candidate_view(c: Candidate, params: EconomicsParams, cfg: scoring.ScoringConfig) -> dict:
    sc = scoring.score({b: getattr(c, b) for b in scoring.BLOCKS}, c.risk_penalty, cfg)
    flag = scoring.cpl_filter(c.expected_cpl_usd, eco.target_cpl_usd(params), eco.breakeven_cpl_usd(params))
    margin = (c.sale_price_uah - c.purchase_price_uah) if c.sale_price_uah and c.purchase_price_uah else None
    return {"c": c, "score": sc, "flag": flag, "decision": scoring.decision(sc, flag, cfg), "margin": margin,
            "filled": sum(getattr(c, b) is not None for b in scoring.BLOCKS)}


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def overview(request: Request, db: Session = Depends(get_db)):
    params, cfg = get_economics(db), get_scoring(db)
    products = analytics.product_summaries(db)
    cands = sorted((candidate_view(c, params, cfg) for c in db.scalars(select(Candidate))), key=lambda v: -v["score"])
    totals = {
        "spend": sum(p.spend for p in products), "leads": sum(p.leads for p in products),
        "profit": sum(p.profit_uah or 0 for p in products),
    }
    totals["cpl"] = totals["spend"] / totals["leads"] if totals["leads"] else None
    totals["romi"] = totals["profit"] / (totals["spend"] * params.uah_per_usd) if totals["spend"] else None
    counts = {k: sum(p.verdict == k for p in products) for k in VERDICT}
    testing = [(p, analytics.evaluate_test(db, p)) for p in db.scalars(select(Product).where(Product.status == "testing"))]
    return render(request, "overview.html", params=params, be=eco.breakeven_cpl_usd(params),
                  target=eco.target_cpl_usd(params), totals=totals, counts=counts,
                  shortlist=[v for v in cands if v["decision"] == "test"][:10], testing=testing,
                  unassigned=analytics.unassigned_spend(db), crm=analytics.crm_rates(db))


@app.get("/products", response_class=HTMLResponse, dependencies=[Depends(auth)])
def products_page(request: Request, since: date | None = None, until: date | None = None,
                  db: Session = Depends(get_db)):
    return render(request, "products.html", rows=analytics.product_summaries(db, since, until), since=since,
                  until=until, unassigned=analytics.unassigned_spend(db))


@app.get("/products/{code}", response_class=HTMLResponse, dependencies=[Depends(auth)])
def product_page(request: Request, code: str, db: Session = Depends(get_db)):
    p = db.get(Product, code)
    if not p:
        raise HTTPException(404)
    summary = next((s for s in analytics.product_summaries(db) if s.code == code), None)
    from app.models import AdStat
    daily = db.scalars(select(AdStat).where(AdStat.product_code == code).order_by(AdStat.day.desc()).limit(200)).all()
    return render(request, "product.html", p=p, s=summary, daily=daily, crm=analytics.crm_rates(db, code),
                  test=analytics.evaluate_test(db, p) if p.status == "testing" else None)


@app.post("/products/{code}", dependencies=[Depends(auth)])
def product_save(code: str, name: str = Form(""), category: str = Form(""), status_: str = Form("active", alias="status"),
                 crm_aliases: str = Form(""), test_started: str = Form(""), notes: str = Form(""),
                 db: Session = Depends(get_db)):
    p = db.get(Product, code)
    if not p:
        raise HTTPException(404)
    p.name, p.category, p.status, p.crm_aliases, p.notes = name, category, status_, crm_aliases, notes
    p.test_started = date.fromisoformat(test_started) if test_started else (
        date.today() if status_ == "testing" and not p.test_started else p.test_started)
    db.commit()
    return RedirectResponse(f"/products/{code}", status.HTTP_303_SEE_OTHER)


@app.get("/candidates", response_class=HTMLResponse, dependencies=[Depends(auth)])
def candidates_page(request: Request, db: Session = Depends(get_db)):
    params, cfg = get_economics(db), get_scoring(db)
    rows = sorted((candidate_view(c, params, cfg) for c in db.scalars(select(Candidate))), key=lambda v: -v["score"])
    return render(request, "candidates.html", rows=rows, target=eco.target_cpl_usd(params),
                  be=eco.breakeven_cpl_usd(params))


def _int_or_none(v: str):
    return int(v) if v not in ("", None) else None


def _float_or_none(v: str):
    return float(v.replace(",", ".")) if v not in ("", None) else None


@app.post("/candidates", dependencies=[Depends(auth)])
async def candidate_create(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    c = Candidate(name=form.get("name", "").strip() or "Без назви")
    _apply_candidate_form(c, form)
    db.add(c)
    db.commit()
    return RedirectResponse(f"/candidates/{c.id}", status.HTTP_303_SEE_OTHER)


def _apply_candidate_form(c: Candidate, form) -> None:
    for f in ("name", "query_en", "category", "comment"):
        if f in form:
            setattr(c, f, form.get(f, "").strip())
    for b in scoring.BLOCKS:
        if b in form:
            v = _int_or_none(form.get(b))
            if v is not None and not 0 <= v <= 5:
                raise HTTPException(400, f"{b}: 0..5")
            setattr(c, b, v)
    if "risk_penalty" in form:
        c.risk_penalty = max(0, min(20, _int_or_none(form.get("risk_penalty")) or 0))
    for f in ("expected_cpl_usd", "purchase_price_uah", "sale_price_uah"):
        if f in form:
            setattr(c, f, _float_or_none(form.get(f)))


@app.get("/candidates/{cid}", response_class=HTMLResponse, dependencies=[Depends(auth)])
def candidate_page(request: Request, cid: int, db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if not c:
        raise HTTPException(404)
    db.refresh(c)
    params, cfg = get_economics(db), get_scoring(db)
    return render(request, "candidate.html", v=candidate_view(c, params, cfg), cfg=cfg,
                  countries=ad_library.EU_COUNTRIES, prompt=psychology_prompt(c))


@app.post("/candidates/{cid}", dependencies=[Depends(auth)])
async def candidate_save(request: Request, cid: int, db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if not c:
        raise HTTPException(404)
    form = await request.form()
    if form.get("_action") == "delete":
        db.delete(c)
        db.commit()
        return RedirectResponse("/candidates", status.HTTP_303_SEE_OTHER)
    _apply_candidate_form(c, form)
    db.commit()
    return RedirectResponse(f"/candidates/{cid}", status.HTTP_303_SEE_OTHER)


@app.post("/candidates/{cid}/ad-library", dependencies=[Depends(auth)])
def candidate_ad_library(cid: int, country: str = Form("DE"), query: str = Form(""), db: Session = Depends(get_db)):
    c = db.get(Candidate, cid)
    if not c:
        raise HTTPException(404)
    q = query.strip() or c.query_en or c.name
    check = AdLibraryCheck(candidate_id=cid, country=country, query=q)
    try:
        res = ad_library.search(q, country)
        check.active_ads, check.long_running_ads = res["active_ads"], res["long_running_ads"]
        check.advertisers, check.sample_titles = res["advertisers"], res["sample_titles"]
        if c.ad_proof is None:
            c.ad_proof = scoring.ad_proof_from_library(res["active_ads"], res["long_running_ads"])
    except Exception as e:  # shown in the UI
        check.error = str(e)
    db.add(check)
    db.commit()
    return RedirectResponse(f"/candidates/{cid}", status.HTTP_303_SEE_OTHER)


def psychology_prompt(c: Candidate) -> str:
    titles = []
    for chk in c.library_checks[:3]:
        titles += chk.sample_titles or []
    titles_txt = "\n".join(f"- {t}" for t in titles[:15]) or "<ВСТАВТЕ тексти реклами конкурентів>"
    return f"""Ти — маркетолог для українського ринку товарів з оплатою при отриманні.
Наша ЦА: переважно жінки 45–65+ (також чоловіки 45+), практичні, хочуть полегшити побут;
довіряють «німецькій якості»; бояться, що товар не працює або підробка. Продаємо через лендінг + Meta Ads.

Товар: {c.name}{f" ({c.query_en})" if c.query_en else ""}{f", ціна {c.sale_price_uah:.0f} грн" if c.sale_price_uah else ""}

Заголовки реклами конкурентів (Meta Ad Library):
{titles_txt}

Коментарі та відгуки:
<ВСТАВТЕ 20–30 коментарів і відгуків 1–2★ та 5★>

Зроби:
1. Топ-5 болей і топ-5 бажань покупця (з цитатами).
2. Топ-5 заперечень і як закрити кожне на лендінгу.
3. 5 кутів для відеокреативів (хук перших 3 секунд + сценарій 15–30 с) для української аудиторії 45+.
4. Структура лендінгу: оффер, блоки, FAQ, гарантія, блок довіри.
5. Ідеї допродажу, щоб підняти маржу.
6. Ризики для модерації Meta.
7. Оцінку 0–5 для блоку «Відповідність ЦА 45+» з поясненням."""


@app.get("/tests", response_class=HTMLResponse, dependencies=[Depends(auth)])
def tests_page(request: Request, db: Session = Depends(get_db)):
    rows = [(p, analytics.evaluate_test(db, p)) for p in db.scalars(select(Product).where(Product.status == "testing"))]
    return render(request, "tests.html", rows=rows, proto=get_test_protocol(db))


@app.get("/audience", response_class=HTMLResponse, dependencies=[Depends(auth)])
def audience_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "audience.html", rows=analytics.audience_table(db))


@app.get("/settings", response_class=HTMLResponse, dependencies=[Depends(auth)])
def settings_page(request: Request, msg: str = "", db: Session = Depends(get_db)):
    params = get_economics(db)
    return render(request, "settings.html", params=params, cfg=get_scoring(db), proto=get_test_protocol(db),
                  status_map=get_status_map(db), msg=msg, be=eco.breakeven_cpl_usd(params),
                  target=eco.target_cpl_usd(params), econ_fields=[f.name for f in fields(EconomicsParams)])


@app.post("/settings/economics", dependencies=[Depends(auth)])
async def settings_economics(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    params = get_economics(db)
    updates = {f.name: float(str(form[f.name]).replace(",", ".")) for f in fields(EconomicsParams) if form.get(f.name)}
    save_economics(db, replace(params, **updates))
    return back_to_settings("Економіку збережено")


@app.post("/settings/scoring", dependencies=[Depends(auth)])
async def settings_scoring(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        cfg = scoring.ScoringConfig(weights={b: float(form[b]) for b in scoring.BLOCKS},
                                    test_threshold=int(form["test_threshold"]),
                                    watch_threshold=int(form["watch_threshold"]))
        save_scoring(db, cfg)
        msg = "Ваги збережено"
    except (ValueError, KeyError) as e:
        msg = f"Помилка: {e}"
    return back_to_settings(msg)


@app.post("/settings/test", dependencies=[Depends(auth)])
async def settings_test(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    save_test_protocol(db, {k: str(form[k]).replace(",", ".") for k in DEFAULT_TEST if form.get(k)})
    return back_to_settings("Протокол збережено")


@app.post("/settings/status-map", dependencies=[Depends(auth)])
def settings_status_map(mapping: str = Form(""), db: Session = Depends(get_db)):
    pairs = {}
    for line in mapping.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            pairs[k] = v.strip()
    save_status_map(db, pairs)
    return back_to_settings("Статуси збережено")


@app.post("/settings/crm-import", dependencies=[Depends(auth)])
async def settings_crm_import(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        res = lpcrm.import_csv(db, await file.read(), get_status_map(db))
        msg = f"Імпортовано {res['orders']} замовлень"
        if res["unknown_statuses"]:
            msg += f". Невідомі статуси: {', '.join(res['unknown_statuses'][:10])}"
    except Exception as e:
        msg = f"Помилка імпорту: {e}"
    return back_to_settings(msg)
