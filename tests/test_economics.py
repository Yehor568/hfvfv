import pytest

from app import economics as eco
from app.economics import EconomicsParams

P = EconomicsParams()  # user's numbers as of 02.10.2026


def test_matches_excel_model():
    # Values verified in model/Product_Hunter_Model.xlsx (sheet «Економіка»)
    assert eco.full_margin_uah(P) == pytest.approx(492.5)
    assert eco.income_per_confirmed_uah(P) == pytest.approx(353.85)
    assert eco.breakeven_cpl_usd(P) == pytest.approx(5.4570, abs=1e-3)
    assert eco.target_cpl_usd(P) == pytest.approx(3.2742, abs=1e-3)


def test_status_and_romi():
    assert eco.status(P, 2.2) == "profitable"
    assert eco.status(P, 3.8) == "thin"
    assert eco.status(P, 5.94) == "loss"
    assert eco.romi(P, 2.1954503844745514) == pytest.approx(1.4856, abs=1e-3)
    assert eco.romi(P, 0) == 0
