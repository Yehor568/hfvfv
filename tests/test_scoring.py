import pytest

from app import scoring


def test_score_matches_excel():
    s = dict(trend=4, ad_proof=4, ua_saturation=3, unit_economics=3, audience_fit=5, similarity=3)
    assert scoring.score(s) == 74
    assert scoring.score(dict(trend=3, ad_proof=5, ua_saturation=2, unit_economics=2, audience_fit=4, similarity=5), 5) == 63


def test_missing_blocks_count_as_zero_and_bounds():
    assert scoring.score({"trend": 5}) == 20
    with pytest.raises(ValueError):
        scoring.score({"trend": 6})


def test_decision_and_filter():
    assert scoring.cpl_filter(None, 3.27, 5.46) is None
    assert scoring.cpl_filter(3.0, 3.27, 5.46) == "ok"
    assert scoring.cpl_filter(4.0, 3.27, 5.46) == "thin"
    assert scoring.cpl_filter(6.0, 3.27, 5.46) == "expensive"
    assert scoring.decision(80, "expensive") == "reject"
    assert scoring.decision(70, "ok") == "test"
    assert scoring.decision(60, None) == "watch"
    assert scoring.decision(40, "ok") == "reject"


def test_weights_validation():
    with pytest.raises(ValueError):
        scoring.validate_weights({**scoring.DEFAULT_WEIGHTS, "trend": 30})


def test_ad_proof_from_library():
    assert scoring.ad_proof_from_library(0, 0) == 0
    assert scoring.ad_proof_from_library(5, 0) == 1
    assert scoring.ad_proof_from_library(150, 12) == 5
