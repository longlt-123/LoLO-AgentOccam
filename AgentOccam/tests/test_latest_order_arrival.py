"""Latest-order status/delivery regressions using observed rows, not eval answers."""

import json
from pathlib import Path
import unittest

import yaml

from test_stop_guard import StopGuard, URL, page, sorted_observation


OBJECTIVE = "Tell me the status of my latest order and when will it arrive"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/order_history_task47.json").read_text(encoding="utf-8"))
DETAIL_URL = "http://localhost:7770/sales/order/view/order_id/1/"
RECENT_FIXTURE = json.loads((Path(__file__).parent / "fixtures/recent_orders_task96.json").read_text(encoding="utf-8"))
CONFIG = yaml.safe_load((Path(__file__).resolve().parents[1] / "AgentOccam/configs/AgentOccam_shopping_qwen_evidence_gated.yml")
                        .read_text(encoding="utf-8"))["agent"]["stop_guard"]


def detail(order_id="000000001", status="Pending"):
    return (f"RootWebArea 'Order {order_id}'\n\tmain\n"
            f"\t\theading 'Order {order_id}'\n\t\ttext '{status}'\n"
            "\t\ttable 'Items Ordered'\n\t\ttext 'Order Information'\n"
            "\t\ttext 'Shipping Method'\n\t\ttext 'Flat Rate - Fixed'")


