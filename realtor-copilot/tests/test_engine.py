import unittest
from datetime import date
from types import SimpleNamespace

from copilot import insurance, market, scoring, weights as W
from copilot.engine import compute_total
from copilot.models import Property, SafetyFacilities, Transaction, TransitRoute, UserPreference
from copilot.reviews import ClaudeSummarizer, RuleBasedSummarizer
from copilot.service import CopilotService, build_preference

EOK = 100_000_000
TODAY = date(2026, 11, 7)


def prop(**kw):
    base = dict(property_id=1, address="테스트", property_type="아파트",
                price_deposit=3 * EOK, official_price=3 * EOK)
    base.update(kw)
    return Property(**base)


class WeightsTest(unittest.TestCase):
    def test_normalize_sums_to_one(self):
        for raw in ({"traffic": 1, "safety": 1, "infrastructure": 1, "environment": 1, "value": 1},
                    {"traffic": 3, "safety": 7, "value": 1},
                    {"traffic": 1, "safety": 1, "infrastructure": 1}):
            w = W.normalize(raw)
            self.assertAlmostEqual(sum(w.values()), 1.0, places=9)

    def test_keywords(self):
        w = W.from_keywords(["출퇴근이 중요해요"])
        self.assertEqual(max(w, key=w.get), "traffic")
        self.assertAlmostEqual(sum(w.values()), 1.0)
        with self.assertRaises(ValueError):
            W.from_keywords(["없는 키워드"])

    def test_validate_rejects_bad_sum(self):
        p = UserPreference("a", "b", weight_traffic=0.5)
        with self.assertRaises(ValueError):
            W.validate(p)

    def test_total_formula(self):
        b = {"traffic": 80, "safety": 60, "infrastructure": 100, "environment": 50, "value": 40}
        w = {"traffic": 0.4, "safety": 0.3, "infrastructure": 0.1, "environment": 0.1, "value": 0.1}
        total, _ = compute_total(b, w)
        self.assertEqual(total, round(80 * .4 + 60 * .3 + 100 * .1 + 50 * .1 + 40 * .1, 1))


class InsuranceTest(unittest.TestCase):
    def test_limit_is_126_percent(self):
        d = insurance.diagnose(prop(official_price=EOK, price_deposit=int(0.5 * EOK)))
        self.assertEqual(d.insurance_limit, int(1.26 * EOK))

    def test_safe(self):
        d = insurance.diagnose(prop(official_price=2 * EOK, price_deposit=2 * EOK))  # 여유율 20.6%
        self.assertEqual(d.status, insurance.SAFE)

    def test_caution_thin_margin(self):
        # 한도 2.52억, 채권합 2.4억 → 여유율 4.8%
        d = insurance.diagnose(prop(official_price=2 * EOK, price_deposit=int(2.4 * EOK)))
        self.assertEqual(d.status, insurance.CAUTION)
        self.assertLessEqual(d.recommended_deposit, int(2.52 * EOK * 0.9))

    def test_caution_negotiable(self):
        # 한도 2.52억, 보증금 2.7억 → 1,800만원(6.7%) 인하 시 가입 가능
        d = insurance.diagnose(prop(official_price=2 * EOK, price_deposit=int(2.7 * EOK)))
        self.assertEqual(d.status, insurance.CAUTION)
        self.assertEqual(d.required_cut, int(2.7 * EOK) - int(2.52 * EOK))
        self.assertLessEqual(d.max_insurable_deposit, int(2.52 * EOK))

    def test_danger_bond(self):
        d = insurance.diagnose(prop(official_price=EOK, price_deposit=EOK, senior_bond=int(1.3 * EOK)))
        self.assertEqual(d.status, insurance.DANGER)

    def test_danger_kkangtong(self):
        d = insurance.diagnose(prop(official_price=EOK, price_deposit=int(1.6 * EOK)))
        self.assertEqual(d.status, insurance.DANGER)
        self.assertIn("126%", d.message)

    def test_boundary_exactly_ten_percent(self):
        # 채권합 = 한도 × 0.9 → 여유율 정확히 10% → SAFE
        d = insurance.diagnose(prop(official_price=EOK * 10, price_deposit=int(EOK * 10 * 1.26 * 0.9)))
        self.assertEqual(d.status, insurance.SAFE)


class ScoringTest(unittest.TestCase):
    def test_traffic_penalties(self):
        s45, _ = scoring.traffic_score(TransitRoute(45, 1, 300))
        s50, _ = scoring.traffic_score(TransitRoute(50, 1, 300))
        self.assertAlmostEqual(s45 - s50, 10.0)                 # 45분 초과 1분당 -2점
        s_t1, _ = scoring.traffic_score(TransitRoute(30, 1, 300))
        s_t2, _ = scoring.traffic_score(TransitRoute(30, 2, 300))
        self.assertAlmostEqual(s_t1 - s_t2, 20.0)               # 환승 2회 → 회당 -10
        self.assertEqual(scoring.traffic_score(TransitRoute(200, 4, 3000))[0], 0)

    def test_safety_lock_80_percent(self):
        p = prop(price_deposit=int(8.5 * EOK), official_price=8 * EOK)
        ins = insurance.diagnose(p)
        s, notes, locked = scoring.safety_score(p, SafetyFacilities(20, 30, True), ins, 10 * EOK)
        self.assertTrue(locked)
        self.assertLessEqual(s, 30)

    def test_safety_lock_when_uninsurable(self):
        p = prop(official_price=EOK, price_deposit=int(1.6 * EOK))
        ins = insurance.diagnose(p)
        s, _, locked = scoring.safety_score(p, SafetyFacilities(20, 30, True), ins, 10 * EOK)
        self.assertTrue(locked)
        self.assertLessEqual(s, 30)

    def test_safety_no_lock(self):
        p = prop(price_deposit=3 * EOK, official_price=5 * EOK)
        ins = insurance.diagnose(p)
        s, _, locked = scoring.safety_score(p, SafetyFacilities(10, 15, True), ins, 10 * EOK)
        self.assertFalse(locked)
        self.assertGreater(s, 90)

    def test_environment_bonuses(self):
        base, _ = scoring.environment_score(prop(built_year=2020, direction="동향", parking_ratio=1.0), TODAY)
        bonus, _ = scoring.environment_score(prop(built_year=2020, direction="남향", parking_ratio=1.2), TODAY)
        self.assertEqual(bonus - base, 15)                      # 남향 +10, 주차 1.2대 +5

    def test_infrastructure_bounds(self):
        self.assertEqual(scoring.infrastructure_score({})[0], 0)
        full = {k: 99 for k in scoring.INFRA_RULES}
        self.assertEqual(scoring.infrastructure_score(full)[0], 100)


