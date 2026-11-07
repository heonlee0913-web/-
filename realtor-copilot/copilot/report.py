"""중개사용 '안심 진단 & 맞춤형 매물 추천 리포트' HTML 생성 (단일 파일, 외부 의존성 없음)."""
from __future__ import annotations

from html import escape
from typing import Optional

from .engine import LABELS, PropertyReport
from .insurance import fmt_won
from .weights import KEYS

_STATUS_CLASS = {"SAFE": "safe", "CAUTION": "caution", "DANGER": "danger"}

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1b1f24;--muted:#5b6470;--line:#e3e6ea;--accent:#2f5bea;
--safe:#1a7f4b;--safe-bg:#e6f4ec;--caution:#9a6200;--caution-bg:#fdf3dc;--danger:#c0362c;--danger-bg:#fbe7e5;
--bar:#2f5bea;--bar-bg:#e8ecf5;--jeonse:#2f5bea;--sale:#8a94a6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#111418;--card:#1a1e24;--fg:#e8eaed;
--muted:#9aa3ae;--line:#2b3138;--accent:#7c9cff;--safe:#5fd39a;--safe-bg:#16301f;--caution:#f0c060;
--caution-bg:#33290f;--danger:#ff8a80;--danger-bg:#3a1a18;--bar:#7c9cff;--bar-bg:#262c36;--jeonse:#7c9cff;--sale:#7d8796}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:0}h3{font-size:14px;margin:16px 0 6px;color:var(--muted)}
.sub{color:var(--muted);margin:0 0 20px}
.weights{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:18px}
.head{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.rank{font-weight:700;color:var(--accent);margin-right:6px}
.meta{color:var(--muted);font-size:13px;margin-top:2px}
.score{text-align:right}.score b{font-size:34px;line-height:1}.score span{color:var(--muted);font-size:13px}
.badge{display:inline-block;border-radius:8px;padding:3px 10px;font-weight:600;font-size:13px;margin-top:6px}
.safe{color:var(--safe);background:var(--safe-bg)}.caution{color:var(--caution);background:var(--caution-bg)}
.danger{color:var(--danger);background:var(--danger-bg)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media(max-width:720px){.grid{grid-template-columns:1fr}}
.row{display:grid;grid-template-columns:88px 1fr 44px;gap:8px;align-items:center;font-size:13px;margin:5px 0}
.track{height:8px;background:var(--bar-bg);border-radius:4px;overflow:hidden}
.fill{height:100%;background:var(--bar);border-radius:4px}.fill.lock{background:var(--danger)}
.num{text-align:right;font-variant-numeric:tabular-nums}
ul{margin:4px 0;padding-left:18px}li{margin:2px 0}
.note{color:var(--muted);font-size:12px}
.box{border-radius:10px;padding:12px 14px;font-size:14px}
.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:13px;margin-top:8px}
.kv dt{color:var(--muted)}.kv dd{margin:0;font-variant-numeric:tabular-nums}
svg text{fill:var(--muted);font-size:10px}
details summary{cursor:pointer;color:var(--muted);font-size:13px;margin-top:10px}
footer{color:var(--muted);font-size:12px;margin-top:28px}
"""


def _bar(label: str, val: float, locked: bool = False) -> str:
    return (f'<div class="row"><span>{escape(label)}</span><div class="track">'
            f'<div class="fill{" lock" if locked else ""}" style="width:{val:.0f}%"></div></div>'
            f'<span class="num">{val:.0f}</span></div>')


def _chart(trend: list, own: Optional[int]) -> str:
    pts = [(r["month"], r["jeonse"], r["sale"]) for r in trend]
    vals = [v for _, j, s in pts for v in (j, s) if v] + ([own] if own else [])
    if len(pts) < 2 or not vals:
        return '<p class="note">실거래 추이를 그릴 데이터가 부족합니다.</p>'
    w, h, pl, pr, pt, pb = 420, 170, 48, 10, 10, 22
    lo, hi = min(vals) * 0.95, max(vals) * 1.05
    n = len(pts)
    x = lambda i: pl + (w - pl - pr) * i / (n - 1)
    y = lambda v: pt + (h - pt - pb) * (1 - (v - lo) / (hi - lo))

    def line(idx: int, color: str) -> str:
        seg = [(x(i), y(p[idx])) for i, p in enumerate(pts) if p[idx]]
        if len(seg) < 2:
            return ""
        d = " ".join(f"{'M' if k == 0 else 'L'}{a:.1f},{b:.1f}" for k, (a, b) in enumerate(seg))
        dots = "".join(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.5" fill="var({color})"/>' for a, b in seg)
        return f'<path d="{d}" fill="none" stroke="var({color})" stroke-width="2"/>{dots}'

    ticks = "".join(
        f'<text x="{pl - 6}" y="{y(v) + 3:.1f}" text-anchor="end">{v / 1e8:.1f}억</text>'
        f'<line x1="{pl}" x2="{w - pr}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="var(--line)"/>'
        for v in (lo + (hi - lo) * k / 3 for k in range(4)))
    months = "".join(f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle">{m[2:].replace("-", ".")}</text>'
                     for i, (m, _, _) in enumerate(pts) if i % max(1, n // 6) == 0 or i == n - 1)
    own_line = (f'<line x1="{pl}" x2="{w - pr}" y1="{y(own):.1f}" y2="{y(own):.1f}" '
                f'stroke="var(--danger)" stroke-dasharray="4 3"/>'
                f'<text x="{w - pr}" y="{y(own) - 4:.1f}" text-anchor="end" style="fill:var(--danger)">이 매물</text>'
                if own else "")
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="최근 1년 실거래가 추이">'
            f'{ticks}{months}{line(2, "--sale")}{line(1, "--jeonse")}{own_line}</svg>'
            '<p class="note"><span style="color:var(--jeonse)">━</span> 전세 '
            '<span style="color:var(--sale)">━</span> 매매 (반경 300m·유사 평형, 면적 보정 월평균)</p>')


def _card(r: PropertyReport) -> str:
    p, ins, mkt, rv = r.property, r.insurance, r.market, r.reviews
    cls = _STATUS_CLASS[ins["status"]]
    price = fmt_won(p["price_deposit"]) + (f" / 월 {p['price_monthly'] // 10_000:,}만원" if p["price_monthly"] else "")
    bars = "".join(_bar(LABELS[k], r.breakdown[k], k == "safety" and r.safety_locked) for k in KEYS)
    notes = "".join(f"<li><b>{LABELS[k]}</b> — {escape(' / '.join(r.notes[k]))}</li>" for k in KEYS)
    hl = "".join(f"<li>{escape(h)}</li>" for h in r.highlights) or "<li>—</li>"
    warn = "".join(f"<li>{escape(wn)}</li>" for wn in r.warnings)
    pos = "".join(f"<li>{escape(s)}</li>" for s in rv["positives"]) or "<li>후기 없음</li>"
    neg = "".join(f"<li>{escape(s)}</li>" for s in rv["negatives"]) or "<li>후기 없음</li>"
    rec = (f"<dt>조율 제안 보증금</dt><dd>{fmt_won(ins['recommended_deposit'])}</dd>"
           if ins.get("recommended_deposit") else "")
    return f"""
<section class="card">
 <div class="head">
  <div><h2><span class="rank">#{r.rank}</span>{escape(p['address'])}</h2>
   <div class="meta">{escape(p['property_type'])} · {price} · 전용 {p.get('exclusive_area_m2') or '-'}㎡ · {p.get('built_year') or '-'}년식 · {escape(p.get('direction') or '-')}</div>
   <span class="badge {cls}">HUG {escape(ins['label'])}</span></div>
  <div class="score"><b>{r.total_score:.1f}</b><br><span>종합 점수 / 100</span></div>
 </div>
 <div class="grid">
  <div><h3>지표별 점수</h3>{bars}
   <h3>브리핑 포인트</h3><ul>{hl}</ul>
   {f'<h3>주의 사항</h3><ul>{warn}</ul>' if warn else ''}</div>
  <div><h3>전세보증보험 진단</h3>
   <div class="box {cls}">{escape(ins['message'])}</div>
   <dl class="kv"><dt>보증 한도 (공시가×126%)</dt><dd>{fmt_won(ins['insurance_limit'])}</dd>
    <dt>선순위 채권 + 보증금</dt><dd>{fmt_won(ins['total_claims'])}</dd>
    <dt>여유율</dt><dd>{ins['margin_ratio']:.1%}</dd>
    <dt>가입 가능 최대 보증금</dt><dd>{fmt_won(ins['max_insurable_deposit'])}</dd>{rec}</dl>
  </div>
 </div>
 <div class="grid">
  <div><h3>시세 분석 (CMA)</h3>{_chart(mkt['monthly_trend'], mkt['deposit_equivalent'])}</div>
  <div><h3>AI 가격 코멘트</h3><div class="box" style="background:var(--bar-bg)">{escape(mkt['comment'])}</div>
   <dl class="kv"><dt>적정 전세가</dt><dd>{fmt_won(mkt['fair_jeonse']) if mkt['fair_jeonse'] else '-'}</dd>
    <dt>3개월 평균 전세</dt><dd>{fmt_won(mkt['avg_jeonse_3m']) if mkt['avg_jeonse_3m'] else '-'}</dd>
    <dt>매매 시세(추정)</dt><dd>{fmt_won(mkt['market_sale_price']) if mkt['market_sale_price'] else '-'}</dd>
    <dt>비교 거래 수</dt><dd>{mkt['comparable_count']}건</dd></dl></div>
 </div>
 <h3>거주자 솔직 후기 요약 <span class="note">({escape(rv['engine'])}, 후기 {rv['review_count']}건)</span></h3>
 <div class="grid"><div><b style="color:var(--safe)">👍 긍정</b><ul>{pos}</ul></div>
  <div><b style="color:var(--danger)">👎 부정</b><ul>{neg}</ul></div></div>
 <details><summary>점수 산출 근거 보기</summary><ul class="note">{notes}</ul></details>
</section>"""


def render(reports: list[PropertyReport], customer_name: str, weights: dict,
           as_of: str, title: str = "안심 매물 추천 리포트") -> str:
    chips = "".join(f'<span class="chip">{LABELS[k]} {weights[k]:.0%}</span>' for k in KEYS)
    cards = "".join(_card(r) for r in reports)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>{_CSS}</style></head><body><main>
<h1>{escape(customer_name)} 고객님 맞춤 {escape(title)}</h1>
<p class="sub">기준일 {escape(as_of)} · 매물 {len(reports)}건 · 종합 점수 = Σ(지표 점수 × 고객 가중치)</p>
<div class="weights">{chips}</div>
{cards}
<footer>본 리포트는 공공데이터·실거래가·등기 정보를 기반으로 한 참고 자료입니다. 전세보증보험 최종 가입 여부는
HUG 심사 결과에 따르며, 계약 전 등기부등본 최신본을 반드시 재확인하세요.</footer>
</main></body></html>"""
