"""Regression for a correct step-2 stop rejected in the Shopping trajectory.

The fixture contains only the objective and observed history table, no evaluator
answer. Test the date predicate and its coverage proof independently of the LLM.
"""

import copy
from datetime import date
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

import test_stop_guard as support


requirements = __import__("occam_stop_guard.stop_requirements", fromlist=["parse_requirement"])
FIXTURE = json.loads((Path(__file__).parent / "fixtures/order_history_task47.json").read_text(encoding="utf-8"))
CONFIG = yaml.safe_load((support.ROOT / "AgentOccam/configs/AgentOccam_shopping_qwen_evidence_gated.yml")
                        .read_text(encoding="utf-8"))["agent"]["stop_guard"]


class RelativeDateTests(unittest.TestCase):
    def test_count_and_spending_share_the_explicit_relative_period(self):
        requirement = requirements.parse_requirement(FIXTURE["objective"])
        self.assertTrue(requirement.understood)
        self.assertEqual(requirement.kind, "aggregate")
        self.assertEqual(requirement.status, "complete")
        self.assertEqual(requirement.outputs, ("count", "total"))
        self.assertEqual(requirement.reference_date, date(2023, 6, 12))
        self.assertEqual((requirement.start, requirement.end), (date(2023, 5, 12), date(2023, 6, 12)))

    def test_anchored_day_week_month_and_year_windows(self):
        for phrase, expected in [
            ("3 days", date(2023, 6, 9)), ("two weeks", date(2023, 5, 29)),
            ("four month", date(2023, 2, 12)), ("six months", date(2022, 12, 12)),
            ("year", date(2022, 6, 12)),
        ]:
            with self.subTest(phrase=phrase):
                objective = FIXTURE["objective"].replace("past month", "past " + phrase)
                requirement = requirements.parse_requirement(objective)
                self.assertTrue(requirement.understood)
                self.assertEqual(requirement.start, expected)
                self.assertEqual(requirement.end, date(2023, 6, 12))

    def test_calendar_subtraction_clamps_month_end_and_leap_day(self):
        for anchor, period, expected in [
            (date(2024, 3, 31), "month", date(2024, 2, 29)),
            (date(2023, 3, 31), "month", date(2023, 2, 28)),
            (date(2024, 2, 29), "year", date(2023, 2, 28)),
        ]:
            with self.subTest(anchor=anchor, period=period):
                self.assertEqual(requirements.date_window("over the past " + period, anchor), (expected, anchor))

    def test_relative_dates_work_for_other_existing_request_kinds(self):
        for question, kind in [("Do I have any fulfilled orders in the past month?", "existence"),
                               ("Find 3 pending orders in the past month", "sample"),
                               ("List all orders during the past month", "enumeration")]:
            with self.subTest(question=question):
                requirement = requirements.parse_requirement("Today is 2023-06-12. " + question)
                self.assertTrue(requirement.understood)
                self.assertEqual(requirement.kind, kind)
                self.assertEqual(requirement.start, date(2023, 5, 12))

    def test_missing_or_invalid_anchor_and_extra_conditions_remain_unknown(self):
        for objective in [
            FIXTURE["objective"].split(". ", 1)[1],
            FIXTURE["objective"].replace("6/12/2023", "2/30/2023"),
            FIXTURE["objective"].replace("fulfilled orders", "fulfilled orders containing food"),
            FIXTURE["objective"].rstrip(".") + " and cancel my pending orders.",
            FIXTURE["objective"].replace("past month", "past 0 months"),
            FIXTURE["objective"].replace("past month", "past 999999999999999999999 days"),
            FIXTURE["objective"].replace("past month", "past 999999 months"),
        ]:
            with self.subTest(objective=objective):
                self.assertFalse(requirements.parse_requirement(objective).understood)

    def test_status_and_inclusive_dates_apply_to_the_same_row(self):
        requirement = requirements.parse_requirement(FIXTURE["objective"])
        for day in ("5/12/23", "6/12/23"):
            self.assertTrue(requirement.matches(("000000001", day, "10.00", "Complete")))
        for day, status in [("5/11/23", "Complete"), ("6/13/23", "Complete"), ("5/17/23", "Canceled")]:
            self.assertFalse(requirement.matches(("000000001", day, "10.00", status)))


