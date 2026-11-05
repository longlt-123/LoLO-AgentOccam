"""Regressions for missing CDP rectangle values and stale observations.

Uses installed browser libraries with fake CDP/page objects, without a live site.
"""

from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_stop_guard as support


class BrowserRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = types.ModuleType("browser_env")
        package.__path__ = [str(support.ROOT / "browser_env")]
        with patch.dict(sys.modules, {"browser_env": package}):
            cls.processors = importlib.import_module("browser_env.processors")
            cls.actions = importlib.import_module("browser_env.actions")
            cls.envs = importlib.import_module("browser_env.envs")
        support.SortMetadataTests.setUpClass()
        cls.wrapper_module = support.SortMetadataTests.module

    def test_missing_or_invalid_cdp_rectangle_has_no_fabricated_coordinates(self):
        for response in [None, {}, {"result": {}}, {"result": {"type": "undefined"}},
                         {"result": {"subtype": "error"}}, {"result": {"value": None}},
                         {"result": {"value": {"x": 1}}},
                         {"result": {"value": {"x": float("nan"), "y": 1, "width": 5, "height": 5}}}]:
            with self.subTest(response=response):
                self.assertIsNone(self.processors.bounding_rect_from_response(response))
        self.assertEqual(self.processors.bounding_rect_from_response(
            {"result": {"value": {"x": 10, "y": 20, "width": 30, "height": 40}}}), [10, 20, 30, 40])

    def processor(self):
        processor = self.processors.TextObervationProcessor("accessibility_tree", False, {"width": 1280, "height": 720})
        processor.obs_nodes_info = {"9757": {"backend_id": 123}}
        return processor

    def test_expired_coordinates_raise_useful_error_instead_of_keyerror(self):
        processor = self.processor()
        processor.get_bounding_client_rect = Mock(return_value={"result": {"type": "undefined"}})
        processor.fetch_browser_info = Mock(return_value={"config": {}})
        with self.assertRaisesRegex(ValueError, "9757.*refresh"):
            processor.element_is_visible(Mock(), "9757")
        with self.assertRaisesRegex(ValueError, "9757.*refresh"):
            processor.get_element_center("9757", Mock())

    def test_accessibility_tree_survives_missing_rectangle_value(self):
        processor = self.processor()
        processor.get_bounding_client_rect = Mock(return_value={"result": {"type": "undefined"}})
        client = Mock()
        client.send.return_value = {"nodes": [
            {"nodeId": "1", "role": {"value": "RootWebArea"}, "backendDOMNodeId": 1},
            {"nodeId": "2", "role": {"value": "link"}, "backendDOMNodeId": 2},
        ]}
        tree = processor.fetch_page_accessibility_tree({}, client, False)
        self.assertIsNone(tree[1]["union_bound"])
        self.assertIsNotNone(tree[0]["union_bound"])

    def test_pagination_click_uses_live_locator_despite_expired_cdp_node(self):
        processor = Mock()
        processor.get_node_info_by_element_id.return_value = types.SimpleNamespace(role="link", name="Page Next")
        processor.element_is_visible.side_effect = KeyError("value")
        page = Mock()
        action = self.actions.create_click_action(element_id="9757")
        result = self.actions.execute_action(action, page, Mock(), processor)
        self.assertIs(result, page)
        page.get_by_role.assert_called_once_with("link", name="Page Next", exact=True)
        page.get_by_role.return_value.click.assert_called_once()
        processor.element_is_visible.assert_not_called()
        processor.get_element_center.assert_not_called()

    def wrapper(self):
        wrapper = self.wrapper_module.WebArenaEnvironmentWrapper.__new__(self.wrapper_module.WebArenaEnvironmentWrapper)
        wrapper.steps, wrapper.max_steps = 0, 15
        wrapper.is_done, wrapper.reward, wrapper.terminated = False, 0.0, False
        wrapper.obs = {"text": "OLD PAGE"}
        wrapper.info = {}
        wrapper.trajectory = []
        wrapper.webarena_env = Mock()
        return wrapper

    def test_failed_action_refreshes_without_repeating_click_or_remaining_batch(self):
        wrapper = self.wrapper()
        wrapper.webarena_env.step.side_effect = KeyError("value")
        wrapper.webarena_env.refresh_observation.return_value = ({"text": "NEW PAGE"}, {"fail_error": "KeyError"})
        cmd = {"action_type": "click"}
        with patch.object(self.wrapper_module, "create_id_based_actions", return_value=[cmd, cmd]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = wrapper.step("click [9757]\nclick [11066]")
        wrapper.webarena_env.step.assert_called_once_with(cmd)
        wrapper.webarena_env.refresh_observation.assert_called_once_with(fail_error="KeyError: 'value'")
        self.assertEqual(wrapper.obs["text"], "NEW PAGE")
        self.assertIn("KeyError", status["last_action_error"])
        self.assertFalse(status["done"])
        self.assertEqual(wrapper.trajectory[-1]["observation"]["text"], "NEW PAGE")

    def test_failed_refresh_terminates_without_presenting_old_observation(self):
        wrapper = self.wrapper()
        wrapper.webarena_env.step.side_effect = KeyError("value")
        wrapper.webarena_env.refresh_observation.side_effect = RuntimeError("DOM unavailable")
        with patch.object(self.wrapper_module, "create_id_based_actions", return_value=[{"action_type": "click"}]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = wrapper.step("click [9757]")
        self.assertIsNone(wrapper.obs)
        self.assertTrue(status["done"])
        self.assertEqual(status["success"], 0.0)
        self.assertEqual(status["termination_reason"], "observation_refresh_failed")

    def stop_step(self, wrapper, action, evaluator):
        # Use the real action parser and STOP enum with the lightweight wrapper.
        wrapper.config_file = "test_task.json"
        with patch.object(self.wrapper_module, "ActionTypes", self.actions.ActionTypes), \
                patch.object(self.wrapper_module, "create_id_based_actions", self.actions.create_id_based_actions), \
                patch.object(self.wrapper_module, "evaluator_router", return_value=evaluator), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return wrapper.step(action)

    def test_accepted_stop_finishes_even_if_a_browser_refresh_would_timeout(self):
        wrapper = self.wrapper()
        observation = wrapper.obs
        wrapper.trajectory.append({"observation": wrapper.obs, "info": wrapper.info})
        wrapper.webarena_env.step.side_effect = TimeoutError("taking page screenshot")
        wrapper.webarena_env.refresh_observation.side_effect = TimeoutError("taking page screenshot")
        evaluator = Mock(return_value=1.0)

        status = self.stop_step(wrapper, "stop [0 fulfilled orders, $0.00 spent]", evaluator)

        self.assertTrue(status["done"])
        self.assertTrue(wrapper.done())  # AgentOccam.act must exit before another actor call.
        self.assertTrue(wrapper.terminated)
        self.assertEqual(status["num_actions"], 1)
        self.assertEqual(status["reward"], 1.0)
        self.assertNotIn("last_action_error", status)
        self.assertIs(wrapper.obs, observation)
        self.assertEqual(len(wrapper.trajectory), 2)
        self.assertEqual(wrapper.trajectory[-1]["action_type"], self.actions.ActionTypes.STOP)
        self.assertEqual(wrapper.trajectory[-1]["answer"], "0 fulfilled orders, $0.00 spent")
        wrapper.webarena_env.step.assert_not_called()
        wrapper.webarena_env.refresh_observation.assert_not_called()
        evaluator.assert_called_once_with(
            trajectory=wrapper.trajectory, config_file=wrapper.config_file,
            page=wrapper.webarena_env.page, client=wrapper.webarena_env.get_page_client.return_value)

    def test_stop_discards_commands_after_it_in_the_same_batch(self):
        wrapper = self.wrapper()
        evaluator = Mock(return_value=1.0)
        status = self.stop_step(wrapper, "stop [Done]\nclick [9757]", evaluator)
        self.assertTrue(status["done"])
        self.assertEqual(len(wrapper.trajectory), 1)
        wrapper.webarena_env.step.assert_not_called()
        evaluator.assert_called_once()

    def test_evaluator_failure_does_not_resume_actor_after_stop(self):
        wrapper = self.wrapper()
        evaluator = Mock(side_effect=RuntimeError("grading unavailable"))
        status = self.stop_step(wrapper, "stop [Done]", evaluator)
        self.assertTrue(status["done"])
        self.assertEqual(status["reward"], 0)
        self.assertEqual(wrapper.trajectory[-1]["action_type"], self.actions.ActionTypes.STOP)
        wrapper.webarena_env.step.assert_not_called()
        wrapper.webarena_env.refresh_observation.assert_not_called()
        evaluator.assert_called_once()

    def test_rejected_stop_empty_step_still_continues_without_browser_work(self):
        wrapper = self.wrapper()
        evaluator = Mock(return_value=1.0)
        status = self.stop_step(wrapper, "", evaluator)
        self.assertFalse(status["done"])
        self.assertEqual(status["num_actions"], 1)
        wrapper.webarena_env.step.assert_not_called()
        wrapper.webarena_env.refresh_observation.assert_not_called()
        evaluator.assert_not_called()

    def test_refresh_observation_has_no_task_action(self):
        env = self.envs.ScriptBrowserEnv.__new__(self.envs.ScriptBrowserEnv)
        env.page = Mock(url="http://example.test/orders?p=3")
        env.page.content.return_value = "new page"
        env.modify_page = Mock(return_value={})
        env._get_obs = Mock(return_value={"text": "PAGE THREE"})
        env._get_obs_metadata = Mock(return_value={})
        with patch.object(self.envs, "execute_action") as execute:
            observation, info = env.refresh_observation(fail_error="failed")
        execute.assert_not_called()
        self.assertEqual(observation["text"], "PAGE THREE")
        self.assertEqual(info["page"].url, "http://example.test/orders?p=3")
        self.assertEqual(info["fail_error"], "failed")


if __name__ == "__main__":
    unittest.main()
