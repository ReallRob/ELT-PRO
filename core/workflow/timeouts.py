"""Timeout helpers for workflow runs."""

from core.dataframe_ops.code_exec import coerce_timeout_seconds


WORKFLOW_CODE_TIMEOUT_BUFFER_MS = 500


def workflow_code_timeout_ms(workflow_config):
    """Return an external timeout for workflows containing code blocks.

    The timeout is intentionally a UI/task-level discard deadline, not a safe
    thread kill. It sums configured code block timeouts because workflow steps run
    sequentially, then adds a small buffer for engine bookkeeping.
    """
    total_seconds = 0.0
    for step in (workflow_config or {}).get("steps", []) or []:
        if not isinstance(step, dict) or step.get("action") != "code_block":
            continue
        params = step.get("params") or {}
        total_seconds += coerce_timeout_seconds(params.get("timeout_seconds", 10))
    if total_seconds <= 0:
        return 0
    return int(total_seconds * 1000) + WORKFLOW_CODE_TIMEOUT_BUFFER_MS
