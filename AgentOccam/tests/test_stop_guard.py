"""Offline coverage and orchestration regressions; no LLM/browser installation."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("occam_stop_guard", ROOT / "AgentOccam/stop_guard.py",
                                             submodule_search_locations=[str(ROOT / "AgentOccam")])
guard_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = guard_module
spec.loader.exec_module(guard_module)
StopGuard = guard_module.StopGuard
policy_module = __import__("occam_stop_guard.stop_policy", fromlist=["resolve_stop_mode"])
URL = "http://localhost:7770/sales/order/history/"
OBJECTIVE = "How much did I spend on orders in January 2023?"


def page(number=1, total=37, size=10, ids=None):
    start = (number - 1) * size + 1
    end = min(number * size, total)
    ids = ids if ids is not None else range(start, end + 1)
    rows = "\n".join(
        f'\t\trow "| {i:09} | 1/2/23 | 10.00 | Complete | View Order |"' for i in ids
    )
    return ("RootWebArea 'My Orders'\n\ttable 'Orders'\n"
            + rows + f"\n\ttext 'Items {start} to {end} of {total} total'\n"
            + f'\tlist \'Page\'\n\t\ttext "You\'re currently reading page"\n\t\ttext \'{number}\'\n'
            + "\n".join(f"\t\tlink [{800+i}] 'Page {i}'" for i in range(1, (total+size-1)//size + 1) if i != number))


def sorted_observation(text, direction="descending"):
    return {"text": text, "order_history_sort": {
        "field": "date", "direction": direction, "source": "orders_table_aria_sort"}}


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_existence_accepts_one_matching_witness_without_all_pages(self):
        guard = StopGuard("Do I have any fulfilled orders?")
        guard.observe(URL, page(ids=[1]))  # Partial page still contains a valid witness.
        result = guard.check("stop [Yes, order 000000001 is Complete.]")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "matching_witness")
        self.assertEqual(result["witness_ids"], ["000000001"])
        self.assertFalse(result["coverage"][0]["complete"])
        self.assertFalse(guard.check("stop [Yes, order 000000999]")["allowed"])

    def test_yes_cannot_replace_observed_evidence(self):
        guard = StopGuard("Do I have any fulfilled orders?")
        self.assertFalse(guard.check("stop [Yes]")["allowed"])
        guard.observe(URL, page().replace("Complete", "Pending"))
        self.assertFalse(guard.check("stop [Yes]")["allowed"])

    def test_absence_still_requires_relevant_coverage(self):
        guard = StopGuard("Do I have any fulfilled orders?")
        guard.observe(URL, page().replace("Complete", "Pending"))
        self.assertFalse(guard.check("stop [No]")["allowed"])
        guard.observe(URL + "?limit=50", page(size=50).replace("Complete", "Pending"))
        self.assertTrue(guard.check("stop [No]")["allowed"])

    def test_all_conditions_must_match_the_same_order(self):
        guard = StopGuard("Do I have any fulfilled orders in January 2023?")
        observation = page(ids=[1, 2]).replace("1/2/23 | 10.00 | Complete", "2/2/23 | 10.00 | Complete", 1)
        observation = observation.replace("000000002 | 1/2/23 | 10.00 | Complete", "000000002 | 1/2/23 | 10.00 | Pending")
        guard.observe(URL, observation)
        self.assertFalse(guard.check("stop [Yes]")["allowed"])
        guard.observe(URL, page(ids=[3]))
        self.assertTrue(guard.check("stop [Yes]")["allowed"])

    def test_unparsed_qualifiers_never_become_wildcard_matches(self):
        for objective in [
            "Do I have any fulfilled orders containing food?",
            "Do I have any orders over $100?",
            "Find 3 orders in the past month",
            "Find 3 non-cancelled orders",
            "Find 3 fulfilled orders and tell me my total spending",
            "Do I have any orders in January 2023 or February 2023?",
        ]:
            with self.subTest(objective=objective):
                guard = StopGuard(objective)
                guard.observe(URL, page())
                self.assertFalse(guard.evidence_requirement.understood)
                self.assertFalse(guard.check("stop [Yes: 000000001, 000000002, 000000003]")["allowed"])

    def test_bounded_sample_needs_enough_distinct_matching_ids_in_answer(self):
        guard = StopGuard("Find 3 fulfilled orders in January 2023")
        guard.observe(URL, page(ids=[1, 2]))
        self.assertFalse(guard.check("stop [000000001, 000000002, 000000003]")["allowed"])
        guard.observe(URL, page(ids=[3]))
        for answer in ["Found three orders", "000000001, 000000001, 000000002", "000000001, 000000002, 000000999"]:
            self.assertFalse(guard.check(f"stop [{answer}]")["allowed"])
        result = guard.check("stop [000000001, 000000002, 000000003]")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "requested_matches_found")

    def test_shortfall_claim_cannot_stop_on_partial_coverage(self):
        guard = StopGuard("List three pending orders")
        guard.observe(URL, page(ids=[1, 2]).replace("Complete", "Pending"))
        self.assertFalse(guard.check("stop [Only two: 000000001, 000000002]")["allowed"])

    def test_sample_count_and_requirement_override(self):
        guard = StopGuard("Show me one completed order")
        guard.observe(URL, page())
        self.assertTrue(guard.check("stop [000000001]")["allowed"])
        forced = StopGuard("Show me one completed order", {"requirement": "aggregate"})
        forced.observe(URL, page())
        self.assertFalse(forced.check("stop [000000001]")["allowed"])

    def test_absolute_date_interval_and_invalid_dates(self):
        guard = StopGuard("Find 2 orders from 2023-01-01 to 2023-01-31")
        guard.observe(URL, page(ids=[1, 2]))
        self.assertTrue(guard.check("stop [000000001, 000000002]")["allowed"])
        for window in ["from 2023-02-31 to 2023-03-01", "from 2023-03-01 to 2023-01-01", "in January 0000"]:
            guard = StopGuard("Find 2 orders " + window)
            guard.observe(URL, page())
            self.assertFalse(guard.check("stop [000000001, 000000002]")["allowed"])

    def test_verified_date_boundary_closes_only_requested_scope(self):
        guard = StopGuard(OBJECTIVE)
        text = page(ids=range(1, 11)).replace("000000010 | 1/2/23", "000000010 | 12/31/22")
        guard.observe(URL, sorted_observation(text))
        result = guard.check("stop [$90]")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "requested_date_range_covered")
        self.assertEqual(result["boundary_order_id"], "000000010")
        self.assertFalse(result["coverage"][0]["complete"])

    def test_zero_is_allowed_after_verified_date_boundary(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(page().replace("1/2/23", "12/31/22")))
        self.assertEqual(guard.check("stop [$0]")["reason"], "requested_date_range_covered")

    def test_monotonic_dates_or_url_sort_do_not_prove_global_sort(self):
        text = page().replace("1/2/23", "12/31/22")
        for url, observation in [(URL, text), (URL + "?sort=date&dir=desc", text),
                                 (URL, {"text": text, "order_history_sort": {"field": "date", "direction": "descending"}})]:
            guard = StopGuard(OBJECTIVE)
            guard.observe(url, observation)
            self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_boundary_must_be_strict_and_prefix_contiguous(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(page().replace("1/2/23", "1/1/23")))
        self.assertFalse(guard.check("stop [$100]")["allowed"])
        guard.observe(URL + "?p=3", sorted_observation(page(3).replace("1/2/23", "12/31/22")))
        self.assertFalse(guard.check("stop [$100]")["allowed"])
        guard.observe(URL + "?p=2", sorted_observation(page(2).replace("1/2/23", "1/1/23")))
        self.assertTrue(guard.check("stop [$200]")["allowed"])

    def test_missing_sort_on_one_page_or_inconsistent_dates_disable_shortcut(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        guard.observe(URL + "?p=2", sorted_observation(page(2).replace("1/2/23", "12/31/22")))
        self.assertFalse(guard.check("stop [$100]")["allowed"])
        guard = StopGuard(OBJECTIVE)
        text = page().replace("000000001 | 1/2/23", "000000001 | 12/31/22")
        guard.observe(URL, sorted_observation(text))
        self.assertFalse(guard.check("stop [$90]")["allowed"])

    def test_ascending_boundary_and_latest_order(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, sorted_observation(page().replace("1/2/23", "2/1/23"), "ascending"))
        self.assertTrue(guard.check("stop [$0]")["allowed"])
        guard = StopGuard("What is the status of my latest order?")
        guard.observe(URL, page())
        self.assertFalse(guard.check("stop [Complete]")["allowed"])
        guard.observe(URL, sorted_observation(page()))
        self.assertEqual(guard.check("stop [Complete]")["reason"], "ordered_first_match")
        self.assertFalse(guard.check("stop [000000002]")["allowed"])

    def test_first_matching_order_must_satisfy_status_filter(self):
        guard = StopGuard("Get the order number of my latest pending order")
        text = page().replace("000000003 | 1/2/23 | 10.00 | Complete", "000000003 | 1/2/23 | 10.00 | Pending")
        guard.observe(URL, sorted_observation(text))
        result = guard.check("stop [000000003]")
        self.assertEqual(result["reason"], "ordered_first_match")
        self.assertFalse(guard.check("stop [000000001]")["allowed"])

    def test_new_evidence_clears_stale_feedback_but_same_observation_does_not(self):
        guard = StopGuard("Find 3 fulfilled orders")
        guard.observe(URL, page(ids=[1]))
        guard.check("stop [000000001]")
        self.assertIn("STOP REJECTED", guard.context())
        guard.observe(URL, page(ids=[1]))
        self.assertIn("STOP REJECTED", guard.context())
        guard.observe(URL, page(ids=[2]))
        self.assertNotIn("STOP REJECTED", guard.context())
        guard.check("stop [000000001]")
        guard.observe(URL, page())
        self.assertNotIn("STOP REJECTED", guard.context())
        self.assertIn("no further pages are required", guard.context())


class StopGuardTests(unittest.TestCase):
    def test_premature_zero_is_rejected(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        result = guard.check("stop [The total is $0.]")
        self.assertFalse(result["allowed"])
        self.assertIn("10/37", result["feedback"])
        self.assertIn("[2, 3, 4]", result["feedback"])
        self.assertEqual(result["request_type"], "aggregate")

    def test_positive_aggregate_still_needs_full_coverage(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        self.assertFalse(guard.check("stop [$100]")["allowed"])

    def test_every_page_allows_stop_and_preserves_rows(self):
        guard = StopGuard(OBJECTIVE)
        for number in [1, 3, 2, 4]:
            guard.observe(URL + f"?p={number}", page(number))
        self.assertTrue(guard.check("stop [$370]")["allowed"])
        self.assertEqual(guard.snapshot()[0]["observed_items"], 37)
        self.assertIn("000000001 | 1/2/23 | 10.00 | Complete", guard.context())
        self.assertIn("000000037", guard.context())

    def test_duplicate_page_and_changed_url_are_not_new_evidence(self):
        guard = StopGuard(OBJECTIVE)
        for number in range(1, 5):
            guard.observe(URL + f"?p={number}", page())
        self.assertEqual(guard.snapshot()[0]["observed_items"], 10)
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_last_page_does_not_prove_missing_middle_pages(self):
        guard = StopGuard(OBJECTIVE)
        for number in [1, 4]:
            guard.observe(URL + f"?p={number}", page(number))
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_show_all_can_complete_coverage(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        guard.observe(URL + "?limit=50", page(size=50))
        self.assertTrue(guard.check("stop [$370]")["allowed"])
        self.assertEqual(len(guard.scopes), 1)

    def test_size_change_does_not_confuse_page_numbers_with_coverage(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        guard.observe(URL + "?limit=20&p=2", page(2, size=20))
        self.assertEqual(guard.snapshot()[0]["observed_items"], 27)
        self.assertFalse(guard.check("stop [$270]")["allowed"])

    def test_truncated_observation_is_not_counted_as_a_whole_page(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(ids=[1]))
        self.assertEqual(guard.snapshot()[0]["observed_items"], 0)
        self.assertIn("truncated", guard.check("stop [$0]")["feedback"])

    def test_duplicate_rows_cannot_fill_a_page(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(ids=[1] * 10))
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_filtered_result_cannot_prove_unfiltered_total(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        guard.observe(URL + "?status=canceled", page(total=1))
        self.assertFalse(guard.check("stop [$0]")["allowed"])
        guard.observe(URL + "?status=", page(total=1))
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_sort_orders_are_separate_scopes(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=20))
        guard.observe(URL + "?p=2&dir=asc", page(2, total=20))
        self.assertEqual(len(guard.scopes), 2)
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_count_change_invalidates_old_coverage(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=20))
        guard.observe(URL + "?p=2", page(2, total=21))
        self.assertEqual(guard.snapshot()[0]["observed_items"], 10)
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_relocated_records_invalidate_old_positions(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=20))
        guard.observe(URL + "?p=2", page(2, total=20, ids=range(1, 11)))
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_recent_orders_and_sidebar_empty_text_are_not_global_evidence(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe("http://localhost:7770/customer/account/", page(total=1))
        guard.observe(URL, "heading 'My Orders'\ntext 'You have no items to compare.'")
        self.assertFalse(guard.check("stop [$0]")["allowed"])

    def test_explicit_empty_history_is_evidence(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, "RootWebArea 'My Orders'\ntext 'You have placed no orders.'")
        self.assertTrue(guard.check("stop [$0]")["allowed"])

    def test_single_page_item_count(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=3).replace("Items 1 to 3 of 3 total", "3 Items"))
        self.assertTrue(guard.check("stop [$30]")["allowed"])

    def test_unknown_count_fails_closed(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=3).replace("Items 1 to 3 of 3 total", ""))
        self.assertFalse(guard.check("stop [$30]")["allowed"])

    def test_request_types_and_negative_lookup(self):
        for objective, kind in [
            ("List all my orders", "enumeration"),
            ("Which order cost the most?", "comparison"),
            ("How many fulfilled orders do I have?", "aggregate"),
            ("Did I purchase any orders in January?", "lookup"),
        ]:
            with self.subTest(objective=objective):
                guard = StopGuard(objective)
                guard.observe(URL, page())
                result = guard.check("stop [No matching orders]")
                self.assertEqual(result["request_type"], kind)
                self.assertFalse(result["allowed"])

    def test_identity_lookup_requires_observed_target(self):
        guard = StopGuard("What is the status of order 000000001?")
        self.assertFalse(guard.check("stop [Complete]")["allowed"])
        guard.observe(URL, page())
        self.assertTrue(guard.check("stop [Complete]")["allowed"])
        self.assertFalse(guard.check("stop [No such order]")["allowed"])
        self.assertFalse(guard.check("stop [$0.]")["allowed"])
        self.assertFalse(guard.check("stop")["allowed"])

    def test_mixed_navigation_and_stop_rejected_even_with_full_coverage(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page(total=1))
        self.assertFalse(guard.check("click [900]\nstop [$10]")["allowed"])
        self.assertFalse(guard.check("note [checking]\nclick [900]\nstop [$10]")["allowed"])

    def test_note_cannot_create_evidence(self):
        guard = StopGuard(OBJECTIVE)
        self.assertFalse(guard.check("note [All pages checked]\nstop [$0]")["allowed"])

    def test_unbracketed_stop_cannot_bypass_guard(self):
        guard = StopGuard(OBJECTIVE)
        guard.observe(URL, page())
        for action in ["stop", "stop $0", "stop[]", "note [Done]\nstop", "click [802]\nstop $0"]:
            with self.subTest(action=action):
                self.assertFalse(guard.check(action)["allowed"])

    def test_other_sites_are_not_subject_to_magento_rules(self):
        guard = StopGuard(OBJECTIVE, sites=["shopping_admin"])
        self.assertEqual(guard.check("stop [$0]")["reason"], "unsupported_task")

    def test_disabled_unsupported_mutation_and_non_stop(self):
        self.assertTrue(StopGuard(OBJECTIVE, {"enabled": False}).check("stop [$0]")["allowed"])
        self.assertEqual(StopGuard("Find a red shirt").check("stop [Found]")["reason"], "unsupported_task")
        self.assertEqual(StopGuard("Cancel order 000000001").check("stop [Done]")["reason"], "unsupported_task")
        self.assertIsNone(StopGuard(OBJECTIVE).check("click [123]"))

    def test_config_override_and_serialization(self):
        guard = StopGuard("What is the status of order 000000001?", {"requirement": "aggregate"})
        guard.observe(URL, {"text": page()})
        result = guard.check("stop [Complete]")
        self.assertFalse(result["allowed"])
        json.dumps(result)
        with self.assertRaises(ValueError):
            StopGuard(OBJECTIVE, {"requirement": "invented"})


def load_agent_module():
    """Stub optional LLM/DOM imports, while executing the real orchestration code."""
    import ast
    path = ROOT / "AgentOccam/AgentOccam.py"
    stubs = {"AgentOccam.stop_guard": guard_module, "AgentOccam.stop_policy": policy_module}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module.startswith("AgentOccam.") and node.module not in stubs:
            module = types.ModuleType(node.module)
            for name in node.names:
                setattr(module, name.name, Mock())
            stubs[node.module] = module
    spec = importlib.util.spec_from_file_location("occam_agent_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class SortMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Execute the real environment module, stubbing optional browser packages.
        import ast
        path = ROOT / "AgentOccam/env.py"
        stubs = {"AgentOccam.stop_policy": policy_module}
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (isinstance(node, ast.ImportFrom) and node.module not in stubs
                    and node.module.startswith(("browser_env", "evaluation_harness", "AgentOccam."))):
                module = types.ModuleType(node.module)
                for name in node.names:
                    setattr(module, name.name, Mock())
                stubs[node.module] = module
        spec = importlib.util.spec_from_file_location("occam_env_under_test", path)
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(cls.module)

    def test_only_unambiguous_date_header_is_trusted(self):
        page_mock = Mock(url=URL)
        for headers in [[], [{"name": "price", "direction": "ascending"}],
                        [{"name": "date", "direction": "none"}],
                        [{"name": "date", "direction": "ascending"}] * 2]:
            page_mock.evaluate.return_value = headers
            self.assertIsNone(self.module.read_order_history_sort(page_mock))
        page_mock.evaluate.return_value = [{"name": "date", "direction": "descending"}]
        self.assertEqual(self.module.read_order_history_sort(page_mock),
                         sorted_observation("")["order_history_sort"])

    def test_wrong_page_or_evaluation_failure_is_not_sort_evidence(self):
        page_mock = Mock(url="http://localhost:7770/customer/account/")
        self.assertIsNone(self.module.read_order_history_sort(page_mock))
        page_mock.evaluate.assert_not_called()
        page_mock.url = URL
        page_mock.evaluate.side_effect = RuntimeError("page navigated")
        self.assertIsNone(self.module.read_order_history_sort(page_mock))

    def test_wrapper_observation_includes_browser_metadata(self):
        wrapper = self.module.WebArenaEnvironmentWrapper.__new__(self.module.WebArenaEnvironmentWrapper)
        wrapper.webarena_env = Mock()
        wrapper.webarena_env.page.url = URL
        wrapper.webarena_env.page.evaluate.return_value = [{"name": "date", "direction": "descending"}]
        wrapper.global_config = types.SimpleNamespace(env=types.SimpleNamespace(prune=True))
        wrapper.obs = {"text": ("", Mock()), "image": None}
        wrapper.objective = OBJECTIVE
        self.module.translate_node_to_str.return_value = page()
        observation = wrapper.observation()
        self.assertEqual(observation["order_history_sort"], sorted_observation("")["order_history_sort"])


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_agent_module()

    def run_agent(self, actions, observations, budget=10, objective=OBJECTIVE, mode=None, guard_config=None):
        config = types.SimpleNamespace(others=types.SimpleNamespace(logging=True, max_steps=20))
        if guard_config is not None:
            config.stop_guard = guard_config
        elif mode is not None:
            config.stop_guard = types.SimpleNamespace(mode=mode)
        agent = self.module.AgentOccam(config=config)
        actor = Mock()
        actor.get_step.return_value = 1
        actor.equal_history_length.return_value = True
        actor.finalize_action.side_effect = lambda item: item
        actor.predict_action.side_effect = [[{"action": action}] for action in actions]
        critic, judge = Mock(), Mock()
        critic.get_criticism_elements.return_value = {}
        judge.judge.side_effect = lambda items: (items[0], {})
        agent.init_actor = lambda: setattr(agent, "actor", actor)
        agent.init_critic = lambda: setattr(agent, "critic", critic)
        agent.init_judge = lambda: setattr(agent, "judge", judge)

        class Environment:
            def __init__(self):
                self.index = 0
                self.max_steps = budget
                self.actions = []
                self.finished = False

            def get_sites(self):
                return ["shopping"]

            def observation(self):
                return observations[self.index]

            def get_url(self):
                return URL + f"?p={self.index + 1}"

            def done(self):
                return self.finished

            def status(self):
                return {"done": self.finished, "num_actions": len(self.actions), "reward": 0.0, "success": 0.0}

            def step(self, action):
                self.actions.append(action)
                if action.startswith("click"):
                    self.index += 1
                self.finished = action.startswith("stop") or len(self.actions) > budget
                return self.status()

        env = Environment()
        status = agent.act(objective, env)
        return agent, actor, env, status

    def test_actor_budget_tracks_actual_environment_budget(self):
        agent, _, _, _ = self.run_agent(["stop [$0]"], [page()], budget=15, mode="baseline")
        self.assertEqual(agent.config.others.max_steps, 15)

    def test_sufficient_positive_witness_stops_without_extra_navigation(self):
        agent, actor, env, status = self.run_agent(
            ["stop [Yes, 000000001 is Complete]"], [page()],
            objective="Do I have any fulfilled orders?",
        )
        self.assertEqual(len(env.actions), 1)
        self.assertTrue(status["done"])
        self.assertEqual(agent.trajectory[0]["stop_guard"]["reason"], "matching_witness")

    def test_date_sort_evidence_is_logged_and_replayable(self):
        agent, _, _, _ = self.run_agent(
            ["stop [$0]"], [sorted_observation(page().replace("1/2/23", "12/31/22"))],
        )
        self.assertEqual(agent.trajectory[0]["order_history_sort"], sorted_observation("")["order_history_sort"])
        spec = importlib.util.spec_from_file_location("audit_under_test", ROOT / "scripts/audit_stop_guard.py")
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.json"
            path.write_text(json.dumps({"trajectory": agent.trajectory}), encoding="utf-8")
            replayed = audit.audit(path, audit.load_guard())
        self.assertEqual(replayed[0]["reason"], "requested_date_range_covered")

    def test_rejection_continues_then_accepts_after_new_observation(self):
        agent, actor, env, status = self.run_agent(
            ["stop [$0]", "click [802]", "stop [$200]"],
            [page(total=20), page(2, total=20)],
        )
        self.assertEqual(env.actions, ["", "click [802]", "stop [$200]"])
        self.assertEqual(actor.finalize_action.call_count, 2)
        self.assertEqual(agent.trajectory[0]["proposed_action"], "stop [$0]")
        self.assertEqual(agent.trajectory[0]["action"], "")
        self.assertFalse(agent.trajectory[0]["stop_guard"]["allowed"])
        self.assertTrue(agent.trajectory[-1]["stop_guard"]["allowed"])
        self.assertTrue(status["done"])
        self.assertEqual(actor.update_history.call_args_list[0].kwargs["action"], "")

    def test_repeated_refusals_end_as_budget_failure_not_guessed_answer(self):
        agent, actor, env, status = self.run_agent(
            ["stop [$0]"] * 3, [page()], budget=2,
        )
        self.assertEqual(env.actions, ["", "", ""])
        actor.finalize_action.assert_not_called()
        self.assertIn("STOP REJECTED", actor.stop_guard_context)
        self.assertEqual(status["termination_reason"], "insufficient_evidence_budget_exhausted")
        self.assertEqual(status["success"], 0.0)

    def test_actor_receives_feedback_even_without_critic_input(self):
        actor = self.module.Actor.__new__(self.module.Actor)
        actor.prompt_template = {"input_template": "{input}"}
        actor.config = types.SimpleNamespace(input=["objective"], current_observation=types.SimpleNamespace(type=["text"]))
        actor.objective = OBJECTIVE
        actor.get_step = lambda: 1
        actor.get_previous_plans = lambda **kwargs: ""
        actor.get_interaction_history = lambda: ""
        actor.get_observation_text = lambda: ""
        actor.get_observation_image = lambda: None
        actor.stop_guard_context = "STOP REJECTED: inspect pages 2, 3, 4."
        text = "".join(item[1] for item in actor.get_online_input({}))
        self.assertIn(actor.stop_guard_context, text)


if __name__ == "__main__":
    unittest.main()
