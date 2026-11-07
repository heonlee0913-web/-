"""4.2 실시간 시세 및 금융 데이터 매칭 (CMA, 적정가 제안) + 가성비 점수 입력값.

- 비교 매물 분석(CMA): 반경 300m, 유사 평형(전용면적 ±15%), 최근 1년 실거래
- 가성비 기준가: 최근 3개월 동일 평형 평균 전세 실거래가 (없으면 1년치로 확장)
- 월세 매물은 전월세 전환율로 보증금 환산 후 비교
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from statistics import median
from typing import Optional

from .insurance import fmt_won
from .models import Property, Transaction

CMA_RADIUS_M = 300
AREA_TOLERANCE = 0.15
CONVERSION_RATE = 0.05   # 전월세 전환율 (기준금리 + 2%p 가정, 설정 가능)


@dataclass
class MarketAnalysis:
    comparable_count: int
    deposit_equivalent: int              # 월세 환산 보증금
    avg_jeonse_3m: Optional[int]         # 3개월 평균 전세 (면적 보정)
    fair_jeonse: Optional[int]           # AI 적정 전세가
    premium_ratio: Optional[float]       # (호가 - 적정가) / 적정가  (+면 비쌈)
    market_sale_price: Optional[int]     # 매매 시세 추정
    jeonse_to_sale: Optional[float]      # 전세가율 (보증금 / 매매시세)
    monthly_trend: list = field(default_factory=list)   # [{"month","jeonse","sale","count"}]
    comment: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def deposit_equivalent(prop: Property, rate: float = CONVERSION_RATE) -> int:
    return int(prop.price_deposit + prop.price_monthly * 12 / rate)


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def comparables(prop: Property, txs: list[Transaction], today: date,
                days: int = 365) -> list[Transaction]:
    area = prop.exclusive_area_m2
    out = []
    for t in txs:
        if t.distance_m > CMA_RADIUS_M:
            continue
        if (today - _parse(t.deal_date)).days > days:
            continue
        if area and abs(t.area_m2 - area) / area > AREA_TOLERANCE:
            continue
        out.append(t)
    return out


def _per_m2_median(txs: list[Transaction]) -> Optional[float]:
    return median(t.price / t.area_m2 for t in txs) if txs else None


def _area_adjusted(txs: list[Transaction], area: Optional[float], agg="mean") -> Optional[int]:
    if not txs:
        return None
    if area:
        vals = [t.price / t.area_m2 * area for t in txs]
    else:
        vals = [t.price for t in txs]
    return int(median(vals) if agg == "median" else sum(vals) / len(vals))


def monthly_trend(txs: list[Transaction], area: Optional[float]) -> list[dict]:
    buckets: dict[str, dict[str, list]] = {}
    for t in txs:
        m = t.deal_date[:7]
        b = buckets.setdefault(m, {"전세": [], "매매": []})
        if t.deal_type in b:
            b[t.deal_type].append(t)
    rows = []
    for m in sorted(buckets):
        b = buckets[m]
        rows.append({
            "month": m,
            "jeonse": _area_adjusted(b["전세"], area),
            "sale": _area_adjusted(b["매매"], area),
            "count": len(b["전세"]) + len(b["매매"]),
        })
    return rows


def analyze(prop: Property, txs: list[Transaction], today: Optional[date] = None) -> MarketAnalysis:
    today = today or date.today()
    comps = comparables(prop, txs, today)
    jeonse_1y = [t for t in comps if t.deal_type == "전세"]
    jeonse_3m = [t for t in jeonse_1y if (today - _parse(t.deal_date)).days <= 92]
    sales_1y = [t for t in comps if t.deal_type == "매매"]
    area = prop.exclusive_area_m2
    equiv = deposit_equivalent(prop)

    avg_3m = _area_adjusted(jeonse_3m, area, "mean")
    # 적정가: 3개월 거래가 3건 이상이면 3개월 중위값, 아니면 1년 중위값 (이상치에 강건)
    base = jeonse_3m if len(jeonse_3m) >= 3 else jeonse_1y
    fair = _area_adjusted(base, area, "median")
    if fair:
        fair = int(round(fair, -6))  # 100만원 단위

    sale_price = prop.market_price or _area_adjusted(
        [t for t in sales_1y if (today - _parse(t.deal_date)).days <= 183] or sales_1y,
        area, "median")

    premium = (equiv - fair) / fair if fair else None
    # 전세가율은 '위험도' 지표이므로 월세 환산액이 아닌 실제 보증금 기준
    jeonse_to_sale = prop.price_deposit / sale_price if sale_price else None

    return MarketAnalysis(
        comparable_count=len(comps),
        deposit_equivalent=equiv,
        avg_jeonse_3m=avg_3m,
        fair_jeonse=fair,
        premium_ratio=round(premium, 4) if premium is not None else None,
        market_sale_price=sale_price,
        jeonse_to_sale=round(jeonse_to_sale, 4) if jeonse_to_sale is not None else None,
        monthly_trend=monthly_trend(comps, area),
        comment=negotiation_comment(fair, premium, equiv, prop.price_monthly > 0),
    )


def negotiation_comment(fair: Optional[int], premium: Optional[float],
                        equiv: int, is_monthly: bool) -> str:
    if not fair or premium is None:
        return "반경 300m 내 유사 평형 실거래가 부족해 적정가를 산출하지 못했습니다. 인근 단지로 범위를 넓혀 확인하세요."
    basis = "월세 환산 보증금" if is_monthly else "현재 호가"
    if premium > 0.02:
        return (f"이 매물의 적정 전세가는 {fmt_won(fair)}이나, 현재 임대인은 {premium:.0%} 높게 내놓았습니다 "
                f"({basis} {fmt_won(equiv)}). 중개사님은 가격 네고 시 최근 실거래 데이터를 근거로 "
                f"{fmt_won(fair)} 선을 제시해 보세요.")
    if premium < -0.02:
        return (f"이 매물의 적정 전세가는 {fmt_won(fair)}이며, 현재 {basis}는 {abs(premium):.0%} 저렴합니다. "
                f"시세 대비 가성비가 뛰어나다는 점을 브리핑 포인트로 활용하세요. "
                f"(단, 시세보다 지나치게 싼 매물은 권리관계를 한 번 더 확인하세요.)")
    return (f"이 매물의 적정 전세가는 {fmt_won(fair)}이며, 현재 {basis}는 시세 수준(±2%)입니다. "
            f"가격보다는 안전성·입지 강점으로 설득하세요.")
