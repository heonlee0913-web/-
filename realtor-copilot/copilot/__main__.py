"""CLI

  python -m copilot demo [--customer 0] [--out report.html] [--claude]
  python -m copilot score --name 홍길동 --work "서울 강남구 테헤란로 152 (강남역)" \
        --keywords 출퇴근이 중요해요 가성비가 1순위예요 [--json]
  python -m copilot serve [--port 8000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import weights as W
from .engine import LABELS
from .insurance import fmt_won
from .service import CopilotService, build_preference


def _print_table(reports) -> None:
    head = f"{'순위':<3} {'종합':>5}  " + " ".join(f"{LABELS[k][:2]:>4}" for k in W.KEYS) + "  HUG 진단        주소"
    print(head)
    print("-" * len(head) * 2)
    for r in reports:
        b = " ".join(f"{r.breakdown[k]:>5.0f}" for k in W.KEYS)
        lock = "*" if r.safety_locked else " "
        print(f"#{r.rank:<2} {r.total_score:>6.1f}  {b}{lock} {r.insurance['label']:<14} {r.property['address']}")
        print(f"      └ {r.market['comment']}")
    print("\n* 안전 점수 30점 락 적용")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="copilot", description="AI 매물 스코어링 & 안심 진단")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="샘플 데이터로 리포트 생성")
    d.add_argument("--customer", type=int, default=0)
    d.add_argument("--out", default="report.html")
    d.add_argument("--claude", action="store_true", help="후기 요약에 Claude API 사용")

    s = sub.add_parser("score", help="고객 조건으로 샘플 매물 채점")
    s.add_argument("--name", required=True)
    s.add_argument("--work", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--keywords", nargs="+", choices=list(W.KEYWORD_BOOSTS))
    g.add_argument("--weights", nargs=5, type=float, metavar=("T", "S", "I", "E", "V"),
                   help="교통 안전 인프라 환경 가성비 중요도 (자동 정규화)")
    s.add_argument("--exclude-uninsurable", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", help="HTML 리포트 저장 경로")
    s.add_argument("--claude", action="store_true")

    v = sub.add_parser("serve", help="HTTP API 서버 실행")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--claude", action="store_true")

    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from .server import serve
        serve(a.host, a.port, a.claude)
        return 0

    svc = CopilotService(use_claude=a.claude)
    if a.cmd == "demo":
        c = svc.store.preferences()[a.customer]
        pref = build_preference(c["customer_name"], c["work_address"], c.get("weights"), c.get("keywords"))
        excl = False
    else:
        weights = dict(zip(W.KEYS, a.weights)) if a.weights else None
        pref = build_preference(a.name, a.work, weights, a.keywords)
        excl = a.exclude_uninsurable
        if a.json:
            req = {"customer_name": a.name, "work_address": a.work, "weights": weights,
                   "keywords": a.keywords, "exclude_uninsurable": excl}
            json.dump(svc.score_json(req), sys.stdout, ensure_ascii=False, indent=2)
            print()
            return 0

    print(f"[{pref.customer_name}] 가중치: " + ", ".join(f"{LABELS[k]} {v:.0%}" for k, v in W.weights_of(pref).items()))
    reports = svc.score(pref, exclude_uninsurable=excl)
    _print_table(reports)
    out = getattr(a, "out", None)
    if out:
        from . import report
        Path(out).write_text(report.render(reports, pref.customer_name, W.weights_of(pref),
                                           svc.today.isoformat()), encoding="utf-8")
        print(f"\n리포트 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
