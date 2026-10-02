from app.models import Candidate, Product
from app.seed import load_seed


def test_pages_render_with_seed(client, db):
    load_seed(db)
    for path in ["/", "/products", "/products/id72", "/candidates", "/tests", "/audience", "/settings"]:
        r = client.get(path)
        assert r.status_code == 200, path
    body = client.get("/products").text
    assert "Подрібнювач" in body and "прибутковий" in body and "збиток" in body
    assert "Електрична щітка-скрабер" in client.get("/").text  # shortlist


def test_candidate_flow(client, db):
    r = client.post("/candidates", data={"name": "Тест товар", "query_en": "test", "expected_cpl_usd": "2,5"},
                    follow_redirects=False)
    assert r.status_code == 303
    c = db.query(Candidate).one()
    assert c.expected_cpl_usd == 2.5
    client.post(f"/candidates/{c.id}", data={b: "5" for b in
                ["trend", "ad_proof", "ua_saturation", "unit_economics", "audience_fit", "similarity"]})
    page = client.get(f"/candidates/{c.id}").text
    assert ">100<" in page and "В тест" in page
    # Ad Library without token -> error stored, page still renders
    client.post(f"/candidates/{c.id}/ad-library", data={"country": "DE", "query": "x"})
    assert "META_ACCESS_TOKEN" in client.get(f"/candidates/{c.id}").text


def test_settings_and_product_edit(client, db):
    client.post("/settings/economics", data={"approve_rate": "0.5"})
    assert "0.5" in client.get("/settings").text
    r = client.post("/settings/scoring", data={"trend": "50", "ad_proof": "20", "ua_saturation": "15",
                                               "unit_economics": "20", "audience_fit": "15", "similarity": "10",
                                               "test_threshold": "70", "watch_threshold": "55"})
    assert "Помилка" in r.text
    db.add(Product(code="id1", name="X"))
    db.commit()
    client.post("/products/id1", data={"name": "Новий", "status": "testing"})
    p = db.get(Product, "id1")
    assert p.name == "Новий" and p.status == "testing" and p.test_started is not None


def test_crm_upload(client, db):
    csv = "ID;Статус\n1;Отримано\n2;Повернення\n".encode()
    r = client.post("/settings/crm-import", files={"file": ("o.csv", csv, "text/csv")})
    assert "Імпортовано 2" in r.text


def test_basic_auth(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "dashboard_password", "secret")
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "secret")).status_code == 200