class RelativeDateCoverageTests(unittest.TestCase):
    def guard_for(self, observation=None, config=None, url=None):
        guard = support.StopGuard(FIXTURE["objective"], CONFIG if config is None else config)
        guard.observe(url or FIXTURE["url"], FIXTURE["observation"] if observation is None else observation)
        return guard

    def test_recorded_step_2_can_stop_with_verified_installation_sort(self):
        guard = self.guard_for()
        decision = guard.check(FIXTURE["proposed_action"])
        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["reason"], "requested_date_range_covered")
        self.assertEqual(decision["date_range"], ["2023-05-12", "2023-06-12"])
        self.assertEqual(decision["matching_order_ids"], [])
        self.assertEqual(decision["prefix_items"], 10)
        self.assertFalse(decision["coverage"][0]["complete"])
        self.assertEqual(decision["coverage"][0]["total_items"], 37)
        self.assertIn(CONFIG["order_history_sort"]["reference"], decision["sort_sources"][0])
        self.assertIn("2023-05-12 to 2023-06-12", guard.context())
        self.assertIn("status=complete", guard.context())
        self.assertIn("magento_history_source", guard.context())
        json.dumps(decision)  # Proof and parsed dates must be safe for trajectory logging.

    def test_parsed_date_alone_is_not_proof_of_unread_page_order(self):
        guard = self.guard_for(config={})
        decision = guard.check(FIXTURE["proposed_action"])
        self.assertTrue(decision["requirement"]["understood"])
        self.assertFalse(decision["allowed"])
        self.assertIn("trusted sort evidence", decision["feedback"])
        self.assertIn("no trusted sorting evidence", guard.context())

    def test_browser_sort_still_works_without_configured_contract(self):
        guard = self.guard_for(config={}, observation=support.sorted_observation(FIXTURE["observation"]))
        self.assertTrue(guard.check(FIXTURE["proposed_action"])["allowed"])

    def test_contract_does_not_apply_to_other_sites_filters_or_sort_queries(self):
        for url in [support.URL.replace("7770", "7780"), support.URL + "?sort=date&dir=desc",
                    support.URL + "?status=complete", support.URL.replace("history", "view")]:
            with self.subTest(url=url):
                guard = self.guard_for(url=url)
                self.assertFalse(guard.check(FIXTURE["proposed_action"])["allowed"])
        self.assertTrue(self.guard_for(url=support.URL + "?p=1&limit=10")
                        .check(FIXTURE["proposed_action"])["allowed"])

    def test_explicit_browser_metadata_takes_precedence_over_source_default(self):
        # Dates descend in the fixture, contradicting a browser declaration of ascending.
        guard = self.guard_for(observation=support.sorted_observation(FIXTURE["observation"], "ascending"))
        self.assertFalse(guard.check(FIXTURE["proposed_action"])["allowed"])

    def test_cannot_stop_at_or_before_crossing_the_requested_start(self):
        for day in ("6/1/23", "5/12/23"):
            with self.subTest(day=day):
                guard = self.guard_for(observation=support.page().replace("1/2/23", day))
                self.assertFalse(guard.check("stop [10 fulfilled orders, $100 total spent]")["allowed"])

    def test_source_contract_does_not_bypass_missing_rows_gaps_or_unsorted_dates(self):
        for observation in [
            support.page(ids=[1, 2]),
            support.page(number=2),
            FIXTURE["observation"].replace("2/9/23", "6/1/23"),
        ]:
            with self.subTest(observation=observation[:60]):
                self.assertFalse(self.guard_for(observation=observation).check(FIXTURE["proposed_action"])["allowed"])

    def test_contract_needs_an_explicit_origin_and_source_reference(self):
        for key, value in [("origin", "http://localhost:7770/sales/order/history/"),
                           ("direction", "ascending"), ("reference", ""), ("source", "model_guess")]:
            config = copy.deepcopy(CONFIG)
            config["order_history_sort"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                support.StopGuard(FIXTURE["objective"], config)

    def test_baseline_and_prompt_only_ignore_contract(self):
        for mode in ("baseline", "prompt_only"):
            config = {**CONFIG, "mode": mode}
            guard = self.guard_for(config=config)
            self.assertEqual(guard.scopes, {})
            self.assertEqual(guard.context(), "")
            self.assertEqual(guard.check(FIXTURE["proposed_action"])["reason"], "disabled")

    def test_real_agent_path_executes_stop_instead_of_consuming_more_steps(self):
        runner = support.IntegrationTests()
        runner.module = support.load_agent_module()
        agent, _, env, status = runner.run_agent(
            [FIXTURE["proposed_action"]], [FIXTURE["observation"]],
            objective=FIXTURE["objective"], guard_config=CONFIG)
        self.assertEqual(env.actions, [FIXTURE["proposed_action"]])
        self.assertEqual(status["stop_guard_rejections"], 0)
        self.assertEqual(agent.trajectory[0]["stop_guard"]["reason"], "requested_date_range_covered")

    def test_audit_uses_recorded_contract_or_explicit_override(self):
        spec = importlib.util.spec_from_file_location("relative_date_audit", support.ROOT / "scripts/audit_stop_guard.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.json"
            data = {"trajectory": [FIXTURE]}
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertFalse(audit.audit(path, support.StopGuard)[0]["allowed"])
            self.assertTrue(audit.audit(path, support.StopGuard, CONFIG)[0]["allowed"])
            data["stop_guard_config"] = CONFIG
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(audit.audit(path, support.StopGuard)[0]["allowed"])


if __name__ == "__main__":
    unittest.main()
