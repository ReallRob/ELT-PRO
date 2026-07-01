"""Shared execution helpers for user-written pandas/openpyxl code."""

from __future__ import annotations

import builtins as py_builtins
from copy import copy, deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import keyword
import math
import multiprocessing as mp
import queue
import re
import traceback

import numpy as np
import openpyxl
import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from parameter_resolver import (
    normalize_parameter_mappings,
    normalize_runtime_parameters,
    resolve_placeholder,
)

DEFAULT_CODE_TIMEOUT_SECONDS = 10
MAX_CODE_TIMEOUT_SECONDS = 300
_LOCAL_RETURN_KEY = "__code_block_locals__"
_ALLOWED_IMPORT_ROOTS = {
    "copy",
    "datetime",
    "math",
    "numpy",
    "openpyxl",
    "pandas",
    "re",
}


@dataclass
class CodeExecutionOutput:
    name: str
    data: object
    data_type: str = "table"


@dataclass
class CodeExecutionResult:
    outputs: list[CodeExecutionOutput]
    state: dict


_ALIAS_RE = re.compile(r"^[A-Za-z_]\w*$")
_RESERVED_ALIASES = {
    "pd",
    "np",
    "re",
    "math",
    "datetime",
    "date",
    "timedelta",
    "openpyxl",
    "copy",
    "deepcopy",
    "get_column_letter",
    "params",
    "mappings",
    "param",
    "state",
    "dfs",
    "wbs",
    "wss",
    "locals",
    "result",
    "__builtins__",
}
_ALLOWED_WRAPPED_NAMES = {
    "pd",
    "np",
    "re",
    "math",
    "datetime",
    "date",
    "timedelta",
    "openpyxl",
    "copy",
    "deepcopy",
    "get_column_letter",
    "params",
    "mappings",
    "param",
    "state",
    "dfs",
    "df",
    "wbs",
    "wss",
    "wb",
    "ws",
}


def is_valid_code_alias(alias):
    text = str(alias or "").strip()
    return bool(
        text
        and _ALIAS_RE.match(text)
        and not keyword.iskeyword(text)
        and text not in _RESERVED_ALIASES
    )


