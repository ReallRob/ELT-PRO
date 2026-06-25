"""Multi-input custom pandas code block operator."""

from core.dataframe_ops.code_exec import (
    DEFAULT_CODE_TIMEOUT_SECONDS,
    is_valid_code_alias,
    run_dataframe_code,
)


def code_block(
    tables,
    code,
    runtime_parameters=None,
    parameter_mappings=None,
    timeout_seconds=DEFAULT_CODE_TIMEOUT_SECONDS,
):
    """Run custom code over one or more DataFrames.

    Variables available to code:
    - df: first input table
    - custom aliases from bindings, for example df1 or summary
    - dfs: dictionary of alias -> DataFrame
    - pd, np, re, math, datetime, date, timedelta
    - params, mappings, param()
    """
    if not tables:
        raise ValueError("代码块至少需要连接一个输入表")
    for alias in tables:
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")

    return run_dataframe_code(
        tables,
        code,
        runtime_parameters=runtime_parameters,
        parameter_mappings=parameter_mappings,
        timeout_seconds=timeout_seconds,
        result_name="result",
        fallback_alias="df",
        error_prefix="代码块执行",
    )
