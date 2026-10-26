"""Turn an uploaded CSV / Excel file into a clean, typed DataFrame.

Safeguards:
* extension allowlist plus content sniffing (an .xlsx must really be a zip container)
* size, row and column limits (configured in Settings)
* encoding fallback for CSV, delimiter detection
* no formulas or macros are evaluated: Excel is read as cached values only
"""

from __future__ import annotations

import csv
import io
import re
import warnings
from dataclasses import dataclass, field
from pathlib import PurePath

import numpy as np
import pandas as pd
from openpyxl import load_workbook

CSV_EXT = {".csv", ".tsv", ".txt"}
EXCEL_EXT = {".xlsx", ".xlsm"}
ALLOWED_EXT = CSV_EXT | EXCEL_EXT

NA_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-", "--", "?", "#n/a", "missing"}
DATE_NAME_HINT = re.compile(r"(date|time|day|month|period|created|updated|timestamp|_at$|_on$)", re.I)
ID_NAME_HINT = re.compile(r"(^id$|_id$|^id_|uuid|guid|^code$|_code$|_no$|number$)", re.I)


class IngestError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class IngestInfo:
    file_name: str
    file_type: str
    size_bytes: int
    sheet: str | None = None
    sheets: list[str] = field(default_factory=list)
    delimiter: str | None = None
    encoding: str | None = None
    dropped_empty_rows: int = 0
    dropped_empty_columns: list[str] = field(default_factory=list)
    renamed_columns: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def safe_name(name: str | None) -> str:
    base = PurePath(name or "dataset").name
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip() or "dataset"
    return base[:120]


# ---------------------------------------------------------------- parsing


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise IngestError("bad_encoding", "The file isn't readable text. Save it as UTF-8 CSV and try again.")


def _sniff_delimiter(text: str, ext: str) -> str:
    if ext == ".tsv":
        return "\t"
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        return max(counts, key=counts.get) if max(counts.values()) else ","


def _read_csv(data: bytes, ext: str, max_rows: int, info: IngestInfo) -> pd.DataFrame:
    text, enc = _decode(data)
    if not text.strip():
        raise IngestError("empty_file", "The file is empty.")
    if "\x00" in text[:4096]:
        raise IngestError("binary_file", "This looks like a binary file, not CSV text.")
    delim = _sniff_delimiter(text, ext)
    info.encoding, info.delimiter = enc, delim
    try:
        df = pd.read_csv(
            io.StringIO(text),
            sep=delim,
            dtype=str,
            keep_default_na=False,
            nrows=max_rows + 1,
            skipinitialspace=True,
            on_bad_lines="error",
        )
    except pd.errors.ParserError as exc:
        msg = str(exc).split("\n")[0]
        raise IngestError("parse_error", f"The CSV couldn't be parsed: {msg}") from exc
    except pd.errors.EmptyDataError as exc:
        raise IngestError("empty_file", "The file has no columns or rows.") from exc
    return df


def _read_excel(data: bytes, max_rows: int, sheet: str | None, info: IngestInfo) -> pd.DataFrame:
    if not data.startswith(b"PK"):
        raise IngestError("invalid_excel", "This file isn't a valid .xlsx workbook.")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a variety of errors for corrupt files
        raise IngestError("invalid_excel", "The workbook couldn't be opened. Is it password-protected or corrupt?") from exc
    try:
        names = list(wb.sheetnames)
        info.sheets = names
        if not names:
            raise IngestError("empty_file", "The workbook has no sheets.")
        if sheet:
            if sheet not in names:
                raise IngestError("unknown_sheet", f"Sheet '{sheet}' isn't in this workbook. Sheets: {', '.join(names)}.")
            target = sheet
        else:
            target = next((n for n in names if wb[n].max_row and wb[n].max_row > 1), names[0])
        info.sheet = target
        ws = wb[target]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            raise IngestError("empty_file", f"Sheet '{target}' is empty.")
        body = []
        for i, row in enumerate(rows_iter):
            if i > max_rows:
                break
            body.append(row)
    finally:
        wb.close()
    width = max([len(header)] + [len(r) for r in body]) if body else len(header)
    header = list(header) + [None] * (width - len(header))
    body = [list(r) + [None] * (width - len(r)) for r in body]
    df = pd.DataFrame(body, columns=[("" if h is None else str(h)) for h in header], dtype=object)
    return df


# ---------------------------------------------------------------- cleaning


def _clean_columns(df: pd.DataFrame, info: IngestInfo) -> pd.DataFrame:
    new_cols: list[str] = []
    used: set[str] = set()
    for i, col in enumerate(df.columns):
        orig = str(col)
        name = re.sub(r"\s+", " ", orig).strip()
        if not name or name.lower().startswith("unnamed:") or name.lower() == "nan":
            name = f"column_{i + 1}"
        candidate, k = name, 2
        while candidate.lower() in used:
            candidate = f"{name}_{k}"
            k += 1
        used.add(candidate.lower())
        if candidate != orig:
            info.renamed_columns[orig] = candidate
        new_cols.append(candidate)
    df.columns = new_cols
    return df


