"""Human-readable decision reports; no browser or model dependencies."""

from pathlib import Path
import re


def _node(label, children=()):
    return str(label), list(children)


def _field(label, value):
    return _node(f"{label}: {value}")


def _render_tree(node, prefix="", connector=""):
    label, children = node
    lines = label.splitlines() or [""]
    yield prefix + connector + lines[0]
    continuation = prefix + ("|   " if connector == "+-- " else "    " if connector else "")
    for line in lines[1:]:
        yield continuation + line
    for index, child in enumerate(children):
        yield from _render_tree(child, continuation, "`-- " if index == len(children) - 1 else "+-- ")


def _plan_tree(node, active_node, ancestor_pruned=False):
    # Pruning can hide a parent without updating its descendants' visible flags.
    pruned = ancestor_pruned or not node.visible
    state = "PRUNED" if pruned else "ACTIVE" if node is active_node else "VISIBLE"
    children = [_field("Created at step", node.step), _field("URL", node.url)]
    children.extend(_field("Resumed because", reason) for reason in node.resume_reason)
    children.extend(_field("Note", note) for note in node.note)
    children.extend(_plan_tree(child, active_node, pruned) for child in node.children)
    return _node(f"Plan [{node.id}] [{state}] {node.text}", children)


def _decision(step, index):
    children = []
    for key, label in (
        ("url", "URL before action"),
        ("plan", "Plan after decision"),
        ("observation_description", "Observation summary"),
        ("reason", "Reason"),
    ):
        if step.get(key):
            children.append(_field(label, step[key]))

    candidate_keys = sorted(
        (key for key in step if re.fullmatch(r"actor_\d+:action", key)),
        key=lambda key: int(key.split(":")[0].split("_")[1]),
    )
    if candidate_keys:
        candidates = []
        for key in candidate_keys:
            actor = key.split(":")[0]
            reason = step.get(f"{actor}:reason")
            candidates.append(_node(
                f"{actor}: {step[key]}",
                [_field("Reason", reason)] if reason else [],
            ))
        children.append(_node("Actor candidates (proposals)", candidates))

    if step.get("proposed_action"):
        children.append(_field("Proposed action", step["proposed_action"]))

    guard = step.get("stop_guard")
    if isinstance(guard, dict):
        guard_fields = [
            _field(label, guard[key])
            for key, label in (("reason", "Reason"), ("feedback", "Feedback"),
                               ("rejection_count", "Rejection count"))
            if guard.get(key) is not None
        ]
        verdict = {True: "ALLOWED", False: "REJECTED"}.get(guard.get("allowed"), "UNKNOWN")
        children.append(_node(f"Stop Guard: {verdict}", guard_fields))

    action = step.get("action", "")
    children.append(_field("Selected action", action or "(none; empty environment step)"))
    if step.get("navigation_action"):
        children.append(_field("Environment action", step["navigation_action"]))
    outcome = [
        _field(key, step[key])
        for key in ("done", "success", "reward", "num_actions", "last_action_error", "termination_reason")
        if key in step
    ]
    if outcome:
        children.append(_node("Outcome", outcome))
    return _node(f"Step {index}", children)


def render_decision_tree(log_data, *, actor=None, status=None, objective=None):
    """Render the retained planning tree and every logged decision in order.

    Decisions are kept in chronological order separately from the final plan
    tree: pruning folds step history into ancestors and can reuse plan IDs.
    """
    trajectory = log_data.get("trajectory") or []
    objective = objective or (trajectory[0].get("objective") if trajectory else None)
    lines = [f"DECISION TREE - Task {log_data.get('id', 'unknown')}"]
    for label, value in (
        ("Objective", objective), ("Model", log_data.get("model")),
        ("Agent", log_data.get("type")), ("Stop mode", log_data.get("stop_mode")),
    ):
        if value is not None:
            lines.append(f"{label}: {value}")
    final_status = status if status is not None else (trajectory[-1] if trajectory else {})
    for key in ("done", "success", "reward", "num_actions", "termination_reason", "task_seconds"):
        if key in final_status:
            lines.append(f"{key}: {final_status[key]}")

    lines.extend(["", "PLAN TREE (final state, including pruned branches)"])
    root = getattr(actor, "plan_tree_root", None)
    if root is not None:
        lines.extend(_render_tree(_plan_tree(root, getattr(actor, "active_node", None))))
    else:
        lines.append("Planning tree unavailable for this agent; see logged decisions below.")

    lines.extend(["", "DECISIONS (chronological, step numbers start at 0)"])
    if trajectory:
        lines.extend(_render_tree(_node("Task decisions", [
            _decision(step, index) for index, step in enumerate(trajectory)
        ])))
    else:
        lines.append("No decisions were logged.")
    return "\n".join(lines) + "\n"


def save_decision_tree(log_file, log_data, *, actor=None, status=None, objective=None):
    """Write a UTF-8 report beside the task's JSON log and return its path."""
    log_path = Path(log_file)
    destination = log_path.with_name(f"{log_path.stem}-decision-tree.txt")
    destination.write_text(
        render_decision_tree(log_data, actor=actor, status=status, objective=objective),
        encoding="utf-8",
    )
    return destination
