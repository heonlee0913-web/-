"""4.3 거주자 솔직 후기 3줄 요약 (긍정/부정).

두 가지 엔진을 제공한다.
- RuleBasedSummarizer : 외부 의존성 없는 키워드 사전 기반 요약 (기본값·폴백)
- ClaudeSummarizer    : Claude API 로 리뷰 원문 + 하자/층간소음 접수 이력을 요약.
                        `pip install anthropic` + ANTHROPIC_API_KEY 필요. 실패 시 규칙 기반으로 폴백.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import Optional, Protocol


@dataclass
class ReviewSummary:
    positives: list = field(default_factory=list)   # 최대 3줄
    negatives: list = field(default_factory=list)   # 최대 3줄
    engine: str = "rule"
    review_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class Summarizer(Protocol):
    def summarize(self, reviews: str, defect_history: Optional[list] = None) -> ReviewSummary: ...


def split_reviews(text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|(?<=[.!?。])\s+|\s*\|\s*", text or "")
    return [p.strip(" -•·") for p in parts if len(p.strip(" -•·")) >= 4]


# (측면, 감지 키워드, 극성, 템플릿)
_LEXICON = [
    ("소음",   ["조용", "소음이 적", "소음 없"], +1, "단지 내 소음이 적고 조용하다"),
    ("수압",   ["수압 좋", "수압이 좋", "수압 강", "수압이 강", "수압 쎄"], +1, "수압이 강하다"),
    ("채광",   ["채광", "햇빛", "해가 잘", "볕이 잘"], +1, "채광이 좋다"),
    ("관리",   ["관리 잘", "관리가 잘", "관리사무소 친절", "깨끗"], +1, "단지 관리 상태가 좋다"),
    ("교통",   ["역세권", "역까지 가깝", "버스 많", "교통 편"], +1, "대중교통 접근성이 좋다"),
    ("주차",   ["주차 여유", "주차 편", "주차 넉넉"], +1, "주차가 여유롭다"),
    ("치안",   ["치안 좋", "밤에도 안전", "밝아서"], +1, "밤길이 밝고 치안이 좋다"),
    ("편의",   ["편의시설", "마트 가깝", "병원 가깝", "슬세권"], +1, "생활 편의시설이 가깝다"),
    ("층간소음", ["층간소음", "윗집 소음", "발망치"], -1, "층간소음 민원이 있다"),
    ("외풍",   ["외풍", "웃풍", "샷시 오래", "단열"], -1, "겨울철 외풍이 있어 난방비가 더 나올 수 있다"),
    ("결로곰팡이", ["결로", "곰팡이"], -1, "결로·곰팡이가 생긴다"),
    ("주차부족", ["주차 어렵", "주차 전쟁", "주차가 어렵", "이중주차", "주차 힘"], -1, "주차가 어렵다"),
    ("벌레",   ["벌레", "바퀴"], -1, "벌레가 나온다"),
    ("수압약", ["수압 약", "수압이 약"], -1, "수압이 약하다"),
    ("도로소음", ["차 소리", "도로 소음", "대로변", "오토바이"], -1, "도로 소음이 있다"),
    ("관리비", ["관리비 비싸", "관리비가 비싸", "관리비 많이"], -1, "관리비가 높은 편이다"),
    ("누수",   ["누수", "물이 샌"], -1, "누수 이력이 있다"),
]


_NEGATORS = ("없어", "없고", "없습", "없음", "없는", "않", "안 나", "안 들", "못 느")


def _negated(sentence: str, kw: str) -> bool:
    """키워드 뒤에 부정 표현이 오면 True (예: '외풍은 거의 없어요')."""
    tail = sentence[sentence.find(kw) + len(kw):]
    return any(n in tail for n in _NEGATORS)


def _quote(t: str) -> str:
    """'…좋다' → '…좋다는', '…편이다' → '…편이라는'."""
    return t[:-2] + "이라는" if t.endswith("이다") else t + "는"


class RuleBasedSummarizer:
    def summarize(self, reviews: str, defect_history: Optional[list] = None) -> ReviewSummary:
        sents = split_reviews(reviews)
        hits: dict[str, list] = {}
        for s in sents:
            for aspect, kws, pol, tmpl in _LEXICON:
                kw = next((k for k in kws if k in s), None)
                if kw is None or (pol < 0 and _negated(s, kw)):
                    continue
                h = hits.setdefault(aspect, [pol, tmpl, 0, s])
                h[2] += 1

        def top(pol: int) -> list:
            rows = sorted((v for v in hits.values() if v[0] == pol), key=lambda v: -v[2])
            return rows[:3]

        pos = top(+1)
        neg = top(-1)
        positives = []
        if pos:
            # '조용하다' + '수압이 강하다' → '조용하고 수압이 강하다는'
            head = [v[1].removesuffix("다") + "고" for v in pos[:1]] if len(pos) > 1 else []
            last = pos[1][1] if len(pos) > 1 else pos[0][1]
            positives.append(f"이전 주거자들은 주로 {' '.join(head + [_quote(last)])} "
                             f"점을 높게 평가했습니다.")
            for v in pos[2:]:
                positives.append(f"{_quote(v[1])} 의견도 {v[2]}건 있었습니다.")
        negatives = [f"{_quote(v[1])} 의견이 {v[2]}건 있었습니다. (예: \"{v[3][:40]}\")" for v in neg]

        for d in (defect_history or [])[: max(0, 3 - len(negatives))]:
            negatives.append(f"국토부 하자/층간소음 접수 이력: {d}")
        if not positives and sents:
            positives.append("특별히 두드러진 긍정 평가는 확인되지 않았습니다.")
        if not negatives and sents:
            negatives.append("특별히 반복적으로 언급된 불만 사항은 없습니다.")
        return ReviewSummary(positives[:3], negatives[:3], "rule", len(sents))


_SYSTEM = (
    "당신은 공인중개사가 고객에게 보여줄 매물 리포트의 '거주자 후기' 섹션을 작성합니다. "
    "주어진 후기 원문과 하자 접수 이력에 실제로 있는 내용만 근거로 삼고, 수치는 원문에 있을 때만 쓰세요. "
    "긍정·부정 각각 최대 3개의 한국어 문장으로 요약합니다. 긍정은 '이전 주거자들은 …' 형식, "
    "부정은 고객이 대비할 수 있도록 구체적인 영향(예: 난방비, 생활 불편)을 담아 씁니다. "
    "원문이 부족하면 문장 수를 줄이세요."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "positives": {"type": "array", "items": {"type": "string"}},
        "negatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["positives", "negatives"],
    "additionalProperties": False,
}


class ClaudeSummarizer:
    """Claude API 기반 3줄 요약. 오류·거절 시 규칙 기반 요약으로 폴백한다."""

    def __init__(self, model: str = "claude-opus-5-5", client=None, fallback: Optional[Summarizer] = None):
        self.model = model
        self._client = client
        self.fallback = fallback or RuleBasedSummarizer()

    def _get_client(self):
        if self._client is None:
            import anthropic  # 선택 의존성
            self._client = anthropic.Anthropic()
        return self._client

    def summarize(self, reviews: str, defect_history: Optional[list] = None) -> ReviewSummary:
        sents = split_reviews(reviews)
        if not sents:
            return ReviewSummary(engine="claude", review_count=0)
        payload = "<reviews>\n" + "\n".join(f"- {s}" for s in sents) + "\n</reviews>"
        if defect_history:
            payload += "\n<defect_history>\n" + "\n".join(f"- {d}" for d in defect_history) + "\n</defect_history>"
        try:
            client = self._get_client()
            resp = client.beta.messages.create(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": payload}],
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": _SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if resp.stop_reason in ("refusal", "max_tokens"):
                raise RuntimeError(f"stop_reason={resp.stop_reason}")
            text = next(b.text for b in resp.content if b.type == "text")
            data = json.loads(text)
            return ReviewSummary(data["positives"][:3], data["negatives"][:3], "claude", len(sents))
        except Exception as e:  # noqa: BLE001 — 리포트 생성은 요약 실패로 중단되면 안 됨
            s = self.fallback.summarize(reviews, defect_history)
            s.engine = f"rule (claude 실패: {type(e).__name__})"
            return s
