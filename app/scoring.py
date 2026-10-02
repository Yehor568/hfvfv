"""Product Score 0–100 (sheet «Скоринг» of the Excel model)."""
from dataclasses import dataclass, field

BLOCKS = ("trend", "ad_proof", "ua_saturation", "unit_economics", "audience_fit", "similarity")

BLOCK_LABELS = {
    "trend": "Тренд",
    "ad_proof": "Реклама US/EU",
    "ua_saturation": "Насиченість UA (5 = вільно)",
    "unit_economics": "Юніт-економіка",
    "audience_fit": "ЦА 45+",
    "similarity": "Схожість з переможцями",
}

DEFAULT_WEIGHTS = {
    "trend": 20,
    "ad_proof": 20,
    "ua_saturation": 15,
    "unit_economics": 20,
    "audience_fit": 15,
    "similarity": 10,
}


@dataclass(frozen=True)
class ScoringConfig:
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    test_threshold: int = 70
    watch_threshold: int = 55


def validate_weights(weights: dict) -> None:
    missing = set(BLOCKS) - set(weights)
    if missing:
        raise ValueError(f"missing weights: {sorted(missing)}")
    if round(sum(weights[b] for b in BLOCKS)) != 100:
        raise ValueError("weights must sum to 100")


def score(scores: dict, risk_penalty: float = 0, config: ScoringConfig | None = None) -> int:
    """scores: block -> 0..5. Missing blocks count as 0."""
    config = config or ScoringConfig()
    total = 0.0
    for b in BLOCKS:
        v = scores.get(b) or 0
        if not 0 <= v <= 5:
            raise ValueError(f"{b} must be 0..5, got {v}")
        total += v * config.weights[b]
    return round(total / 5 - (risk_penalty or 0))


def cpl_filter(expected_cpl_usd: float | None, target_usd: float, breakeven_usd: float) -> str | None:
    """'ok' | 'thin' | 'expensive' | None if unknown."""
    if expected_cpl_usd is None:
        return None
    if expected_cpl_usd <= target_usd:
        return "ok"
    if expected_cpl_usd <= breakeven_usd:
        return "thin"
    return "expensive"


def decision(product_score: int, cpl_flag: str | None, config: ScoringConfig | None = None) -> str:
    """'test' | 'watch' | 'reject'"""
    config = config or ScoringConfig()
    if cpl_flag == "expensive":
        return "reject"
    if product_score >= config.test_threshold:
        return "test"
    if product_score >= config.watch_threshold:
        return "watch"
    return "reject"


def ad_proof_from_library(active_ads: int, long_running_ads: int) -> int:
    """Rough 0..5 suggestion for the 'ad_proof' block from Ad Library counts.

    long_running_ads = ads delivering for more than 30 days (a profitability signal).
    """
    if active_ads <= 0:
        return 0
    s = 1
    if active_ads >= 20:
        s += 1
    if active_ads >= 100:
        s += 1
    if long_running_ads >= 3:
        s += 1
    if long_running_ads >= 10:
        s += 1
    return min(s, 5)
