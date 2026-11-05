"""Replay saved observations through the guard without calling a model/browser.

Usage (from repository root):
  python AgentOccam/scripts/audit_stop_guard.py path/to/47.json
"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def load_guard():
    # Avoid AgentOccam.__init__, which imports optional browser/LLM packages.
    path = Path(__file__).resolve().parents[1] / "AgentOccam/stop_guard.py"
    spec = importlib.util.spec_from_file_location("occam_stop_guard_audit", path,
                                                 submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.StopGuard


def audit(path, guard_class, guard_config=None):
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data["trajectory"]
    if not steps:
        return []
    # Audit all variants with the same gate, using the recorded site contract or
    # an explicit override. This does not rewrite recorded actions or rewards.
    config = dict(guard_config if guard_config is not None else data.get("stop_guard_config") or {})
    config["mode"] = "evidence_gated"
    config.pop("enabled", None)
    guard = guard_class(steps[0]["objective"], config)
    results = []
    for index, step in enumerate(steps):
        observation = step.get("observation", "")
        if step.get("order_history_sort") and isinstance(observation, str):
            observation = {"text": observation, "order_history_sort": step["order_history_sort"]}
        guard.observe(step.get("url", ""), observation)
        action = step.get("proposed_action", step.get("action", ""))
        decision = guard.check(action)
        if decision is not None:
            results.append({"file": str(path), "step": index, "action": action,
                            "recorded_success": step.get("success"), **decision})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Trajectory JSON files or directories")
    parser.add_argument("--config", type=Path, help="Use agent.stop_guard from this YAML, including its verified site contract")
    args = parser.parse_args()
    guard_config = None
    if args.config:
        import yaml
        guard_config = yaml.safe_load(args.config.read_text(encoding="utf-8"))["agent"]["stop_guard"]
    guard_class = load_guard()
    results = []
    for path in args.paths:
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            results.extend(audit(file, guard_class, guard_config))
    print(json.dumps(results, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
