"""Validate core DataFrame operators with large synthetic inputs.

The checks focus on result shape and a few deterministic values so the script can
serve as a fast regression guard for performance-oriented refactors.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.dataframe_ops.aggregate import group_calc
from core.dataframe_ops.calc import calc_col
from core.dataframe_ops.filter import filter_data
from core.dataframe_ops.table import concat_rows, left_join


@dataclass
class CheckResult:
    name: str
    rows: int
    elapsed_ms: float
    output_shape: tuple[int, int]


def make_dataframe(rows: int) -> pd.DataFrame:
    groups = ["A", "B", "C", "D", "E"]
    return pd.DataFrame(
        {
            "id": range(rows),
            "group": [groups[i % len(groups)] for i in range(rows)],
            "amount": [float(i % 1000) for i in range(rows)],
            "qty": [i % 13 for i in range(rows)],
        }
    )


def make_lookup(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(rows),
            "flag": ["even" if i % 2 == 0 else "odd" for i in range(rows)],
        }
    )


def run_check(name: str, rows: int, func) -> CheckResult:
    started = time.perf_counter()
    output = func()
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not isinstance(output, pd.DataFrame):
        raise AssertionError(f"{name} did not return a DataFrame")
    return CheckResult(name, rows, elapsed_ms, output.shape)


def validate_filter(df: pd.DataFrame) -> pd.DataFrame:
    output = filter_data(df, [{"col": "amount", "op": ">=", "value": "900"}])
    expected_rows = int((df["amount"] >= 900).sum())
    assert output.shape[0] == expected_rows
    assert output["amount"].min() >= 900
    return output


def validate_join(df: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    output = left_join(df, lookup, "id", "id", ["flag"])
    assert output.shape == (len(df), 5)
    assert output.loc[0, "flag"] == "even"
    assert output.loc[1, "flag"] == "odd"
    return output


def validate_concat(df: pd.DataFrame) -> pd.DataFrame:
    left = df.iloc[: len(df) // 2]
    right = df.iloc[len(df) // 2 :]
    output = concat_rows(left, right, ignore_index=True)
    assert output.shape == df.shape
    assert output.loc[0, "id"] == 0
    assert output.loc[len(output) - 1, "id"] == len(df) - 1
    return output


def validate_group(df: pd.DataFrame) -> pd.DataFrame:
    output = group_calc(df, ["group"], {"amount": "sum", "qty": "mean"})
    assert output.shape[0] == df["group"].nunique()
    total = output["amount_sum"].sum()
    assert abs(total - df["amount"].sum()) < 0.0001
    return output


def validate_calc(df: pd.DataFrame) -> pd.DataFrame:
    output = calc_col(df, "total", "[amount] + [qty]")
    assert output.shape == (len(df), len(df.columns) + 1)
    assert output.loc[0, "total"] == output.loc[0, "amount"] + output.loc[0, "qty"]
    sample_index = min(len(output) - 1, 12345)
    assert output.loc[sample_index, "total"] == output.loc[sample_index, "amount"] + output.loc[sample_index, "qty"]
    return output


def run_validations(rows: int) -> list[CheckResult]:
    df = make_dataframe(rows)
    lookup = make_lookup(rows)
    checks = [
        ("filter", lambda: validate_filter(df)),
        ("left_join", lambda: validate_join(df, lookup)),
        ("concat_rows", lambda: validate_concat(df)),
        ("group_calc", lambda: validate_group(df)),
        ("calc_col", lambda: validate_calc(df)),
    ]
    return [run_check(name, rows, func) for name, func in checks]


def print_results(results: list[CheckResult]) -> None:
    print("# Large DataFrame Validation")
    print()
    print("| rows | check | elapsed_ms | output_shape |")
    print("| ---: | --- | ---: | ---: |")
    for item in results:
        print(
            f"| {item.rows} | {item.name} | {item.elapsed_ms:.1f} | "
            f"{item.output_shape[0]}x{item.output_shape[1]} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate large DataFrame operator outputs.")
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()
    print_results(run_validations(args.rows))


if __name__ == "__main__":
    main()
