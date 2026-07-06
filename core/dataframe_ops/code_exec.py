"""Shared execution helpers for user-written pandas/openpyxl code."""

from __future__ import annotations

import builtins as py_builtins
from contextlib import redirect_stderr, redirect_stdout
from copy import copy, deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import keyword
import math
import multiprocessing as mp
import queue
import re
import shutil
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
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
MAX_CODE_TIMEOUT_SECONDS = 3600
MAX_LOG_LINE_CHARS = 10000
_LOCAL_RETURN_KEY = "__code_block_locals__"
_ALLOWED_IMPORT_ROOTS = {
    "copy",
    "datetime",
    "math",
    "numpy",
    "openpyxl",
    "os",
    "pandas",
    "re",
    "sys",
    "time",
}
PRESET_IMPORT_SNIPPET = """import pandas as pd
import numpy as np
import re
import math
import openpyxl
from datetime import datetime, date, timedelta
from copy import copy, deepcopy
from openpyxl.utils import get_column_letter"""
SUPPORTED_IMPORT_ROOTS_TEXT = """pandas
numpy
openpyxl
os
sys
re
math
datetime
copy
time"""


@dataclass
class CodeExecutionOutput:
    name: str
    data: object
    data_type: str = "table"


SUPPORTED_IMPORT_ROOTS_TEXT = "\n".join(sorted(_ALLOWED_IMPORT_ROOTS))

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


def allowed_import_roots():
    return tuple(sorted(_ALLOWED_IMPORT_ROOTS))


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


class _QueueWriter:
    def __init__(self, log_queue, stream):
        self._log_queue = log_queue
        self._stream = stream
        self._buffer = ""

    def write(self, text):
        value = str(text or "")
        if not value:
            return 0
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line.rstrip("\r"))
        if len(self._buffer) > MAX_LOG_LINE_CHARS:
            self._emit(self._buffer[:MAX_LOG_LINE_CHARS] + " ...[已截断]")
            self._buffer = ""
        return len(value)

    def flush(self):
        if self._buffer:
            self._emit(self._buffer.rstrip("\r"))
            self._buffer = ""

    def _emit(self, line):
        try:
            self._log_queue.put({"stream": self._stream, "message": str(line)})
        except Exception:
            pass


def _emit_code_log(log_callback, stream, message):
    if not callable(log_callback):
        return
    prefix = "代码块错误输出" if stream == "stderr" else "代码块输出"
    text = f"{prefix}: {message}" if str(message) else f"{prefix}:"
    try:
        log_callback(text)
    except Exception:
        pass


def _drain_code_log_queue(log_queue, log_callback):
    if log_queue is None:
        return
    while True:
        try:
            item = log_queue.get_nowait()
        except queue.Empty:
            break
        except (EOFError, OSError):
            break
        if not isinstance(item, dict):
            continue
        stream = str(item.get("stream") or "stdout")
        message = item.get("message")
        _emit_code_log(log_callback, stream, "" if message is None else str(message))


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


def _workbook_entry_meta(entry):
    if not isinstance(entry, dict):
        return {}
    return {
        key: deepcopy(value)
        for key, value in entry.items()
        if key != "_wb"
    }


def _pack_workbooks_for_process(raw_workbooks, tmp_dir):
    packed = {}
    tmp_dir = Path(tmp_dir)
    for index, (alias, value) in enumerate((raw_workbooks or {}).items(), start=1):
        alias = str(alias or "").strip()
        if not alias:
            continue
        if not is_valid_code_alias(alias):
            raise ValueError(f"变量名无效: {alias}")
        wb = value.get("_wb") if isinstance(value, dict) else value
        if not isinstance(wb, Workbook):
            raise TypeError(f"变量 {alias} 对应的输入不是 Workbook")
        input_path = tmp_dir / f"input_wb_{index}.xlsx"
        wb.save(input_path)
        packed[alias] = {
            "_workbook_path": str(input_path),
            "_entry_meta": _workbook_entry_meta(value),
        }
    return packed


def _load_process_workbook_inputs(raw_workbooks):
    loaded = {}
    for alias, item in (raw_workbooks or {}).items():
        if isinstance(item, dict) and item.get("_workbook_path"):
            entry = dict(item.get("_entry_meta") or {})
            entry["_wb"] = openpyxl.load_workbook(item.get("_workbook_path"))
            loaded[alias] = entry
        else:
            loaded[alias] = item
    return loaded


def _load_workbook_entry_from_path(item):
    entry = dict(item.get("entry_meta") or {})
    entry["_wb"] = openpyxl.load_workbook(item.get("path"))
    return entry


def _ensure_unique_aliases(*groups):
    seen = set()
    for group in groups:
        for alias in group:
            if alias in seen:
                raise ValueError(f"变量名重复: {alias}")
            seen.add(alias)


