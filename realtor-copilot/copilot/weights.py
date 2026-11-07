"""3.2 고객 우선순위 가중치 배분 시스템.

- 슬라이더 입력값(임의 스케일)을 받아 총합 1.0 으로 정규화
- '출퇴근이 중요해요' 같은 키워드 선택을 가중치로 변환
"""
from __future__ import annotations

from .models import UserPreference

KEYS = ("traffic", "safety", "infrastructure", "environment", "value")

# 키워드 -> 해당 지표에 추가로 얹을 중요도 포인트
KEYWORD_BOOSTS = {
    "출퇴근이 중요해요": {"traffic": 3},
    "안전이 최우선이에요": {"safety": 3},
    "전세사기가 걱정돼요": {"safety": 3},
    "생활 편의시설이 중요해요": {"infrastructure": 3},
    "조용하고 쾌적한 집이 좋아요": {"environment": 3},
    "신축/채광이 중요해요": {"environment": 2},
    "가성비가 1순위예요": {"value": 3},
    "예산이 빠듯해요": {"value": 2},
}


def normalize(raw: dict) -> dict:
    """임의 스케일의 중요도를 총합 1.0 가중치로 변환.

    합이 정확히 1.0 이 되도록 반올림 오차는 가장 큰 항목에 흡수시킨다.
    """
    vals = {k: float(raw.get(k, 0) or 0) for k in KEYS}
    if any(v < 0 for v in vals.values()):
        raise ValueError("가중치는 음수일 수 없습니다.")
    total = sum(vals.values())
    if total == 0:
        return {k: 0.2 for k in KEYS}
    w = {k: round(v / total, 2) for k, v in vals.items()}
    diff = round(1.0 - sum(w.values()), 2)
    if diff:
        top = max(w, key=w.get)
        w[top] = round(w[top] + diff, 2)
    return w


def from_keywords(keywords: list[str], base: float = 1.0) -> dict:
    """키워드 선택 방식 -> 정규화된 가중치. 모든 지표는 base 포인트를 기본으로 가진다."""
    raw = {k: base for k in KEYS}
    for kw in keywords:
        if kw not in KEYWORD_BOOSTS:
            raise ValueError(f"알 수 없는 키워드: {kw}")
        for k, pts in KEYWORD_BOOSTS[kw].items():
            raw[k] += pts
    return normalize(raw)


def weights_of(pref: UserPreference) -> dict:
    return {k: getattr(pref, f"weight_{k}") for k in KEYS}


def validate(pref: UserPreference) -> None:
    w = weights_of(pref)
    for k, v in w.items():
        if not 0 <= v <= 1:
            raise ValueError(f"weight_{k} 는 0~1 사이여야 합니다: {v}")
    if abs(sum(w.values()) - 1.0) > 1e-6:
        raise ValueError(f"가중치 총합은 1.0 이어야 합니다 (현재 {sum(w.values()):.4f})")


def apply(pref: UserPreference, weights: dict) -> UserPreference:
    for k in KEYS:
        setattr(pref, f"weight_{k}", weights[k])
    validate(pref)
    return pref
