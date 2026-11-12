"""Decision reports preserve planning branches and rejected stop proposals."""

import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from test_stop_guard import load_agent_module


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("decision_tree_under_test", ROOT / "AgentOccam/decision_tree.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class DecisionTreeTests(unittest.TestCase):
    def test_pruned_branches_and_reused_ids_remain_visible_in_report(self):
        module = load_agent_module()
        root = module.PlanTreeNode(0, "branch", "Find orders", 0, "https://shop/", 0)
        actor = module.Actor.__new__(module.Actor)
        actor.plan_tree_root = actor.active_node = root
        actor.online_interaction = {"url": "https://shop/orders"}
        actor.get_step = lambda: 1
        actor.branch_planning(root, "Old approach")
        old_branch = actor.active_node
        actor.get_step = lambda: 2
        actor.branch_planning(old_branch, "Nested approach")
        actor.prune_planning(root, "Try another approach")
        actor.get_step = lambda: 3
        actor.branch_planning(root, "New approach")
        actor.active_node.note.append("Found the requested order")

        text = report.render_decision_tree({"id": 47}, actor=actor)

        self.assertIn("Plan [1] [PRUNED] Old approach", text)
        self.assertIn("Plan [2] [PRUNED] Nested approach", text)
        self.assertIn("Plan [1] [ACTIVE] New approach", text)
        self.assertIn("Resumed because: Try another approach", text)
        self.assertIn("Note: Found the requested order", text)
        self.assertEqual(len(root.children), 2)
        self.assertFalse(old_branch.visible)
        self.assertIs(actor.active_node, root.children[1])

    def test_parent_hidden_by_prune_also_marks_descendants_pruned(self):
        module = load_agent_module()
        root = module.PlanTreeNode(0, "branch", "Root", 0, "", 0)
        hidden = module.PlanTreeNode(1, "branch", "Hidden", 1, "", 1)
        descendant = module.PlanTreeNode(2, "branch", "Descendant", 2, "", 2)
        root.add_child(hidden)
        hidden.add_child(descendant)
        hidden.visible = False
        actor = types.SimpleNamespace(plan_tree_root=root, active_node=root)
        text = report.render_decision_tree({}, actor=actor)
        self.assertIn("Plan [2] [PRUNED] Descendant", text)
        self.assertTrue(descendant.visible)

    def test_rejected_stop_candidates_and_multiline_actions_are_distinct(self):
        data = {"id": 49, "trajectory": [
            {"objective": "Đếm đơn hàng", "plan": "[0] Find orders", "action": "",
             "proposed_action": "stop [0 orders]", "reason": "No evidence yet",
             "stop_guard": {"allowed": False, "reason": "insufficient_evidence"},
             "actor_10:action": "stop [0 orders]", "actor_2:action": "click [5]",
             "actor_2:reason": "Check orders", "done": False},
            {"action": "prune [0] [Try again]\nnote [Tiếp tục]",
             "navigation_action": "goto [https://shop/] [1]", "done": False},
            {"action": "stop [2 orders]", "stop_guard": {"allowed": True, "reason": "matching_witness"},
             "done": True, "success": 1.0},
        ]}
        before = json.dumps(data)
        with tempfile.TemporaryDirectory() as directory:
            json_file = Path(directory) / "49.json"
            json_file.write_text(before, encoding="utf-8")
            trash_file = Path(directory) / "49-trash.txt"
            trash_file.write_text("original trash", encoding="utf-8")
            path = report.save_decision_tree(json_file, data, status={"success": 0.0, "task_seconds": 1.2})
            text = path.read_text(encoding="utf-8")
            self.assertEqual(path, Path(directory) / "49-decision-tree.txt")
            self.assertEqual(json_file.read_text(encoding="utf-8"), before)
            self.assertEqual(trash_file.read_text(encoding="utf-8"), "original trash")
        self.assertEqual(json.dumps(data), before)
        self.assertIn("Đếm đơn hàng", text)
        self.assertIn("Proposed action: stop [0 orders]", text)
        self.assertIn("Stop Guard: REJECTED", text)
        self.assertIn("Selected action: (none; empty environment step)", text)
        self.assertNotIn("Selected action: stop [0 orders]", text)
        self.assertLess(text.index("actor_2: click"), text.index("actor_10: stop"))
        self.assertIn("Environment action: goto [https://shop/] [1]", text)
        self.assertIn("note [Tiếp tục]", text)
        self.assertIn("Stop Guard: ALLOWED", text)
        self.assertIn("Selected action: stop [2 orders]", text)
        self.assertIn("success: 0.0", text.split("PLAN TREE")[0])
        self.assertIn("task_seconds: 1.2", text)

    def test_empty_trajectory_without_planning_actor(self):
        text = report.render_decision_tree({"id": 47}, objective="Find orders")
        self.assertIn("Objective: Find orders", text)
        self.assertIn("Planning tree unavailable", text)
        self.assertIn("No decisions were logged.", text)


class RunnerReportTests(unittest.TestCase):
    def test_runner_saves_report_beside_each_tasks_json_and_trash(self):
        config = types.SimpleNamespace(
            logging=True, logdir="logs", logname="test-run", max_steps=5,
            env=types.SimpleNamespace(task_ids=[47, 49], max_browser_rows=100, headless=True),
            agent=types.SimpleNamespace(type="AgentOccam", actor=types.SimpleNamespace(model="qwen3-14b")),
        )
        agents, environments = [], []

        def make_agent(**kwargs):
            task_id = int(os.environ["CURRENT_TASK_ID"])
            actor = types.SimpleNamespace(output_trash_path="shared-trash.txt")
            agent = Mock(actor=actor, stop_mode="baseline")
            agent.get_trajectory.return_value = [{"objective": f"Task {task_id}", "action": f"stop [{task_id}]"}]

            def act(**kwargs):
                Path(actor.output_trash_path).write_text(f"Response {task_id}", encoding="utf-8")
                return {"done": True, "success": 1.0}

            agent.act.side_effect = act
            agents.append(agent)
            return agent

        def make_env(**kwargs):
            env = Mock()
            env.get_objective.return_value = f"Task {os.environ['CURRENT_TASK_ID']}"
            environments.append(env)
            return env

        def log_run(log_file, log_data, summary_file, summary_data):
            Path(log_file).write_text(json.dumps(log_data), encoding="utf-8")
            Path(summary_file).write_text("summary", encoding="utf-8")

        modules = {}
        for name, attributes in {
            "AgentOccam.env": {"WebArenaEnvironmentWrapper": make_env},
            "AgentOccam.AgentOccam": {"AgentOccam": make_agent},
            "AgentOccam.decision_tree": {"save_decision_tree": report.save_decision_tree},
            "AgentOccam.prompts": {"AgentOccam_prompt": types.SimpleNamespace()},
            "AgentOccam.utils": {"EVALUATOR_DIR": ""},
            "webagents_step.utils.data_prep": {
                "DotDict": lambda value: value, "yaml": Mock(safe_load=Mock(return_value=config)),
                "json": json, "random": random, "log_run": log_run,
            },
            "webagents_step.agents.step_agent": {"StepAgent": Mock()},
            "webagents_step.prompts.webarena": {"step_fewshot_template_adapted": Mock(), "step_fewshot_template": Mock()},
        }.items():
            modules[name] = types.ModuleType(name)
            modules[name].__dict__.update(attributes)

        spec = importlib.util.spec_from_file_location("runner_under_test", ROOT / "eval_webarena.py")
        runner = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(runner)

        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), patch("builtins.print"):
            try:
                os.chdir(directory)
                Path("config.yml").write_text("test config", encoding="utf-8")
                Path("config_files/tasks").mkdir(parents=True)
                for task_id in config.env.task_ids:
                    Path(f"config_files/tasks/{task_id}.json").write_text(json.dumps({"task_id": task_id}), encoding="utf-8")
                with patch.object(sys, "argv", ["eval_webarena.py", "--config", "config.yml"]):
                    runner.run()
                for task_id in config.env.task_ids:
                    output = Path("logs/test-run")
                    self.assertEqual(json.loads((output / f"{task_id}.json").read_text())["id"], task_id)
                    self.assertEqual((output / f"{task_id}-trash.txt").read_text(), f"Response {task_id}")
                    text = (output / f"{task_id}-decision-tree.txt").read_text(encoding="utf-8")
                    self.assertIn(f"DECISION TREE - Task {task_id}", text)
                    self.assertIn(f"Selected action: stop [{task_id}]", text)
                for env in environments:
                    env.close.assert_called_once()
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