def _normalize_function_spaces(raw_spaces, legacy_global_code=""):
    spaces = []
    for index, item in enumerate(raw_spaces or [], start=1):
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        namespace = str(item.get("namespace") or item.get("id") or f"funcs{index}").strip()
        if not namespace:
            namespace = f"funcs{index}"
        if not is_valid_code_alias(namespace):
            raise ValueError(f"函数空间命名空间无效: {namespace}")
        spaces.append(
            {
                "id": str(item.get("id") or namespace),
                "name": str(item.get("name") or namespace),
                "namespace": namespace,
                "enabled": bool(item.get("enabled", True)),
                "expose_globals": bool(item.get("expose_globals", False)),
                "code": code,
            }
        )
    if not spaces and str(legacy_global_code or "").strip():
        spaces.append(
            {
                "id": "legacy_global",
                "name": "旧全局函数",
                "namespace": "global_funcs",
                "enabled": True,
                "expose_globals": True,
                "code": str(legacy_global_code or ""),
            }
        )
    return spaces


def _public_space_values(space_env):
    hidden = set(_ALLOWED_WRAPPED_NAMES) | _RESERVED_ALIASES | {"__builtins__"}
    public = {}
    for name, value in (space_env or {}).items():
        if not is_valid_code_alias(name) or name in hidden:
            continue
        public[name] = value
    return public


def _execute_function_spaces(exec_env, function_spaces, legacy_global_code=""):
    spaces = _normalize_function_spaces(function_spaces, legacy_global_code)
    for space in spaces:
        if not space.get("enabled", True):
            continue
        code = str(space.get("code") or "")
        if not code.strip():
            continue
        namespace = str(space.get("namespace") or "").strip()
        space_env = dict(exec_env)
        exec(compile(code, f"<函数空间:{namespace}>", "exec"), space_env, space_env)
        public = _public_space_values(space_env)
        exec_env[namespace] = SimpleNamespace(**public)
        if space.get("expose_globals", False):
            exec_env.update(public)
    return spaces


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


def _serialize_workbook_entry_for_process(entry, output_dir, index):
    if not _is_workbook_entry(entry):
        raise TypeError("代码块 Workbook 输出无效")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"output_wb_{index}.xlsx"
    entry.get("_wb").save(output_path)
    meta = _workbook_entry_meta(entry)
    return {"_workbook_path": str(output_path), "_entry_meta": meta}


def _value_type_label(value):
    module = type(value).__module__
    name = type(value).__name__
    return name if module in {"builtins", "__main__"} else f"{module}.{name}"


