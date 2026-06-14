"""Datetime parsing helpers for consistent pandas behavior."""

import re

import pandas as pd

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y.%m.%d",
    "%Y年%m月%d日 %H:%M:%S",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)


def parse_datetime_value(value, allow_compact_numeric=False):
    """Parse one date-like value without emitting pandas format inference warnings."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if (
        not allow_compact_numeric
        and re.fullmatch(r"[-+]?\d+(\.\d+)?", text)
        and not re.fullmatch(r"\d{8}|\d{14}", text)
    ):
        return None

    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(text, errors="coerce", format=fmt)
        if not pd.isna(parsed):
            return pd.Timestamp(parsed)

    # Last-resort parser is only used for genuinely irregular values.
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def parse_datetime_series(series):
    """Parse a Series using known formats first to avoid per-element dateutil fallback."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    text = series.astype("string").str.strip()
    remaining = text.notna() & text.ne("")

    for fmt in _DATE_FORMATS:
        if not remaining.any():
            break
        parsed = pd.to_datetime(text.where(remaining), errors="coerce", format=fmt)
        matched = remaining & parsed.notna()
        if matched.any():
            result.loc[matched] = parsed.loc[matched]
            remaining = remaining & ~matched

    if remaining.any():
        fallback = pd.to_datetime(text.where(remaining), errors="coerce")
        matched = remaining & fallback.notna()
        if matched.any():
            result.loc[matched] = fallback.loc[matched]

    return result