def _normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        s = df[col]
        if not (s.dtype == object or pd.api.types.is_string_dtype(s)):
            continue
        non_null = s.dropna()
        if non_null.map(type).eq(str).all():
            # Fast vectorised path (every CSV column, most Excel text columns).
            stripped = s.str.strip()
            mask = stripped.str.lower().isin(NA_TOKENS)
        else:
            stripped = s.map(lambda v: v.strip() if isinstance(v, str) else v)
            mask = stripped.map(lambda v: isinstance(v, str) and v.lower() in NA_TOKENS)
        df[col] = stripped.mask(mask.fillna(False).astype(bool), np.nan)
    return df


EU_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")
US_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+$")


def _decimal_separator(values: pd.Series, delimiter: str | None) -> str:
    """Decide whether a column of numeric-looking strings uses '.' or ',' as the decimal mark.

    Rules, in order: when a value contains both marks, the one that comes last is the decimal
    mark; '1,234'-style values are thousands in a comma-delimited file; anything else with a
    comma and no dot ('99,50') uses a decimal comma.
    """
    both = values[values.str.contains(".", regex=False) & values.str.contains(",", regex=False)]
    if len(both):
        last_comma = (both.str.rfind(",") > both.str.rfind(".")).mean()
        return "," if last_comma > 0.5 else "."
    comma_only = values[values.str.contains(",", regex=False)]
    if len(comma_only):
        if delimiter != ";" and comma_only.str.match(US_THOUSANDS).all():
            return "."
        return ","
    dot_only = values[values.str.contains(".", regex=False)]
    if delimiter == ";" and len(dot_only) and dot_only.str.match(EU_THOUSANDS).all():
        return ","
    return "."


def _try_numeric(s: pd.Series, delimiter: str | None = None) -> tuple[pd.Series, str] | None:
    non_null = s.dropna()
    if non_null.empty:
        return None
    if all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in non_null.head(200)):
        out = pd.to_numeric(s, errors="coerce")
        return (out, ".") if out.notna().sum() >= 0.95 * len(non_null) else None
    # Cheap early exit: if a sample clearly isn't numeric, skip the full-column work.
    sample = non_null.sample(n=min(500, len(non_null)), random_state=0).astype(str)
    sample = sample.str.replace(r"[\s$€£₹¥%()]", "", regex=True)
    if sample.str.match(r"^[-+]?[\d.,]+(e[-+]?\d+)?$", case=False).mean() < 0.9:
        return None
    # Fast path: plain numbers ("12", "3.5", "-1e3") parse directly in C.
    # Skipped for semicolon files, where "1.000" usually means one thousand.
    direct = pd.to_numeric(non_null, errors="coerce") if delimiter != ";" else None
    if direct is not None and direct.notna().all():
        out = pd.Series(np.nan, index=s.index, dtype=float)
        out.loc[non_null.index] = direct.astype(float)
        if (out.dropna() % 1 == 0).all():
            return out.astype("Int64"), "."
        return out, "."
    as_str = non_null.astype(str)
    cleaned = as_str.str.replace(r"[\s$€£₹¥]", "", regex=True).str.rstrip("%")
    # Accounting negatives: (123.45)
    cleaned = cleaned.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    if not cleaned.str.match(r"^[-+]?[\d.,]+(e[-+]?\d+)?$", case=False).mean() >= 0.95:
        return None
    decimal = _decimal_separator(cleaned, delimiter)
    if decimal == ",":
        cleaned = cleaned.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        cleaned = cleaned.str.replace(",", "", regex=False)
    parsed = pd.to_numeric(cleaned, errors="coerce")
    if parsed.notna().sum() < 0.95 * len(non_null):
        return None
    out = pd.Series(np.nan, index=s.index, dtype=float)
    out.loc[non_null.index] = parsed
    if (out.dropna() % 1 == 0).all():
        return out.astype("Int64"), decimal
    return out, decimal


def _looks_like_dates(sample: pd.Series) -> bool:
    s = sample.astype(str).head(50)
    pattern = r"(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})|(?:[A-Za-z]{3,9}\.? \d{1,2},? \d{2,4})|(?:\d{1,2} [A-Za-z]{3,9} \d{2,4})"
    return s.str.contains(pattern, regex=True).mean() > 0.8


DMY = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")


def _day_first(values: pd.Series, delimiter: str | None) -> tuple[bool, bool]:
    """Return (dayfirst, ambiguous) for dates written like 03/04/2025."""
    parts = values.astype(str).str.extract(DMY).dropna()
    if parts.empty:
        return False, False
    first, second = parts[0].astype(int), parts[1].astype(int)
    if (first > 12).any():
        return True, False
    if (second > 12).any():
        return False, False
    return delimiter == ";", True


