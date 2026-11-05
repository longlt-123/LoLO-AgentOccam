"""Shared configuration and prompt text for the three stopping ablations."""


STOP_MODES = {"baseline", "prompt_only", "evidence_gated"}

EVIDENCE_GUIDANCE = """EVIDENCE BEFORE STOP:
Before proposing stop, check whether the observed evidence is sufficient for the user's requested conclusion.
Not seeing a result on the current page does not establish that it is absent from the whole dataset.
For totals, counts, complete lists, and absence claims, cover the relevant scope, including unseen pages or correctly applied filters. Do not assume global sorting from a few visible rows.
A positive existence answer can use one matching observed record; a request for N examples can finish once N distinct records satisfy all conditions. Do not browse further once sufficient evidence is available.
For an action task, inspect the resulting state or confirmation before claiming completion.
If evidence is missing, continue gathering it instead of guessing an answer. A step limit is not evidence."""


def _get(config, name, default=None):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def resolve_stop_mode(config=None):
    """Explicit mode selects the ablation; preserve legacy enabled:true/false.

    Reject contradictory settings rather than silently running the wrong arm.
    No mode/flag keeps the previously introduced default of evidence gating.
    """
    mode = _get(config, "mode")
    enabled = _get(config, "enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("stop_guard.enabled must be a YAML boolean")
    if mode is None:
        return "baseline" if enabled is False else "evidence_gated"
    if mode not in STOP_MODES:
        raise ValueError(f"Unknown stop_guard.mode: {mode}. Choose one of {sorted(STOP_MODES)}")
    if enabled is not None and enabled != (mode == "evidence_gated"):
        raise ValueError("stop_guard.mode conflicts with enabled; use mode alone for the ablations")
    return mode


def stopping_instruction(mode, step, max_steps):
    """Identical prompt treatment for prompt-only and evidence-gated arms.

    Baseline retains the original final-step instruction verbatim.
    """
    if mode not in STOP_MODES:
        raise ValueError(f"Unknown stopping mode: {mode}")
    addition = "" if mode == "baseline" else "\n\n" + EVIDENCE_GUIDANCE
    if step == max_steps - 1:
        addition += f"\n\nWARNING: You have a {max_steps}-step budget, and this would be your FINAL STEP. "
        if mode == "baseline":
            addition += "Wrap up your observations and return your answer with `stop [answer]` to maximize the reward."
        else:
            addition += ("Return `stop [answer]` only when the observations support the conclusion. "
                         "A step limit is not evidence for a guessed answer; if evidence is missing, continue checking it.")
    return addition
