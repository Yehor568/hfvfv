"""Campaign naming conventions, e.g. 'id260_Max_rk1_блендер_16.09_50$' or 'aerogril_id20_07.07_Maks_BIT'."""
import re

_CODE = re.compile(r"(?<![a-zа-я0-9])id\s*(\d+)", re.IGNORECASE)
_CYR = re.compile(r"[а-яіїєґ]", re.IGNORECASE)
_NOISE = re.compile(r"^(max|maks|max\+|sasha|ivan|rk\d*|bit|test.*|\d[\d.$/ ]*|new|restart.*|vlasnyk)$", re.IGNORECASE)


def product_code(campaign_name: str) -> str | None:
    m = _CODE.search(campaign_name or "")
    return f"id{int(m.group(1))}" if m else None


def guess_product_name(campaign_name: str) -> str:
    """Best-effort human name; the user can rename products in the dashboard."""
    parts = [p.strip() for p in re.split(r"[_|│]", campaign_name or "") if p.strip()]
    parts = [p for p in parts if not _CODE.fullmatch(p) and not _NOISE.match(p)]
    for p in parts:
        if _CYR.search(p):
            return re.sub(r"\s*[–-]\s*копія$", "", p).strip()
    return parts[0] if parts else (campaign_name or "")
