"""3.1 / 3.3 5대 평가 지표 개별 점수 (각 0~100) + 패널티/가산점 보정 규칙.

모든 함수는 (score, notes) 를 반환한다. notes 는 리포트에 그대로 노출되는 산출 근거다.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .insurance import InsuranceDiagnosis, DANGER
from .market import MarketAnalysis
from .models import Property, SafetyFacilities, TransitRoute


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- 1. 교통
COMMUTE_FREE_MIN = 10        # 10분 이내는 감점 없음
COMMUTE_BASE_SLOPE = 0.6     # 10~45분 구간: 분당 -0.6 (45분 = 79점)
COMMUTE_LIMIT_MIN = 45       # PRD: 45분 초과 시 1분당 -2점 (추가)
TRANSFER_PENALTY_FROM = 2    # PRD: 환승 2회 이상 시 회당 -10점
WALK_FREE_M = 800            # 총 도보 800m 초과분 100m당 -1점


def traffic_score(route: TransitRoute) -> tuple[float, list[str]]:
    t = route.total_minutes
    notes = [f"편도 {t:.0f}분 · 환승 {route.transfers}회 · 도보 {route.walk_meters:.0f}m"]
    score = 100 - COMMUTE_BASE_SLOPE * max(0.0, min(t, COMMUTE_LIMIT_MIN) - COMMUTE_FREE_MIN)
    if t > COMMUTE_LIMIT_MIN:
        p = 2 * (t - COMMUTE_LIMIT_MIN)
        score -= p
        notes.append(f"45분 초과 {t - COMMUTE_LIMIT_MIN:.0f}분 → -{p:.0f}점")
    if route.transfers >= TRANSFER_PENALTY_FROM:
        p = 10 * route.transfers
        score -= p
        notes.append(f"환승 {route.transfers}회 → -{p}점")
    if route.walk_meters > WALK_FREE_M:
        p = (route.walk_meters - WALK_FREE_M) / 100
        score -= p
        notes.append(f"도보 {WALK_FREE_M}m 초과 → -{p:.1f}점")
    return round(clamp(score), 1), notes


# ---------------------------------------------------------------- 2. 안전
SAFETY_LOCK = 30.0           # PRD: Critical 조건 시 30점 이하로 락
DEBT_TO_MARKET_LOCK = 0.80   # (근저당 + 보증금) / 시세 > 80% → 락


def safety_score(prop: Property, fac: SafetyFacilities, ins: InsuranceDiagnosis,
                 market_price: Optional[int]) -> tuple[float, list[str], bool]:
    """반환: (score, notes, locked)"""
    notes: list[str] = []
    # (a) 금융 안전도 70% — 시세 대비 부채비율 (시세 없으면 공시가×1.4 를 시세로 간주)
    mp = market_price or int(prop.official_price * 1.4)
    debt_ratio = (prop.senior_bond + prop.price_deposit) / mp
    financial = clamp(100 - max(0.0, debt_ratio - 0.5) * 200)   # 50% 이하 100점, 100% → 0점
    notes.append(f"시세 대비 부채비율(근저당+보증금) {debt_ratio:.0%}")

    # (b) 생활 치안 30% — 반경 200m CCTV·가로등, 500m 치안센터
    facility = clamp(fac.cctv_count * 8 + fac.streetlight_count * 3
                     + (15 if fac.police_box_within_500m else 0))
    notes.append(f"반경 200m CCTV {fac.cctv_count}대 · 가로등 {fac.streetlight_count}개"
                 + (" · 500m 내 치안센터" if fac.police_box_within_500m else ""))

    score = financial * 0.7 + facility * 0.3
    if prop.illegal_building:
        score -= 30
        notes.append("건축물대장 위반건축물 → -30점 (전세대출·보증보험 거절 사유)")

    locked = False
    if debt_ratio > DEBT_TO_MARKET_LOCK:
        locked = True
        notes.append(f"부채비율 {debt_ratio:.0%} > 80% → 안전 점수 {SAFETY_LOCK:.0f}점 이하 락")
    if ins.status == DANGER:
        locked = True
        notes.append(f"HUG 보증보험 가입 불가 → 안전 점수 {SAFETY_LOCK:.0f}점 이하 락")
    if locked:
        score = min(score, SAFETY_LOCK)
    return round(clamp(score), 1), notes, locked


# ---------------------------------------------------------------- 3. 인프라
# 카테고리: (배점, 만점 기준 개수)  — 반경 500m(도보 7분)
INFRA_RULES = {
    "subway":      ("지하철역", 25, 1),
    "mart":        ("마트", 15, 2),
    "convenience": ("편의점", 15, 3),
    "hospital":    ("병원", 20, 3),
    "pharmacy":    ("약국", 10, 2),
    "cafe":        ("카페", 15, 5),
}


def infrastructure_score(poi_counts: dict) -> tuple[float, list[str]]:
    score = 0.0
    parts = []
    missing = []
    for key, (label, pts, sat) in INFRA_RULES.items():
        n = int(poi_counts.get(key, 0))
        score += pts * min(1.0, n / sat)
        parts.append(f"{label} {n}")
        if n == 0:
            missing.append(label)
    notes = ["반경 500m: " + " · ".join(parts)]
    if missing:
        notes.append("도보권 부재: " + ", ".join(missing))
    return round(clamp(score), 1), notes


# ---------------------------------------------------------------- 4. 주거 환경
DIRECTION_BONUS = {"남향": 10, "남동향": 5, "남서향": 5, "동향": 0, "서향": -3,
                   "북동향": -5, "북서향": -5, "북향": -10}


def environment_score(prop: Property, today: Optional[date] = None) -> tuple[float, list[str]]:
    today = today or date.today()
    notes = []
    if prop.built_year:
        age = today.year - prop.built_year
        base = max(30.0, 85 - 1.5 * max(0, age - 5))   # 5년 이하 85점, 이후 연 -1.5점
        notes.append(f"준공 {prop.built_year}년(연식 {age}년) 기본 {base:.0f}점")
    else:
        base = 60.0
        notes.append("건축연도 미상 → 기본 60점")
    score = base

    d = (prop.direction or "").strip()
    if d:
        bonus = DIRECTION_BONUS.get(d, 0)
        if bonus:
            score += bonus
            notes.append(f"{d} {'+' if bonus > 0 else ''}{bonus}점")

    if prop.parking_ratio is not None:
        if prop.parking_ratio >= 1.2:
            score += 5
            notes.append(f"세대당 주차 {prop.parking_ratio:.2f}대 ≥ 1.2 → +5점")
        elif prop.parking_ratio < 0.5:
            score -= 10
            notes.append(f"세대당 주차 {prop.parking_ratio:.2f}대 < 0.5 → -10점")

    if prop.near_main_road:
        score -= 10
        notes.append("대로변 인접(소음) → -10점")
    return round(clamp(score), 1), notes


# ---------------------------------------------------------------- 5. 가성비
def value_score(market: MarketAnalysis) -> tuple[float, list[str]]:
    notes = []
    if market.premium_ratio is None:
        score = 50.0
        notes.append("비교 실거래 부족 → 중립 50점")
    else:
        # 시세 수준 70점, 1% 저렴할 때마다 +2점(15% 이상 저렴 100점), 1% 비쌀 때마다 -2점
        score = 70 - market.premium_ratio * 200
        word = "저렴" if market.premium_ratio < 0 else "높음"
        notes.append(f"적정가 대비 {abs(market.premium_ratio):.1%} {word}")
    if market.jeonse_to_sale is not None:
        r = market.jeonse_to_sale
        notes.append(f"전세가율(매매시세 대비) {r:.0%}")
        if r > 0.9:
            score -= 30
            notes.append("전세가율 90% 초과 → -30점 (역전세·깡통 위험)")
        elif r > 0.8:
            score -= 15
            notes.append("전세가율 80% 초과 → -15점")
    return round(clamp(score), 1), notes
