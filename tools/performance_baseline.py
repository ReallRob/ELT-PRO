"""Run lightweight performance baselines for core DataFrame operators.

This script is intentionally independent from the PyQt UI. It generates synthetic
DataFrame inputs at several sizes, runs representative operators, and prints a
plain-text report that can be pasted into PERFORMANCE_OPTIMIZATION_TASKS.md.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.dataframe_ops.aggregate import group_calc
from core.dataframe_ops.calc import calc_col
from core.dataframe_ops.clean import clean_data
from core.dataframe_ops.filter import filter_data
from core.dataframe_ops.select import get_col_data, sort_data
from core.dataframe_ops.table import concat_rows, left_join

DEFAULT_ROW_COUNTS = (10_000, 100_000, 500_000)


@dataclass
class CaseResult:
    rows: int
    case: str
    elapsed_ms: float
    output_rows: int
    output_cols: int
    output_mb: float

    def as_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "case": self.case,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "output_rows": self.output_rows,
            "output_cols": self.output_cols,
            "output_mb": round(self.output_mb, 6),
        }


def dataframe_mb(df: pd.DataFrame) -> float:
    return float(df.memory_usage(deep=True).sum()) / (1024 * 1024)


def make_dataframe(rows: int) -> pd.DataFrame:
    groups = ["A", "B", "C", "D", "E"]
    regions = ["north", "south", "east", "west"]
    return pd.DataFrame(
        {
            "id": range(rows),
            "group": [groups[i % len(groups)] for i in range(rows)],
            "region": [regions[i % len(regions)] for i in range(rows)],
            "amount": [(i * 17) % 10000 / 10 for i in range(rows)],
            "qty": [(i * 7) % 200 for i in range(rows)],
            "text": [f" item {i % 1000} " for i in range(rows)],
        }
    )


def make_lookup(rows: int) -> pd.DataFrame:
    lookup_rows = max(1, rows // 10)
    return pd.DataFrame(
        {
            "id": range(0, lookup_rows * 10, 10),
            "flag": ["Y" if i % 2 == 0 else "N" for i in range(lookup_rows)],
            "score": [i % 100 for i in range(lookup_rows)],
        }
    )


def time_case(rows: int, name: str, func) -> CaseResult:
    gc.collect()
    started = time.perf_counter()
    output = func()
    elapsed_ms = (time.perf_counter() - started) * 1000
    if isinstance(output, pd.DataFrame):
        output_rows, output_cols = output.shape
        output_mb = dataframe_mb(output)
    else:
        output_rows = output_cols = 0
        output_mb = 0.0
    del output
    gc.collect()
    return CaseResult(rows, name, elapsed_ms, output_rows, output_cols, output_mb)


def run_for_size(rows: int, repeats: int) -> list[CaseResult]:
    df = make_dataframe(rows)
    lookup = make_lookup(rows)
    half = df.iloc[: max(1, rows // 2), :]

    cases = [
        (
            "filter_numeric",
            lambda: filter_data(
                df,
                [{"col": "amount", "op": ">=", "value": "500"}],
                logic="AND",
            ),
        ),
        ("select_columns", lambda: get_col_data(df, ["id", "group", "amount"])),
        (
            "clean_strip_text",
            lambda: clean_data(df, [{"cols": "text", "action": "strip_space"}]),
        ),
        (
            "group_sum",
            lambda: group_calc(df, ["group", "region"], {"amount": "sum", "qty": "mean"}),
        ),
        (
            "calc_formula",
            lambda: calc_col(df, "amount_with_tax", "[amount] * 1.06"),
        ),
        (
            "sort_amount",
            lambda: sort_data(df, [{"col": "amount", "ascending": False}]),
        ),
        (
            "left_join",
            lambda: left_join(df, lookup, "id", "id", ["flag", "score"]),
        ),
        ("concat_rows", lambda: concat_rows(half, half, ignore_index=True)),
    ]

    results = []
    for name, func in cases:
        samples = [time_case(rows, name, func) for _ in range(max(1, repeats))]
        median = statistics.median(sample.elapsed_ms for sample in samples)
        chosen = min(samples, key=lambda sample: abs(sample.elapsed_ms - median))
        chosen.elapsed_ms = median
        results.append(chosen)

    del df, lookup, half
    gc.collect()
    return results


def parse_row_counts(value: str) -> tuple[int, ...]:
    counts = []
    for item in value.split(","):
        text = item.strip().replace("_", "")
        if text:
            counts.append(int(text))
    return tuple(counts) or DEFAULT_ROW_COUNTS


def report_metadata(row_counts: tuple[int, ...], repeats: int) -> dict[str, object]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "row_counts": list(row_counts),
        "repeats": repeats,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "pandas": pd.__version__,
    }


def markdown_report(results: list[CaseResult], metadata: dict[str, object] | None = None) -> str:
    lines = ["# Performance Baseline", ""]
    if metadata:
        lines.extend(
            [
                f"- generated_at: `{metadata.get('generated_at')}`",
                f"- rows: `{', '.join(str(item) for item in metadata.get('row_counts', []))}`",
                f"- repeats: `{metadata.get('repeats')}`",
                f"- python: `{metadata.get('python')}`",
                f"- pandas: `{metadata.get('pandas')}`",
                "",
            ]
        )
    lines.extend(
        [
            "| rows | case | elapsed_ms | output_shape | output_mb |",
            "| ---: | --- | ---: | ---: | ---: |"
        ]
    )
    for item in results:
        shape = f"{item.output_rows}x{item.output_cols}"
        lines.append(
            f"| {item.rows} | {item.case} | {item.elapsed_ms:.1f} | "
            f"{shape} | {item.output_mb:.2f} |"
        )
    return "\n".join(lines)


def json_report(results: list[CaseResult], metadata: dict[str, object]) -> str:
    payload = {
        "metadata": metadata,
        "results": [item.as_dict() for item in results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def csv_report(results: list[CaseResult]) -> str:
    lines = ["rows,case,elapsed_ms,output_rows,output_cols,output_mb"]
    for item in results:
        lines.append(
            f"{item.rows},{item.case},{item.elapsed_ms:.3f},"
            f"{item.output_rows},{item.output_cols},{item.output_mb:.6f}"
        )
    return "\n".join(lines)


def render_report(results: list[CaseResult], metadata: dict[str, object], report_format: str) -> str:
    if report_format == "json":
        return json_report(results, metadata)
    if report_format == "csv":
        return csv_report(results)
    return markdown_report(results, metadata)


def infer_report_format(path: str, explicit_format: str) -> str:
    if explicit_format != "auto":
        return explicit_format
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    return "markdown"


def write_report(path: str, content: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + "\n", encoding="utf-8")


def print_results(results: list[CaseResult], metadata: dict[str, object]) -> None:
    print(markdown_report(results, metadata))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DataFrame performance baselines.")
    parser.add_argument(
        "--rows",
        default=",".join(str(item) for item in DEFAULT_ROW_COUNTS),
        help="Comma-separated row counts. Default: 10000,100000,500000",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Repeat each case and report the median elapsed time.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write a performance report (.md, .json, or .csv).",
    )
    parser.add_argument(
        "--report-format",
        choices=("auto", "markdown", "json", "csv"),
        default="auto",
        help="Report format. Default infers from --report extension.",
    )
    args = parser.parse_args()

    row_counts = parse_row_counts(args.rows)
    all_results = []
    for rows in row_counts:
        all_results.extend(run_for_size(rows, args.repeats))
    metadata = report_metadata(row_counts, args.repeats)
    print_results(all_results, metadata)
    if args.report:
        report_format = infer_report_format(args.report, args.report_format)
        write_report(args.report, render_report(all_results, metadata, report_format))
        print(f"\nReport written to: {args.report}")


if __name__ == "__main__":
    main()