class MarketTest(unittest.TestCase):
    def setUp(self):
        self.p = prop(price_deposit=int(5.5 * EOK), exclusive_area_m2=84.0)
        self.txs = [Transaction(f"2026-{m:02d}-10", "전세", 5 * EOK, 84.0, 100) for m in (9, 10, 11)]
        self.txs += [Transaction("2026-10-01", "전세", 20 * EOK, 84.0, 900),      # 반경 밖
                     Transaction("2026-10-01", "전세", 20 * EOK, 160.0, 50),      # 평형 상이
                     Transaction("2024-10-01", "전세", 20 * EOK, 84.0, 50),       # 1년 초과
                     Transaction("2026-10-05", "매매", 10 * EOK, 84.0, 50)]

    def test_comparables_filter_and_fair_price(self):
        m = market.analyze(self.p, self.txs, TODAY)
        self.assertEqual(m.comparable_count, 4)
        self.assertEqual(m.fair_jeonse, 5 * EOK)
        self.assertAlmostEqual(m.premium_ratio, 0.1)
        self.assertIn("10% 높게", m.comment)
        self.assertAlmostEqual(m.jeonse_to_sale, 0.55)

    def test_monthly_rent_conversion(self):
        p = prop(price_deposit=EOK, price_monthly=500_000)
        self.assertEqual(market.deposit_equivalent(p, 0.05), EOK + 120_000_000)

    def test_value_score(self):
        cheap = market.MarketAnalysis(5, 0, None, 1, -0.15, None, None)
        pricey = market.MarketAnalysis(5, 0, None, 1, 0.10, None, 0.95)
        self.assertEqual(scoring.value_score(cheap)[0], 100)
        self.assertEqual(scoring.value_score(pricey)[0], 20)  # 70 - 20 - 30


class ReviewTest(unittest.TestCase):
    def test_rule_based(self):
        s = RuleBasedSummarizer().summarize(
            "단지가 조용해요. 수압이 강해요. 겨울에 외풍이 심해요. 외풍 때문에 난방비가 많이 나와요.")
        self.assertTrue(any("조용" in x for x in s.positives))
        self.assertTrue(any("외풍" in x and "2건" in x for x in s.negatives))
        self.assertLessEqual(len(s.positives), 3)
        self.assertLessEqual(len(s.negatives), 3)

    def test_negation(self):
        s = RuleBasedSummarizer().summarize("외풍은 거의 없어요. 채광이 좋아요.")
        self.assertFalse(any("외풍" in x for x in s.negatives))

    def test_claude_fallback_on_error(self):
        class Boom:
            class beta:
                class messages:
                    @staticmethod
                    def create(**kw):
                        raise RuntimeError("network")
        s = ClaudeSummarizer(client=Boom()).summarize("조용해요. 주차가 어렵습니다.")
        self.assertTrue(s.engine.startswith("rule"))
        self.assertTrue(s.negatives)

    def test_claude_parses_json(self):
        resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text='{"positives":["a","b","c","d"],"negatives":["x"]}')])
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: resp)))
        s = ClaudeSummarizer(client=client).summarize("조용해요.")
        self.assertEqual(s.engine, "claude")
        self.assertEqual(s.positives, ["a", "b", "c"])


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.svc = CopilotService()

    def test_ranking_on_sample(self):
        pref = build_preference("김민지", "서울 강남구 테헤란로 152 (강남역)",
                                keywords=["출퇴근이 중요해요", "전세사기가 걱정돼요"])
        reports = self.svc.score(pref)
        self.assertEqual([r.rank for r in reports], list(range(1, len(reports) + 1)))
        scores = [r.total_score for r in reports]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(reports[-1].insurance["status"], insurance.DANGER)
        for r in reports:
            self.assertTrue(0 <= r.total_score <= 100)

    def test_exclude_uninsurable(self):
        pref = build_preference("a", "default", weights={"value": 1})
        reports = self.svc.score(pref, exclude_uninsurable=True)
        self.assertTrue(all(r.insurance["status"] != insurance.DANGER for r in reports))

    def test_weights_change_ranking(self):
        a = self.svc.score(build_preference("a", "default", weights={"traffic": 1}))
        b = self.svc.score(build_preference("b", "default", weights={"environment": 1}))
        self.assertNotEqual([r.property["property_id"] for r in a], [r.property["property_id"] for r in b])

    def test_json_and_html(self):
        out = self.svc.score_json({"customer_name": "a", "work_address": "default", "keywords": ["가성비가 1순위예요"]})
        self.assertEqual(len(out["results"]), 5)
        html = self.svc.html(build_preference("a", "default"))
        self.assertIn("<svg", html)
        self.assertIn("전세보증보험", html)


if __name__ == "__main__":
    unittest.main()