def _try_datetime(name: str, s: pd.Series, delimiter: str | None = None) -> tuple[pd.Series, str | None] | None:
    non_null = s.dropna()
    if non_null.empty:
        return None
    if pd.api.types.is_datetime64_any_dtype(s):
        return s, None
    if all(isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "year") for v in non_null.head(200)):
        out = pd.to_datetime(s, errors="coerce")
        return (out, None) if out.notna().sum() >= 0.9 * len(non_null) else None
    if not (DATE_NAME_HINT.search(name) or _looks_like_dates(non_null)):
        return None
    as_str = s.where(s.isna(), s.astype(str))
    dayfirst, ambiguous = _day_first(non_null.head(5000), delimiter)
    note = None
    if ambiguous:
        order = "day/month/year" if dayfirst else "month/day/year"
        note = f"Dates in {name} could be read either way (e.g. 03/04); they were read as {order}."
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        attempts = [{"format": "ISO8601"}, {"format": "mixed", "dayfirst": dayfirst}]
        for kwargs in attempts:
            try:
                out = pd.to_datetime(as_str, errors="coerce", **kwargs)
            except (ValueError, TypeError):
                continue
            if out.notna().sum() >= 0.9 * len(non_null):
                return out, (note if kwargs.get("format") == "mixed" else None)
    return None


def infer_types(df: pd.DataFrame, info: IngestInfo) -> pd.DataFrame:
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_bool_dtype(s) or pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        non_null = s.dropna()
        if not non_null.empty and all(isinstance(v, bool) for v in non_null.head(200)):
            df[col] = s.astype("boolean")
            continue
        lowered = non_null.astype(str).str.lower()
        if not non_null.empty and lowered.isin(["true", "false"]).all():
            df[col] = s.map(lambda v: None if pd.isna(v) else str(v).lower() == "true").astype("boolean")
            continue
        num = _try_numeric(s, info.delimiter)
        if num is not None:
            df[col] = num[0]
            if num[1] == ",":
                info.notes.append(f"Read {col} with a comma as the decimal mark (e.g. 1.234,50 = 1234.50).")
            continue
        dt = _try_datetime(col, s, info.delimiter)
        if dt is not None:
            df[col] = dt[0]
            if dt[1]:
                info.notes.append(dt[1])
            continue
        df[col] = s.map(lambda v: v if pd.isna(v) else str(v)).astype(object)
    return df


def semantic_type(name: str, s: pd.Series, n_rows: int) -> str:
    """One of: numeric, datetime, boolean, categorical, text, identifier."""
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    nunique = s.nunique(dropna=True)
    non_null = s.notna().sum()
    unique_ratio = nunique / non_null if non_null else 0
    if pd.api.types.is_numeric_dtype(s):
        if ID_NAME_HINT.search(name) and unique_ratio > 0.95 and n_rows > 20:
            return "identifier"
        return "numeric"
    if n_rows > 20 and unique_ratio > 0.95 and (ID_NAME_HINT.search(name) or s.dropna().astype(str).str.len().median() < 40):
        return "identifier"
    if nunique <= max(30, int(0.05 * n_rows)):
        return "categorical"
    return "text"


# ---------------------------------------------------------------- entry point


def load_dataframe(
    file_name: str,
    data: bytes,
    *,
    max_rows: int,
    max_columns: int,
    sheet: str | None = None,
) -> tuple[pd.DataFrame, IngestInfo]:
    name = safe_name(file_name)
    ext = PurePath(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        if ext == ".xls":
            raise IngestError("unsupported_type", "Old .xls workbooks aren't supported. Save as .xlsx or CSV.")
        raise IngestError("unsupported_type", "Upload a CSV, TSV or Excel (.xlsx) file.")
    if not data:
        raise IngestError("empty_file", "The file is empty.")

    info = IngestInfo(file_name=name, file_type="excel" if ext in EXCEL_EXT else "csv", size_bytes=len(data))
    df = _read_excel(data, max_rows, sheet, info) if ext in EXCEL_EXT else _read_csv(data, ext, max_rows, info)

    if len(df) > max_rows:
        raise IngestError("too_many_rows", f"The file has more than {max_rows:,} rows. Filter it down or raise MAX_ROWS.", 413)
    if df.shape[1] > max_columns:
        raise IngestError("too_many_columns", f"The file has {df.shape[1]} columns; the limit is {max_columns}.", 413)

    df = _clean_columns(df, info)
    df = _normalize_missing(df)

    empty_rows = df.isna().all(axis=1)
    info.dropped_empty_rows = int(empty_rows.sum())
    df = df.loc[~empty_rows].reset_index(drop=True)

    empty_cols = [c for c in df.columns if df[c].isna().all() and c.startswith("column_")]
    if empty_cols:
        info.dropped_empty_columns = empty_cols
        df = df.drop(columns=empty_cols)

    if df.empty or df.shape[1] == 0:
        raise IngestError("no_data", "The file has a header but no data rows.")

    df = infer_types(df, info)
    if info.dropped_empty_rows:
        info.notes.append(f"Removed {info.dropped_empty_rows:,} completely empty rows.")
    if info.dropped_empty_columns:
        info.notes.append(f"Removed {len(info.dropped_empty_columns)} empty unnamed columns.")
    if info.renamed_columns:
        info.notes.append(f"Renamed {len(info.renamed_columns)} blank or duplicate column headers.")
    return df, info
