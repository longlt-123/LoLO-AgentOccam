"""Check ablation isolation, prompt parity, and matched experiment configs."""

import copy
import types
import unittest
from unittest.mock import patch

import yaml

import test_stop_guard as support


policy = support.policy_module


class StopVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent_module = support.load_agent_module()
        cls.runner = support.IntegrationTests()
        cls.runner.module = cls.agent_module

    def test_mode_resolution_and_legacy_flags(self):
        for mode in policy.STOP_MODES:
            self.assertEqual(policy.resolve_stop_mode({"mode": mode}), mode)
            self.assertEqual(policy.resolve_stop_mode(types.SimpleNamespace(mode=mode)), mode)
        self.assertEqual(policy.resolve_stop_mode({"enabled": False}), "baseline")
        self.assertEqual(policy.resolve_stop_mode({"enabled": True}), "evidence_gated")
        self.assertEqual(policy.resolve_stop_mode(), "evidence_gated")
        for config in [{"mode": "typo"}, {"enabled": "false"},
                       {"mode": "baseline", "enabled": True},
                       {"mode": "evidence_gated", "enabled": False}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                policy.resolve_stop_mode(config)

    def actor_instruction(self, mode, step):
        actor = self.agent_module.Actor.__new__(self.agent_module.Actor)
        actor.config = types.SimpleNamespace(planning_command=[], others=types.SimpleNamespace(max_steps=20))
        actor.prompt_template = {"instruction_template": {"without_planning": "Original instruction"}}
        actor.get_output_specifications = lambda: ""
        actor.get_planning_specifications = lambda: ""
        actor.get_navigation_specifications = lambda: ""
        actor.get_step = lambda: step
        actor.stop_mode = mode
        return actor.get_actor_instruction()

    def test_baseline_retains_original_prompt_including_last_step(self):
        self.assertEqual(self.actor_instruction("baseline", 0), "Original instruction")
        self.assertEqual(self.actor_instruction("baseline", 19),
                         "Original instruction\n\nWARNING: You have a 20-step budget, and this would be your FINAL STEP. "
                         "Wrap up your observations and return your answer with `stop [answer]` to maximize the reward.")

    def test_prompt_only_and_gated_have_identical_system_guidance(self):
        for step in (0, 10, 19):
            prompt = self.actor_instruction("prompt_only", step)
            self.assertEqual(prompt, self.actor_instruction("evidence_gated", step))
            self.assertIn(policy.EVIDENCE_GUIDANCE, prompt)
            self.assertEqual(prompt.count("EVIDENCE BEFORE STOP:"), 1)
            self.assertNotIn("maximize the reward", prompt)

    def test_baseline_and_prompt_only_never_construct_or_call_guard(self):
        for mode in ("baseline", "prompt_only"):
            with self.subTest(mode=mode), patch.object(self.agent_module, "StopGuard") as constructor:
                agent, actor, env, status = self.runner.run_agent(["stop [$0]"], [support.page()], mode=mode)
                constructor.assert_not_called()
                self.assertIsNone(agent.stop_guard)
                self.assertEqual(actor.stop_guard_context, "")
                self.assertEqual(actor.stop_mode, mode)
                self.assertEqual(env.actions, ["stop [$0]"])
                self.assertNotIn("stop_guard", agent.trajectory[0])
                self.assertEqual(agent.trajectory[0]["stop_mode"], mode)
                self.assertEqual(status["stop_mode"], mode)
                self.assertEqual(status["stop_guard_rejections"], 0)

    def test_gated_mode_blocks_same_unsupported_stop_and_injects_context(self):
        agent, actor, env, status = self.runner.run_agent(
            ["stop [$0]", "click [802]", "stop [$200]"],
            [support.page(total=20), support.page(2, total=20)], mode="evidence_gated",
        )
        self.assertEqual(env.actions, ["", "click [802]", "stop [$200]"])
        self.assertIn("STOP EVIDENCE CHECK", actor.stop_guard_context)
        self.assertEqual(status["stop_mode"], "evidence_gated")
        self.assertEqual(status["stop_guard_rejections"], 1)

    def test_guard_itself_respects_explicit_mode(self):
        for mode in ("baseline", "prompt_only"):
            guard = support.StopGuard(support.OBJECTIVE, {"mode": mode})
            guard.observe(support.URL, support.page())
            self.assertEqual(guard.scopes, {})
            self.assertEqual(guard.check("stop [$0]")["reason"], "disabled")

    def test_three_configs_only_differ_in_mode_and_output_names(self):
        root = support.ROOT / "AgentOccam/configs"
        reference = yaml.safe_load((root / "AgentOccam_shopping_qwen_baseline.yml").read_text(encoding="utf-8"))
        reference.pop("logname")
        reference["agent"]["others"].pop("logname")
        reference["agent"]["stop_guard"].pop("mode")
        lognames = set()
        for mode in policy.STOP_MODES:
            config = yaml.safe_load((root / f"AgentOccam_shopping_qwen_{mode}.yml").read_text(encoding="utf-8"))
            self.assertEqual(config["agent"]["stop_guard"]["mode"], mode)
            self.assertEqual(config["max_steps"], config["agent"]["others"]["max_steps"])
            self.assertEqual(config["logname"], config["agent"]["others"]["logname"])
            lognames.add(config["logname"])
            normalized = copy.deepcopy(config)
            normalized.pop("logname")
            normalized["agent"]["others"].pop("logname")
            normalized["agent"]["stop_guard"].pop("mode")
            self.assertEqual(normalized, reference)
        self.assertEqual(len(lognames), 3)


class EnvironmentVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        support.SortMetadataTests.setUpClass()
        cls.module = support.SortMetadataTests.module

    def test_no_extra_browser_sort_reads_in_baseline_or_prompt_only(self):
        from unittest.mock import Mock
        for mode in ("baseline", "prompt_only", "evidence_gated"):
            with self.subTest(mode=mode):
                wrapper = self.module.WebArenaEnvironmentWrapper.__new__(self.module.WebArenaEnvironmentWrapper)
                wrapper.webarena_env = Mock()
                wrapper.webarena_env.page.url = support.URL
                wrapper.webarena_env.page.evaluate.return_value = [{"name": "date", "direction": "descending"}]
                wrapper.global_config = types.SimpleNamespace(
                    env=types.SimpleNamespace(prune=True),
                    agent=types.SimpleNamespace(stop_guard=types.SimpleNamespace(mode=mode)))
                wrapper.obs = {"text": ("", Mock()), "image": None}
                wrapper.objective = support.OBJECTIVE
                self.module.translate_node_to_str.return_value = support.page()
                observation = wrapper.observation()
                self.assertEqual("order_history_sort" in observation, mode == "evidence_gated")
                if mode != "evidence_gated":
                    wrapper.webarena_env.page.evaluate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