def _make_code_output(name, value, output_names, index, workbook_entries=None):
    output_name = str(name or "").strip() or _fallback_output_name(output_names, index)
    if isinstance(value, pd.DataFrame):
        return {"name": output_name, "data_type": "table", "data": value}
    process_output_dir = None
    if isinstance(workbook_entries, dict):
        process_output_dir = workbook_entries.get("__process_output_dir__")
    if _is_workbook_entry(value):
        data = (
            _serialize_workbook_entry_for_process(value, process_output_dir, index)
            if process_output_dir
            else value
        )
        return {"name": output_name, "data_type": "workbook", "data": data}
    if isinstance(value, Workbook):
        entry = _workbook_entry_for_workbook(value, workbook_entries)
        data = (
            _serialize_workbook_entry_for_process(entry, process_output_dir, index)
            if process_output_dir
            else entry
        )
        return {
            "name": output_name,
            "data_type": "workbook",
            "data": data,
        }
    if isinstance(value, Worksheet):
        wb = getattr(value, "parent", None)
        if isinstance(wb, Workbook):
            entry = _workbook_entry_for_workbook(wb, workbook_entries)
            data = (
                _serialize_workbook_entry_for_process(entry, process_output_dir, index)
                if process_output_dir
                else entry
            )
            return {
                "name": output_name,
                "data_type": "workbook",
                "data": data,
            }
    raise TypeError(
        f"代码块输出 {name or index} 的类型不支持：{_value_type_label(value)}。\n"
        "正式输出只支持 pandas.DataFrame、openpyxl.Workbook 或 openpyxl.Worksheet；"
        "如果你只是想在全局函数里返回普通值，可以在当前代码中继续使用它，"
        "需要输出给下游时，return / result 需要是 DataFrame、Workbook、Worksheet，"
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
    raw_workbooks = payload.get("workbooks") or {}
    if payload.get("process_workbook_paths"):
        raw_workbooks = _load_process_workbook_inputs(raw_workbooks)
    workbooks, workbook_entries = _prepare_workbooks(raw_workbooks)
    if payload.get("process_output_dir"):
        workbook_entries["__process_output_dir__"] = payload.get("process_output_dir")
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
    function_spaces = payload.get("function_spaces") or []
    node_code = str(payload.get("code") or "")
    _execute_function_spaces(exec_env, function_spaces, global_code)

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
    else:
        raw_result = workbook_entries.get(primary_wb_alias) if primary_wb is not None else fallback_df

    outputs = [] if raw_result is None else _normalize_code_outputs(
        raw_result,
        payload.get("output_names") or [],
        workbook_entries,
    )
    return {"outputs": outputs, "state": state}


def _run_dataframe_code_worker(payload, result_queue, log_queue=None):
    stdout_writer = _QueueWriter(log_queue, "stdout") if log_queue is not None else None
    stderr_writer = _QueueWriter(log_queue, "stderr") if log_queue is not None else None
    try:
        if log_queue is None:
            result = _execute_code_payload(payload)
        else:
            try:
                with redirect_stdout(stdout_writer), redirect_stderr(stderr_writer):
                    result = _execute_code_payload(payload)
            finally:
                stdout_writer.flush()
                stderr_writer.flush()
        result_queue.put(("ok", result))
    except Exception:
        result_queue.put(("error", traceback.format_exc()))


def _unpack_process_outputs(result):
    unpacked = []
    for item in result.get("outputs") or []:
        if not isinstance(item, dict):
            continue
        output = dict(item)
        if output.get("data_type") == "workbook":
            data = output.get("data")
            if isinstance(data, dict) and data.get("_workbook_path"):
                output["data"] = _load_workbook_entry_from_path(
                    {
                        "path": data.get("_workbook_path"),
                        "entry_meta": data.get("_entry_meta") or {},
                    }
                )
        unpacked.append(output)
    return unpacked


def run_dataframe_code(
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
    result_name="result",
    fallback_alias="df",
    target_col="",
    output_names=None,
    error_prefix="代码执行",
    log_callback=None,
):
    """Run user code and return DataFrame/workbook outputs."""
    timeout_seconds = coerce_timeout_seconds(timeout_seconds)
    payload = {
        "tables": tables or {},
        "workbooks": workbooks or {},
        "worksheets": worksheets or {},
        "code": code,
        "global_code": global_code or "",
        "function_spaces": function_spaces or [],
        "state": state or {},
        "runtime_parameters": runtime_parameters or {},
        "parameter_mappings": parameter_mappings or {},
        "result_name": result_name,
        "fallback_alias": fallback_alias,
        "target_col": target_col,
        "output_names": output_names or [],
    }

    tmp_root = tempfile.mkdtemp(prefix="code_block_")
    try:
        tmp_dir = Path(tmp_root)
        if workbooks:
            payload["workbooks"] = _pack_workbooks_for_process(workbooks, tmp_dir)
            payload["process_workbook_paths"] = True
            output_dir = tmp_dir / "outputs"
            output_dir.mkdir(parents=True, exist_ok=True)
            payload["process_output_dir"] = str(output_dir)

        ctx = _get_code_process_context()
        result_queue = ctx.Queue(maxsize=1)
        log_queue = ctx.Queue() if callable(log_callback) else None
        process = ctx.Process(
            target=_run_dataframe_code_worker,
            args=(payload, result_queue, log_queue),
        )
        process.daemon = True
        process.start()
        try:
            deadline = time.monotonic() + timeout_seconds
            status = None
            result = None
            while True:
                _drain_code_log_queue(log_queue, log_callback)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{error_prefix}超时：超过 {timeout_seconds:g} 秒，已终止执行")
                try:
                    status, result = result_queue.get(timeout=min(0.05, remaining))
                    break
                except queue.Empty:
                    if process.is_alive():
                        continue
                    _drain_code_log_queue(log_queue, log_callback)
                    try:
                        status, result = result_queue.get_nowait()
                        break
                    except queue.Empty:
                        raise RuntimeError(f"{error_prefix}进程异常退出，退出码: {process.exitcode}")
        finally:
            process.join(0.2)
            if process.is_alive():
                process.terminate()
                process.join(1)
            _drain_code_log_queue(log_queue, log_callback)
            result_queue.close()
            if log_queue is not None:
                log_queue.close()

        if status == "error":
            raise ValueError(f"{error_prefix}失败：\n{result}")
        process_outputs = _unpack_process_outputs(result)

        outputs = [
            CodeExecutionOutput(
                name=str(item.get("name") or f"代码结果{index}"),
                data=item.get("data"),
                data_type=str(item.get("data_type") or "table"),
            )
            for index, item in enumerate(process_outputs, start=1)
            if isinstance(item, dict)
        ]
        return CodeExecutionResult(outputs=outputs, state=dict(result.get("state") or {}))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
