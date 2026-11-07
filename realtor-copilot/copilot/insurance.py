"""4.1 전세보증보험(HUG) 가입 요건 자동 진단.

진단 공식 (PRD):
    공시가격 × 적용비율(140%) × 전세가율(90%) ≥ 선순위 채권 + 내 전세보증금
    → 공시가격의 126% 가 '보증 한도(insurance_limit)'.

분류:
    SAFE    [안전 - 가입 확실] : 한도 대비 여유율 ≥ 10%
    CAUTION [주의 - 조율 필요] : 여유율 0~10% 이거나, 보증금을 소폭(기본 ≤ 15%) 낮추면 가입 가능
    DANGER  [위험 - 가입 불가] : 선순위 채권만으로 한도 초과, 전세가율 126% 초과 등 깡통전세 위험

※ 실제 HUG 심사는 주택 유형별 시세 산정 방식(KB시세·감정평가 등), 다가구 선순위 보증금,
   임대인 보증사고 이력 등을 추가로 본다. 본 모듈은 PRD 기준 1차 스크리닝 용도다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from .models import Property

APPLY_RATIO = 1.40          # 공시가격 적용비율
JEONSE_RATIO = 0.90         # 담보인정비율(전세가율)
LIMIT_RATIO = APPLY_RATIO * JEONSE_RATIO   # 1.26
SAFE_MARGIN = 0.10          # 안전 판정 최소 여유율
MAX_NEGOTIABLE_CUT = 0.15   # '조율 필요'로 볼 수 있는 보증금 인하폭 상한 (보증금 대비)

SAFE, CAUTION, DANGER = "SAFE", "CAUTION", "DANGER"
LABELS = {
    SAFE: "안전 - 가입 확실",
    CAUTION: "주의 - 조율 필요",
    DANGER: "위험 - 가입 불가",
}


@dataclass
class InsuranceDiagnosis:
    status: str                          # SAFE / CAUTION / DANGER
    label: str
    insurance_limit: int                 # 공시가 × 1.26
    total_claims: int                    # 선순위 채권 + 보증금
    margin_ratio: float                  # (한도 - 채권합) / 한도
    jeonse_to_official: float            # 보증금 / 공시가격
    max_insurable_deposit: int           # 가입 가능한 최대 보증금 (0 이하면 불가)
    recommended_deposit: Optional[int]   # 여유율 10% 확보 보증금 (조율 제안가)
    required_cut: int                    # 가입을 위해 낮춰야 하는 최소 금액 (0이면 불필요)
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _round_down(won: float, unit: int = 1_000_000) -> int:
    """제안 금액은 100만원 단위로 내림 (보수적)."""
    return int(won // unit * unit)


def fmt_won(won: int) -> str:
    """1억 2,300만원 형식."""
    sign = "-" if won < 0 else ""
    won = abs(int(won))
    eok, rest = divmod(won, 100_000_000)
    man = rest // 10_000
    if eok and man:
        return f"{sign}{eok}억 {man:,}만원"
    if eok:
        return f"{sign}{eok}억원"
    return f"{sign}{man:,}만원"


def diagnose(prop: Property) -> InsuranceDiagnosis:
    if prop.official_price <= 0:
        raise ValueError("공시가격이 없으면 보증보험 진단을 할 수 없습니다.")

    limit = prop.official_price * LIMIT_RATIO
    claims = prop.senior_bond + prop.price_deposit
    margin = (limit - claims) / limit
    jeonse_ratio = prop.price_deposit / prop.official_price

    max_deposit = _round_down(limit - prop.senior_bond)
    safe_deposit = _round_down(limit * (1 - SAFE_MARGIN) - prop.senior_bond)
    required_cut = max(0, claims - int(limit))

    if margin >= SAFE_MARGIN:
        status = SAFE
        recommended = None
        msg = (f"보증 한도 {fmt_won(int(limit))} 대비 여유율 {margin:.1%}로 "
               f"전세보증보험 가입이 확실한 매물입니다.")
    elif prop.senior_bond >= limit or max_deposit <= 0:
        status = DANGER
        recommended = None
        msg = (f"선순위 채권 {fmt_won(prop.senior_bond)}만으로 보증 한도 "
               f"{fmt_won(int(limit))}를 초과합니다. 보증금을 낮춰도 가입이 불가능한 깡통전세 위험 매물입니다.")
    elif margin >= 0:
        status = CAUTION
        recommended = max(safe_deposit, 0) or None
        msg = (f"가입은 가능하나 여유율이 {margin:.1%}로 아슬아슬합니다. "
               f"시세·공시가 변동 시 가입이 거절될 수 있으니 보증금을 "
               f"{fmt_won(recommended)} 이하로 조율하면 안전권(여유율 10%)에 들어옵니다."
               if recommended else
               f"가입은 가능하나 여유율이 {margin:.1%}로 아슬아슬합니다.")
    elif required_cut <= prop.price_deposit * MAX_NEGOTIABLE_CUT:
        status = CAUTION
        recommended = max(safe_deposit, 0) or max_deposit
        msg = (f"현재 조건으로는 한도를 {fmt_won(required_cut)} 초과해 가입이 불가합니다. "
               f"보증금을 최소 {fmt_won(max_deposit)} 이하(권장 {fmt_won(recommended)})로 "
               f"낮추면 가입 가능합니다. 임대인과 가격 조율을 제안하세요.")
    else:
        status = DANGER
        recommended = None
        reason = ("보증금이 공시가의 126%를 넘는 깡통전세 구조로" if jeonse_ratio > LIMIT_RATIO
                  else "근저당 등 선순위 채권이 과다해")
        msg = (f"{reason} 보증 한도를 {fmt_won(required_cut)} 초과합니다. "
               f"가입 가능 최대 보증금은 {fmt_won(max_deposit)}으로 현재가 대비 인하폭이 너무 커 "
               f"계약을 권장하지 않습니다.")

    return InsuranceDiagnosis(
        status=status,
        label=LABELS[status],
        insurance_limit=int(limit),
        total_claims=claims,
        margin_ratio=round(margin, 4),
        jeonse_to_official=round(jeonse_ratio, 4),
        max_insurable_deposit=max(max_deposit, 0),
        recommended_deposit=recommended,
        required_cut=required_cut,
        message=msg,
    )
