import io

import pandas as pd
import pytest

from app.ingest import IngestError, load_dataframe

LIMITS = {"max_rows": 1000, "max_columns": 50}


def test_csv_types_and_currency():
    data = b"Order Date,Region,Amount,Active\n2025-01-03,West,\"$1,200.50\",true\n2025-01-04,East,$99,false\n2025-01-05,East,N/A,true\n"
    df, info = load_dataframe("orders.csv", data, **LIMITS)
    assert str(df["Order Date"].dtype).startswith("datetime64")
    assert df["Amount"].tolist()[:2] == [1200.5, 99.0]
    assert pd.isna(df["Amount"].iloc[2])
    assert str(df["Active"].dtype) == "boolean"
    assert info.delimiter == ","


def test_semicolon_and_duplicate_headers():
    data = "a;a;;b\n1;2;;x\n3;4;;y\n".encode()
    df, info = load_dataframe("x.csv", data, **LIMITS)
    assert len(set(df.columns)) == len(df.columns)
    assert info.delimiter == ";"


def test_excel_roundtrip():
    buf = io.BytesIO()
    pd.DataFrame({"city": ["Pune", "Belagavi"], "sales": [10, 20]}).to_excel(buf, index=False, sheet_name="Data")
    df, info = load_dataframe("book.xlsx", buf.getvalue(), **LIMITS)
    assert info.sheet == "Data" and info.sheets == ["Data"]
    assert df["sales"].sum() == 30


def test_fake_excel_rejected():
    with pytest.raises(IngestError) as exc:
        load_dataframe("evil.xlsx", b"not a zip", **LIMITS)
    assert exc.value.code == "invalid_excel"


@pytest.mark.parametrize("name", ["data.exe", "data.json", "data.xls"])
def test_unsupported_types(name):
    with pytest.raises(IngestError) as exc:
        load_dataframe(name, b"a,b\n1,2\n", **LIMITS)
    assert exc.value.code == "unsupported_type"


def test_empty_and_header_only():
    with pytest.raises(IngestError):
        load_dataframe("e.csv", b"", **LIMITS)
    with pytest.raises(IngestError) as exc:
        load_dataframe("h.csv", b"a,b,c\n", **LIMITS)
    assert exc.value.code in ("no_data", "empty_file")


def test_row_limit():
    data = ("x\n" + "1\n" * 20).encode()
    with pytest.raises(IngestError) as exc:
        load_dataframe("big.csv", data, max_rows=10, max_columns=5)
    assert exc.value.code == "too_many_rows"


def test_malformed_csv_reported():
    with pytest.raises(IngestError) as exc:
        load_dataframe("bad.csv", b"a,b\n1,2\n3,4,5,6\n", **LIMITS)
    assert exc.value.code == "parse_error"


def test_filename_sanitized():
    df, info = load_dataframe("../../etc/pass wd.csv", b"a\n1\n", **LIMITS)
    assert "/" not in info.file_name and ".." not in info.file_name.replace(".csv", "")


def test_european_decimal_comma():
    data = b"date;amount;qty\n15/02/2025;1.234,50;1.000\n16/02/2025;99,00;2.500\n"
    df, info = load_dataframe("eu.csv", data, **LIMITS)
    assert df["amount"].tolist() == [1234.5, 99.0]
    assert df["qty"].tolist() == [1000, 2500]
    assert df["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-02-15", "2025-02-16"]
    assert any("decimal mark" in n for n in info.notes)


def test_us_thousands_separator():
    df, _ = load_dataframe("us.csv", b'amount,price\n"1,234",1.50\n"12,000",2.25\n', **LIMITS)
    assert df["amount"].tolist() == [1234, 12000]
    assert df["price"].tolist() == [1.5, 2.25]


def test_ambiguous_dates_are_flagged():
    df, info = load_dataframe("d.csv", b"day,v\n03/04/2025,1\n05/06/2025,2\n", **LIMITS)
    assert df["day"].dt.month.tolist() == [3, 5]
    assert any("could be read either way" in n for n in info.notes)


def test_day_first_detected_from_values():
    df, info = load_dataframe("d.csv", b"day,v\n03/04/2025,1\n25/06/2025,2\n", **LIMITS)
    assert df["day"].dt.strftime("%Y-%m-%d").tolist() == ["2025-04-03", "2025-06-25"]
    assert not any("either way" in n for n in info.notes)


def test_text_with_digits_stays_text():
    df, _ = load_dataframe("t.csv", b"code,v\nA-12,1\nB-7,2\n2025-01-01x,3\n", **LIMITS)
    assert df["code"].dtype == object