def coerce_timeout_seconds(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = DEFAULT_CODE_TIMEOUT_SECONDS
    return max(1.0, min(float(MAX_CODE_TIMEOUT_SECONDS), seconds))


def _get_code_process_context():
    methods = mp.get_all_start_methods()
    if "spawn" in methods:
        return mp.get_context("spawn")
    return mp.get_context()


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Allow normal import syntax for the libraries bundled into code blocks."""
    if level != 0:
        raise ImportError("代码块不支持相对 import")
    root = str(name or "").split(".", 1)[0]
    if root not in _ALLOWED_IMPORT_ROOTS:
        allowed = ", ".join(sorted(_ALLOWED_IMPORT_ROOTS))
        raise ImportError(f"代码块不允许 import {name!r}；允许的库: {allowed}")
    return py_builtins.__import__(name, globals, locals, fromlist, level)


def _build_code_builtins():
    return {
        "__import__": _restricted_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "locals": locals,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }


def _prepare_tables(raw_tables):
    tables = {}
    for alias, df in (raw_tables or {}).items():
        alias = str(alias or "").strip()
        if not alias:
            continue
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"变量 {alias} 对应的输入不是 DataFrame")
        tables[alias] = df.copy()
    return tables


def _prepare_workbooks(raw_workbooks):
    workbooks = {}
    workbook_entries = {}
    for alias, value in (raw_workbooks or {}).items():
        alias = str(alias or "").strip()
        if not alias:
            continue
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
        wb = value.get("_wb") if isinstance(value, dict) else value
        if not isinstance(wb, Workbook):
            raise TypeError(f"变量 {alias} 对应的输入不是 Workbook")
        workbooks[alias] = wb
        workbook_entries[alias] = value if isinstance(value, dict) else {"_wb": wb}
    return workbooks, workbook_entries


def _prepare_worksheets(raw_worksheets, workbooks):
    worksheets = {}
    for alias, item in (raw_worksheets or {}).items():
        alias = str(alias or "").strip()
        if not alias:
            continue
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
        wb_alias = str((item or {}).get("workbook_alias") or "").strip()
        sheet_name = str((item or {}).get("sheet_name") or "").strip()
        wb = workbooks.get(wb_alias)
        if wb is None:
            continue
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ValueError(f"工作簿 {wb_alias} 不存在工作表: {sheet_name}")
            worksheets[alias] = wb[sheet_name]
        else:
            worksheets[alias] = wb.active
    return worksheets


def _ensure_unique_aliases(*groups):
    seen = set()
    for group in groups:
        for alias in group:
            if alias in seen:
                raise ValueError(f"变量名重复: {alias}")
            seen.add(alias)


def _fallback_output_name(output_names, index):
    if index - 1 < len(output_names):
        name = str(output_names[index - 1] or "").strip()
        if name:
            return name
    return "代码块结果" if index == 1 else f"代码块结果{index}"


def _is_workbook_entry(value):
    return isinstance(value, dict) and isinstance(value.get("_wb"), Workbook)


def _workbook_entry_for_workbook(wb, workbook_entries):
    for entry in (workbook_entries or {}).values():
        if _is_workbook_entry(entry) and entry.get("_wb") is wb:
            return entry
    return {"_wb": wb}


def _value_type_label(value):
    module = type(value).__module__
    name = type(value).__name__
    return name if module in {"builtins", "__main__"} else f"{module}.{name}"


def _make_code_output(name, value, output_names, index, workbook_entries=None):
    output_name = str(name or "").strip() or _fallback_output_name(output_names, index)
    if isinstance(value, pd.DataFrame):
        return {"name": output_name, "data_type": "table", "data": value}
    if _is_workbook_entry(value):
        return {"name": output_name, "data_type": "workbook", "data": value}
    if isinstance(value, Workbook):
        return {
            "name": output_name,
            "data_type": "workbook",
            "data": _workbook_entry_for_workbook(value, workbook_entries),
        }
    if isinstance(value, Worksheet):
        wb = getattr(value, "parent", None)
        if isinstance(wb, Workbook):
            return {
                "name": output_name,
                "data_type": "workbook",
                "data": _workbook_entry_for_workbook(wb, workbook_entries),
            }
    raise TypeError(
        f"代码块输出 {name or index} 的类型不支持：{_value_type_label(value)}。\n"
        "正式输出只支持 pandas.DataFrame、openpyxl.Workbook 或 openpyxl.Worksheet；"
        "如果你只是想在全局函数里返回普通值，可以在当前代码中继续使用它，"
        "但最终 return / result 需要是 DataFrame、Workbook、Worksheet，"
        "或由它们组成的字典/列表。"
    )


def _normalize_code_outputs(raw_result, output_names, workbook_entries=None):
    if _is_workbook_entry(raw_result):
        return [_make_code_output("", raw_result, output_names, 1, workbook_entries)]

    if isinstance(raw_result, dict):
        outputs = []
        for index, (name, value) in enumerate(raw_result.items(), start=1):
            output_name = str(name or "").strip()
            if not output_name:
                raise ValueError("代码块返回字典的 key 必须是非空输出名称")
            outputs.append(
                _make_code_output(output_name, value, output_names, index, workbook_entries)
            )
        if not outputs:
            raise ValueError("代码块返回字典不能为空")
        return outputs

    if isinstance(raw_result, (list, tuple)):
        if not raw_result:
            raise ValueError("代码块返回列表/元组不能为空")
        return [
            _make_code_output("", value, output_names, index, workbook_entries)
            for index, value in enumerate(raw_result, start=1)
        ]

    return [_make_code_output("", raw_result, output_names, 1, workbook_entries)]


def _wrap_code_as_main(code, available_names):
    user_args = ", ".join(
        f"{name}={name}"
        for name in available_names
        if is_valid_code_alias(name) or name in _ALLOWED_WRAPPED_NAMES
    )
    hidden_arg = "__code_block_locals_fn=__builtins__['locals']"
    args = f"{user_args}, {hidden_arg}" if user_args else hidden_arg
    body_lines = str(code or "").splitlines()
    indented = [f"    {line}" if line.strip() else "" for line in body_lines]
    if not indented:
        indented = ["    pass"]
    indented.append(f"    return {{{_LOCAL_RETURN_KEY!r}: __code_block_locals_fn()}}")
    return f"def __code_block_main__({args}):\n" + "\n".join(indented)


def _execute_code_payload(payload):
    tables = _prepare_tables(payload.get("tables") or {})
    workbooks, workbook_entries = _prepare_workbooks(payload.get("workbooks") or {})
    worksheets = _prepare_worksheets(payload.get("worksheets") or {}, workbooks)
    _ensure_unique_aliases(tables, workbooks, worksheets)
    params = normalize_runtime_parameters(payload.get("runtime_parameters") or {})
    mappings = normalize_parameter_mappings(payload.get("parameter_mappings") or {})
    state = dict(payload.get("state") or {})
    fallback_alias = str(payload.get("fallback_alias") or "df").strip() or "df"

    def param(name, mapping_name=None):
        expression = str(name).strip()
        if mapping_name:
            expression = f"{expression}|map:{str(mapping_name).strip()}"
        return resolve_placeholder(expression, params, mappings, strict=True)

    dfs = dict(tables)
    wbs = dict(workbooks)
    wss = dict(worksheets)
    primary_df = tables.get(fallback_alias)
    if primary_df is None:
        primary_df = next(iter(tables.values())) if tables else None
    primary_wb_alias = "wb" if "wb" in workbooks else (next(iter(workbooks.keys())) if workbooks else "")
    primary_wb = workbooks.get(primary_wb_alias)
    primary_ws_alias = "ws" if "ws" in worksheets else (next(iter(worksheets.keys())) if worksheets else "")
    primary_ws = worksheets.get(primary_ws_alias)

    exec_env = {
        "__builtins__": _build_code_builtins(),
        "pd": pd,
        "np": np,
        "re": re,
        "math": math,
        "datetime": datetime,
        "date": date,
        "timedelta": timedelta,
        "openpyxl": openpyxl,
        "copy": copy,
        "deepcopy": deepcopy,
        "get_column_letter": get_column_letter,
        "params": params,
        "mappings": mappings,
        "param": param,
        "state": state,
        "dfs": dfs,
        "df": primary_df,
        "wbs": wbs,
        "wss": wss,
        "wb": primary_wb,
    }
    if primary_ws is not None:
        exec_env["ws"] = primary_ws
    exec_env.update(tables)
    exec_env.update(workbooks)
    exec_env.update(worksheets)

    global_code = str(payload.get("global_code") or "")
    node_code = str(payload.get("code") or "")
    if global_code.strip():
        exec(compile(global_code, "<全局函数>", "exec"), exec_env, exec_env)

    explicit_return = False
    returned = None
    local_vars = {}
    if node_code.strip():
        wrapped = _wrap_code_as_main(node_code, exec_env.keys())
        exec(compile(wrapped, "<当前代码块>", "exec"), exec_env, exec_env)
        returned = exec_env["__code_block_main__"]()
        if isinstance(returned, dict) and set(returned.keys()) == {_LOCAL_RETURN_KEY}:
            local_vars = dict(returned.get(_LOCAL_RETURN_KEY) or {})
            if isinstance(local_vars.get("state"), dict):
                state = local_vars["state"]
        else:
            explicit_return = True

    target_col = str(payload.get("target_col") or "").strip()
    result_name = str(payload.get("result_name") or "").strip()
    if fallback_alias in local_vars:
        fallback_df = local_vars[fallback_alias]
    elif fallback_alias in exec_env:
        fallback_df = exec_env[fallback_alias]
    elif "df" in local_vars:
        fallback_df = local_vars["df"]
    elif "df" in exec_env:
        fallback_df = exec_env["df"]
    else:
        fallback_df = primary_df

    target_source = local_vars if target_col in local_vars else exec_env
    if target_col and target_col in target_source:
        if not isinstance(fallback_df, pd.DataFrame):
            raise TypeError(f"变量 {fallback_alias} 必须是 DataFrame，才能写入输出列")
        fallback_df[target_col] = target_source[target_col]

    if explicit_return:
        raw_result = returned
    elif result_name and result_name in local_vars:
        raw_result = local_vars[result_name]
    elif result_name and result_name in exec_env:
        raw_result = exec_env[result_name]
    else:
        raw_result = workbook_entries.get(primary_wb_alias) if primary_wb is not None else fallback_df
        if raw_result is None:
            raise ValueError("代码块没有产生输出；请 return DataFrame/Workbook，或赋值 result/df")

    outputs = _normalize_code_outputs(
        raw_result,
        payload.get("output_names") or [],
        workbook_entries,
    )
    return {"outputs": outputs, "state": state}


def _run_dataframe_code_worker(payload, result_queue):
    try:
        result_queue.put(("ok", _execute_code_payload(payload)))
    except Exception:
        result_queue.put(("error", traceback.format_exc()))


def run_dataframe_code(
    tables,
    code,
    workbooks=None,
    worksheets=None,
    global_code="",
    state=None,
    runtime_parameters=None,
    parameter_mappings=None,
    timeout_seconds=DEFAULT_CODE_TIMEOUT_SECONDS,
    result_name="result",
    fallback_alias="df",
    target_col="",
    output_names=None,
    error_prefix="代码执行",
):
    """Run user code and return DataFrame/workbook outputs."""
    timeout_seconds = coerce_timeout_seconds(timeout_seconds)
    payload = {
        "tables": tables or {},
        "workbooks": workbooks or {},
        "worksheets": worksheets or {},
        "code": code,
        "global_code": global_code or "",
        "state": state or {},
        "runtime_parameters": runtime_parameters or {},
        "parameter_mappings": parameter_mappings or {},
        "result_name": result_name,
        "fallback_alias": fallback_alias,
        "target_col": target_col,
        "output_names": output_names or [],
    }

    if workbooks:
        try:
            result = _execute_code_payload(payload)
        except Exception:
            raise ValueError(f"{error_prefix}失败：\n{traceback.format_exc()}")
        outputs = [
            CodeExecutionOutput(
                name=str(item.get("name") or f"代码结果{index}"),
                data=item.get("data"),
                data_type=str(item.get("data_type") or "table"),
            )
            for index, item in enumerate(result.get("outputs") or [], start=1)
            if isinstance(item, dict)
        ]
        return CodeExecutionResult(outputs=outputs, state=dict(result.get("state") or {}))

    ctx = _get_code_process_context()
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_run_dataframe_code_worker, args=(payload, result_queue))
    process.daemon = True
    process.start()
    try:
        status, result = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        if process.is_alive():
            process.terminate()
            process.join(1)
        raise TimeoutError(f"{error_prefix}超时：超过 {timeout_seconds:g} 秒，已终止执行")
    finally:
        process.join(0.2)
        if process.is_alive():
            process.terminate()
            process.join(1)
        result_queue.close()

    if status == "error":
        raise ValueError(f"{error_prefix}失败：\n{result}")

    outputs = [
        CodeExecutionOutput(
            name=str(item.get("name") or f"代码结果{index}"),
            data=item.get("data"),
            data_type=str(item.get("data_type") or "table"),
        )
        for index, item in enumerate(result.get("outputs") or [], start=1)
        if isinstance(item, dict)
    ]
    return CodeExecutionResult(outputs=outputs, state=dict(result.get("state") or {}))
