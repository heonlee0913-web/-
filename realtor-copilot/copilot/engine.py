"""동적 스코어링 엔진 — 기능 1 + 기능 2 결합.

[고객 가중치] → [5대 지표 점수 + HUG 진단 + CMA + 후기 요약] → [종합점수·순위 리포트]

    Total_Score_i = T_i·W_T + S_i·W_S + I_i·W_I + E_i·W_E + V_i·W_V
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Optional

from . import insurance, market, scoring, weights as W
from .models import Property, PropertyContext, UserPreference
from .providers import POIProvider, RouteProvider, SafetyProvider, TransactionProvider
from .reviews import ReviewSummary, RuleBasedSummarizer, Summarizer

LABELS = {"traffic": "교통/출퇴근", "safety": "안심/안전", "infrastructure": "인프라/생활",
          "environment": "주거 환경", "value": "가성비/시세"}


@dataclass
class PropertyReport:
    property: dict
    total_score: float
    rank: int
    breakdown: dict                 # {"traffic": 82.1, ...}
    weighted: dict                  # 가중치 반영 기여 점수
    notes: dict                     # 지표별 산출 근거
    safety_locked: bool
    insurance: dict
    market: dict
    reviews: dict
    highlights: list = field(default_factory=list)   # 브리핑 포인트
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_total(breakdown: dict, w: dict) -> tuple[float, dict]:
    contrib = {k: round(breakdown[k] * w[k], 2) for k in W.KEYS}
    return round(sum(breakdown[k] * w[k] for k in W.KEYS), 1), contrib


class ScoringEngine:
    def __init__(self, routes: RouteProvider, safety: SafetyProvider, pois: POIProvider,
                 txs: TransactionProvider, summarizer: Optional[Summarizer] = None,
                 today: Optional[date] = None, defect_history: Optional[dict] = None):
        self.routes, self.safety, self.pois, self.txs = routes, safety, pois, txs
        self.summarizer = summarizer or RuleBasedSummarizer()
        self.today = today or date.today()
        self.defect_history = defect_history or {}

    def context(self, prop: Property, pref: UserPreference) -> PropertyContext:
        return PropertyContext(
            route=self.routes.route(prop, pref.work_address),
            safety=self.safety.facilities(prop),
            poi_counts=self.pois.counts(prop),
            transactions=self.txs.transactions(prop),
        )

    def evaluate(self, prop: Property, pref: UserPreference,
                 ctx: Optional[PropertyContext] = None) -> PropertyReport:
        W.validate(pref)
        ctx = ctx or self.context(prop, pref)
        w = W.weights_of(pref)

        ins = insurance.diagnose(prop)
        mkt = market.analyze(prop, ctx.transactions, self.today)

        t, t_notes = scoring.traffic_score(ctx.route)
        s, s_notes, locked = scoring.safety_score(prop, ctx.safety, ins, mkt.market_sale_price)
        i, i_notes = scoring.infrastructure_score(ctx.poi_counts)
        e, e_notes = scoring.environment_score(prop, self.today)
        v, v_notes = scoring.value_score(mkt)
        breakdown = {"traffic": t, "safety": s, "infrastructure": i, "environment": e, "value": v}
        total, contrib = compute_total(breakdown, w)

        rv: ReviewSummary = self.summarizer.summarize(
            prop.resident_reviews, self.defect_history.get(str(prop.property_id)))

        return PropertyReport(
            property=asdict(prop),
            total_score=total,
            rank=0,
            breakdown=breakdown,
            weighted=contrib,
            notes={"traffic": t_notes, "safety": s_notes, "infrastructure": i_notes,
                   "environment": e_notes, "value": v_notes},
            safety_locked=locked,
            insurance=ins.to_dict(),
            market=mkt.to_dict(),
            reviews=rv.to_dict(),
            highlights=_highlights(breakdown, w, ins, mkt),
            warnings=_warnings(prop, ins, locked),
        )

    def rank(self, props: list[Property], pref: UserPreference,
             exclude_uninsurable: bool = False) -> list[PropertyReport]:
        reports = [self.evaluate(p, pref) for p in props]
        if exclude_uninsurable:
            reports = [r for r in reports if r.insurance["status"] != insurance.DANGER]
        # 동점이면 HUG 안전 등급 → 안전 점수 순
        order = {insurance.SAFE: 0, insurance.CAUTION: 1, insurance.DANGER: 2}
        reports.sort(key=lambda r: (-r.total_score, order[r.insurance["status"]], -r.breakdown["safety"]))
        for n, r in enumerate(reports, 1):
            r.rank = n
        return reports


def _highlights(b: dict, w: dict, ins, mkt) -> list[str]:
    out = []
    # 고객이 중요하게 본 지표(가중치 상위 2개) 중 점수가 높은 것을 브리핑 포인트로
    for k in sorted(W.KEYS, key=lambda k: -w[k])[:2]:
        if b[k] >= 75:
            out.append(f"고객 우선순위 '{LABELS[k]}'(가중치 {w[k]:.0%}) 점수 {b[k]:.0f}점")
    if ins.status == insurance.SAFE:
        out.append(f"HUG 전세보증보험 가입 확실 (여유율 {ins.margin_ratio:.0%})")
    if mkt.premium_ratio is not None and mkt.premium_ratio < -0.02:
        out.append(f"적정 전세가 대비 {abs(mkt.premium_ratio):.0%} 저렴")
    return out


def _warnings(prop: Property, ins, locked: bool) -> list[str]:
    out = []
    if ins.status != insurance.SAFE:
        out.append(f"[{ins.label}] {ins.message}")
    if prop.illegal_building:
        out.append("위반건축물 표기 매물 — 전세대출·보증보험 거절 가능성이 높습니다.")
    if locked and ins.status == insurance.SAFE:
        out.append("시세 대비 부채비율이 80%를 넘어 안전 점수가 30점 이하로 제한되었습니다.")
    return out