class LatestOrderArrivalTests(unittest.TestCase):
    def test_real_recent_orders_allows_exact_reported_stop_without_history(self):
        guard = StopGuard(OBJECTIVE, CONFIG)
        guard.observe(RECENT_FIXTURE["url"], RECENT_FIXTURE["observation"])
        # Preserve the dashboard witness after navigation to View Order.
        guard.observe(DETAIL_URL.replace("/1/", "/170/"), detail("000000170", "Canceled"))
        result = guard.check(RECENT_FIXTURE["proposed_action"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "recent_order_first_match")
        self.assertEqual(result["witness_ids"], ["000000170"])
        self.assertFalse(result["coverage"][0]["complete"])
        self.assertIsNone(result["coverage"][0]["total_items"])
        self.assertIn("magento_recent_source", result["coverage"][0]["sort_sources"][0])
        row = next(iter(guard.scopes.values())).rows["000000170"]
        self.assertEqual(row, ("000000170", "5/17/23", "365.42", "Canceled"))
        self.assertFalse(guard.check('stop [The latest order 000000189 is Pending; no arrival date.]')["allowed"])

    def test_recent_requires_separate_source_contract_and_exact_scope(self):
        for config, url in [({}, RECENT_FIXTURE["url"]),
                            ({"order_history_sort": CONFIG["order_history_sort"]}, RECENT_FIXTURE["url"]),
                            (CONFIG, RECENT_FIXTURE["url"] + "?filter=pending"),
                            (CONFIG, RECENT_FIXTURE["url"].replace("7770", "7771")),
                            (CONFIG, "http://localhost:7770/")]:
            with self.subTest(url=url, config=config):
                guard = StopGuard(OBJECTIVE, config)
                guard.observe(url, RECENT_FIXTURE["observation"])
                self.assertFalse(guard.check(RECENT_FIXTURE["proposed_action"])["allowed"])

    def test_recent_never_proves_totals_absence_or_earliest(self):
        for objective in ["How many orders do I have?", "List all orders", "Do I have any fulfilled orders?",
                          OBJECTIVE.replace("latest", "earliest"), FIXTURE["objective"]]:
            with self.subTest(objective=objective):
                guard = StopGuard(objective, CONFIG)
                guard.observe(RECENT_FIXTURE["url"], RECENT_FIXTURE["observation"])
                self.assertFalse(guard.check("stop [0 orders, $0.00 total spent]")["allowed"])
                self.assertEqual(guard.snapshot(), [])

    def test_recent_malformed_truncated_or_reordered_rows_are_not_trusted(self):
        text = RECENT_FIXTURE["observation"]
        for observation in [
            "\n".join(line for line in text.splitlines() if "000000170" not in line),
            text.replace("000000189", "000000170"),
            text.replace("5/17/23", "1/1/23"),
            text.replace("Ship To", "Unexpected Column"),
            text.replace("Canceled", "Unknown status"),
        ]:
            with self.subTest(observation=observation):
                guard = StopGuard(OBJECTIVE, CONFIG)
                guard.observe(RECENT_FIXTURE["url"], observation)
                self.assertFalse(guard.check(RECENT_FIXTURE["proposed_action"])["allowed"])

    def test_revisited_dashboard_invalidates_stale_prefix(self):
        guard = StopGuard(OBJECTIVE, CONFIG)
        guard.observe(RECENT_FIXTURE["url"], RECENT_FIXTURE["observation"])
        self.assertTrue(guard.check(RECENT_FIXTURE["proposed_action"])["allowed"])
        guard.observe(RECENT_FIXTURE["url"], "RootWebArea 'My Account'")
        self.assertFalse(guard.check(RECENT_FIXTURE["proposed_action"])["allowed"])

    def test_recent_pending_requires_details_for_same_order(self):
        guard = StopGuard(OBJECTIVE, CONFIG)
        guard.observe(RECENT_FIXTURE["url"], RECENT_FIXTURE["observation"].replace("Canceled", "Pending"))
        action = "stop [Order 000000170 is Pending; no arrival date is displayed.]"
        self.assertFalse(guard.check(action)["allowed"])
        guard.observe(DETAIL_URL.replace("/1/", "/170/"), detail("000000170"))
        self.assertTrue(guard.check(action)["allowed"])

    def test_invalid_recent_contract_fails_configuration(self):
        for field, value in [("source", "magento_history_source"), ("direction", "ascending"),
                             ("origin", "http://localhost:7770/customer/account/"), ("reference", "")]:
            contract = dict(CONFIG["recent_orders_sort"], **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                StopGuard(OBJECTIVE, {"recent_orders_sort": contract})

    def test_parser_retains_both_outputs_and_order_direction(self):
        for qualifier, direction in [("latest", "descending"), ("most recent", "descending"),
                                     ("earliest", "ascending"), ("first", "ascending")]:
            with self.subTest(qualifier=qualifier):
                requirement = StopGuard(OBJECTIVE.replace("latest", qualifier)).evidence_requirement
                self.assertTrue(requirement.understood)
                self.assertEqual(requirement.kind, "comparison")
                self.assertEqual(requirement.direction, direction)
                self.assertEqual(requirement.outputs, ("status", "arrival"))

    def test_extra_constraints_are_not_silently_discarded(self):
        for objective in [OBJECTIVE + " and list all orders", OBJECTIVE.replace("order and", "order containing food and")]:
            self.assertFalse(StopGuard(objective).evidence_requirement.understood)

    def test_canceled_latest_can_stop_after_first_verified_history_page(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(FIXTURE["observation"]))
        for answer in ["Order 000000170 was canceled and will never arrive.",
                       "The last order was canceled. It will never arrive.",
                       'The latest order (000000170) is marked as "Canceled" with no arrival date.']:
            with self.subTest(answer=answer):
                result = guard.check(f"stop [{answer}]")
                self.assertTrue(result["allowed"])
                self.assertEqual(result["reason"], "ordered_first_match")
                self.assertEqual(result["witness_ids"], ["000000170"])
                self.assertEqual(result["arrival_evidence"], "canceled_order_status")
                self.assertFalse(result["coverage"][0]["complete"])

    def test_logged_pending_answer_does_not_identify_latest_order(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(FIXTURE["observation"]))
        answer = ('The latest order (ID 000000189) is marked as "Pending," but no arrival date is provided '
                  'on this page. Check tracking information or contact customer support for delivery details.')
        self.assertFalse(guard.check(f"stop [{answer}]")["allowed"])

    def test_recent_orders_or_detail_alone_do_not_establish_latest(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe("http://localhost:7770/customer/account/", FIXTURE["observation"].replace("'Orders'", "'Recent Orders'"))
        guard.observe(DETAIL_URL, detail(status="Canceled"))
        result = guard.check("stop [Order 000000001 was canceled and will never arrive.]")
        self.assertFalse(result["allowed"])
        self.assertIn("Open My Orders", result["feedback"])
        self.assertNotIn("not fully parsed", result["feedback"])

    def test_untrusted_sort_wrong_direction_and_missing_prefix_still_block(self):
        for observation in [page(), sorted_observation(page(), "ascending"), sorted_observation(page(2))]:
            guard = StopGuard(OBJECTIVE)
            guard.observe(URL, observation)
            self.assertFalse(guard.check("stop [Order 000000001 is Complete, no arrival date.]")["allowed"])

    def test_pending_needs_matching_detail_even_with_full_coverage(self):
        for total in (1, 37):
            with self.subTest(total=total):
                guard = StopGuard(OBJECTIVE)
                guard.observe(URL, sorted_observation(page(total=total).replace("Complete", "Pending")))
                action = "stop [Order 000000001 is Pending; no arrival date is displayed.]"
                self.assertFalse(guard.check(action)["allowed"])
                guard.observe(DETAIL_URL, detail())
                self.assertNotIn("STOP REJECTED", guard.context())
                result = guard.check(action)
                self.assertTrue(result["allowed"])
                self.assertEqual(result["arrival_evidence"], "observed_order_details")

    def test_detail_requires_matching_id_origin_status_and_observed_content(self):
        for url, observation in [
            (DETAIL_URL, ""), (DETAIL_URL, detail("000000002")),
            (DETAIL_URL.replace("localhost:7770", "another-site"), detail()),
            (DETAIL_URL, detail(status="Canceled")),
            (DETAIL_URL, detail().replace("Items Ordered", "truncated")),
        ]:
            with self.subTest(url=url, observation=observation):
                guard = StopGuard(OBJECTIVE)
                guard.observe(URL, sorted_observation(page().replace("Complete", "Pending")))
                guard.observe(url, observation)
                self.assertFalse(guard.check("stop [Order 000000001 is Pending; no arrival date.]")["allowed"])

    def test_complete_unsorted_history_proves_unique_latest(self):
        guard = StopGuard(OBJECTIVE)
        observation = page(total=2).replace("Complete", "Canceled").replace("000000002 | 1/2/23", "000000002 | 2/2/23")
        guard.observe(URL, observation)
        result = guard.check("stop [Order 000000002 was canceled and will never arrive.]")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "complete_history_first_match")
        self.assertFalse(guard.check("stop [Order 000000001 was canceled and will never arrive.]")["allowed"])

    def test_unverified_same_day_ties_do_not_choose_largest_id(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=2).replace("Complete", "Canceled"))
        self.assertFalse(guard.check("stop [Order 000000002 was canceled and will never arrive.]")["allowed"])

    def test_negative_answer_without_a_witness_remains_rejected(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(page()))
        self.assertFalse(guard.check("stop [No orders found.]")["allowed"])

    def test_empty_history_resolves_absence_without_delivery_details(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, "RootWebArea 'My Orders'\n\ttext 'You have placed no orders.'")
        self.assertTrue(guard.check("stop [No orders found.]")["allowed"])


if __name__ == "__main__":
    unittest.main()
