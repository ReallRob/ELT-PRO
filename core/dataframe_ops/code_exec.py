"""Shared execution helpers for user-written pandas code."""

from datetime import date, datetime, timedelta
import keyword
import math
import multiprocessing as mp
import queue
import re
import traceback

import numpy as np
import pandas as pd

from parameter_resolver import (
    normalize_parameter_mappings,
    normalize_runtime_parameters,
    resolve_placeholder,
)

DEFAULT_CODE_TIMEOUT_SECONDS = 10
MAX_CODE_TIMEOUT_SECONDS = 300


_ALIAS_RE = re.compile(r"^[A-Za-z_]\w*$")
_RESERVED_ALIASES = {
    "pd",
    "np",
    "re",
    "math",
    "datetime",
    "date",
    "timedelta",
    "params",
    "mappings",
    "param",
    "dfs",
    "result",
    "__builtins__",
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


def _build_code_builtins():
    return {
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
        tables[alias] = df
    if not tables:
        raise ValueError("代码执行需要至少一个输入表")
    return tables


def _run_dataframe_code_worker(payload, result_queue):
    try:
        tables = _prepare_tables(payload.get("tables") or {})
        params = normalize_runtime_parameters(payload.get("runtime_parameters") or {})
        mappings = normalize_parameter_mappings(payload.get("parameter_mappings") or {})
        fallback_alias = str(payload.get("fallback_alias") or "df").strip() or "df"

        def param(name, mapping_name=None):
            expression = str(name).strip()
            if mapping_name:
                expression = f"{expression}|map:{str(mapping_name).strip()}"
            return resolve_placeholder(expression, params, mappings, strict=True)

        dfs = dict(tables)
        primary_df = tables[fallback_alias] if fallback_alias in tables else next(iter(tables.values()))
        exec_env = {
            "__builtins__": _build_code_builtins(),
            "pd": pd,
            "np": np,
            "re": re,
            "math": math,
            "datetime": datetime,
            "date": date,
            "timedelta": timedelta,
            "params": params,
            "mappings": mappings,
            "param": param,
            "dfs": dfs,
            "df": primary_df,
        }
        exec_env.update(tables)
        exec(str(payload.get("code") or ""), exec_env, exec_env)

        target_col = str(payload.get("target_col") or "").strip()
        result_name = str(payload.get("result_name") or "").strip()
        if fallback_alias in exec_env:
            fallback_df = exec_env[fallback_alias]
        elif "df" in exec_env:
            fallback_df = exec_env["df"]
        else:
            fallback_df = primary_df

        if target_col and target_col in exec_env:
            if not isinstance(fallback_df, pd.DataFrame):
                raise TypeError(f"变量 {fallback_alias} 必须是 DataFrame，才能写入输出列")
            fallback_df[target_col] = exec_env[target_col]

        if result_name and result_name in exec_env:
            result_df = exec_env[result_name]
        else:
            result_df = fallback_df

        if not isinstance(result_df, pd.DataFrame):
            name = result_name if result_name and result_name in exec_env else fallback_alias
            raise TypeError(f"代码执行后 {name} 必须是 DataFrame")
        result_queue.put(("ok", result_df))
    except Exception:
        result_queue.put(("error", traceback.format_exc()))


def run_dataframe_code(
    tables,
    code,
    runtime_parameters=None,
    parameter_mappings=None,
    timeout_seconds=DEFAULT_CODE_TIMEOUT_SECONDS,
    result_name="result",
    fallback_alias="df",
    target_col="",
    error_prefix="代码执行",
):
    """Run user pandas code in a child process with a timeout."""
    timeout_seconds = coerce_timeout_seconds(timeout_seconds)
    ctx = _get_code_process_context()
    result_queue = ctx.Queue(maxsize=1)
    payload = {
        "tables": tables or {},
        "code": code,
        "runtime_parameters": runtime_parameters or {},
        "parameter_mappings": parameter_mappings or {},
        "result_name": result_name,
        "fallback_alias": fallback_alias,
        "target_col": target_col,
    }
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
    return result
