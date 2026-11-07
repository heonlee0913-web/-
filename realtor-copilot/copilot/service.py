"""애플리케이션 서비스 계층 — CLI / HTTP 서버가 공통으로 사용."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from . import weights as W
from .engine import ScoringEngine
from .models import UserPreference
from .providers import MockDataStore
from .reviews import ClaudeSummarizer, RuleBasedSummarizer
from . import report

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_data.json"


def build_preference(customer_name: str, work_address: str,
                     weights: Optional[dict] = None, keywords: Optional[list] = None) -> UserPreference:
    pref = UserPreference(customer_name, work_address)
    if weights and keywords:
        raise ValueError("weights 와 keywords 중 하나만 지정하세요.")
    if keywords:
        W.apply(pref, W.from_keywords(keywords))
    elif weights:
        W.apply(pref, W.normalize(weights))
    W.validate(pref)
    return pref


class CopilotService:
    def __init__(self, data_path: Path = SAMPLE, use_claude: bool = False, today: Optional[date] = None):
        self.store = MockDataStore.from_file(data_path)
        as_of = self.store.data.get("as_of")
        self.today = today or (date.fromisoformat(as_of) if as_of else date.today())
        summarizer = ClaudeSummarizer() if use_claude else RuleBasedSummarizer()
        s = self.store
        self.engine = ScoringEngine(s, s, s, s, summarizer=summarizer, today=self.today,
                                    defect_history=s.data.get("defect_history"))

    def score(self, pref: UserPreference, property_ids: Optional[list] = None,
              exclude_uninsurable: bool = False):
        props = self.store.properties()
        if property_ids:
            wanted = set(property_ids)
            props = [p for p in props if p.property_id in wanted]
        return self.engine.rank(props, pref, exclude_uninsurable)

    def score_json(self, req: dict) -> dict:
        pref = build_preference(req["customer_name"], req["work_address"],
                                req.get("weights"), req.get("keywords"))
        reports = self.score(pref, req.get("property_ids"), bool(req.get("exclude_uninsurable")))
        return {"as_of": self.today.isoformat(), "customer_name": pref.customer_name,
                "weights": W.weights_of(pref), "results": [r.to_dict() for r in reports]}

    def html(self, pref: UserPreference, **kw) -> str:
        reports = self.score(pref, **kw)
        return report.render(reports, pref.customer_name, W.weights_of(pref), self.today.isoformat())
