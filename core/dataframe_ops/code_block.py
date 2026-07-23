"""Multi-input custom code block operator."""

from core.dataframe_ops.code_exec import (
    DEFAULT_CODE_TIMEOUT_SECONDS,
    is_valid_code_alias,
    run_dataframe_code,
)


def code_block(
    tables,
    code,
    workbooks=None,
    worksheets=None,
    global_code="",
    function_spaces=None,
    state=None,
    runtime_parameters=None,
    parameter_mappings=None,
    timeout_seconds=DEFAULT_CODE_TIMEOUT_SECONDS,
    output_names=None,
    log_callback=None,
    execution_mode="auto",
):
    """Run custom code over DataFrame and/or workbook inputs.

    Variables available to code:
    - df / df1... and custom aliases: copied DataFrame inputs
    - dfs: dict of alias -> DataFrame
    - wb / wb1... and custom aliases: workbook inputs
    - wbs: dict of alias -> Workbook
    - use wb.active or wb["SheetName"] when a worksheet object is needed
    - function namespaces such as date_utils / excel_utils when configured
    - function reference names, such as ``from fun import *`` when the reference is ``fun``
    - pd, np, re, math, datetime, date, timedelta, openpyxl
    - copy, deepcopy, get_column_letter
    - params, mappings, param(), state
    - should_cancel() / check_cancel() for cooperative stopping

    ``execution_mode="process"`` runs the code in an isolated child process with
    ``__name__ == "__main__"``. It can create its own QApplication, reads a
    copy of params/mappings, and does not support in-memory Workbook inputs.
    """
    tables = tables or {}
    workbooks = workbooks or {}
    worksheets = worksheets or {}
    for alias in tables:
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
    for alias in workbooks:
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
    for alias in worksheets:
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")

    return run_dataframe_code(
        tables,
        code,
        workbooks=workbooks,
        worksheets=worksheets,
        global_code=global_code,
        function_spaces=function_spaces,
        state=state,
        runtime_parameters=runtime_parameters,
        parameter_mappings=parameter_mappings,
        timeout_seconds=timeout_seconds,
        result_name="result",
        fallback_alias="df",
        output_names=output_names,
        error_prefix="代码块执行",
        log_callback=log_callback,
        execution_mode=execution_mode,
    )
