"""Read resistivity soundings from CSV/XLSX tables, deterministically.

The agent looks at a preview of the table, names the columns and rows that hold the readings,
and this module extracts the numbers; values are never transcribed by the model.
"""

import csv
import io
import re

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PREVIEW_ROWS = 40
MAX_ROWS = 2000
NUMBER = re.compile(r"^[+-]?(\d+([.,]\d+)?|\d{1,3}([.,]\d{3})+([.,]\d+)?)$")


def read_table(data: bytes, mime_type: str) -> list[dict]:
    """Sheets as {"name", "rows": [[cell text]]}; a CSV is one sheet."""
    if mime_type == "text/csv":
        text = data.decode("utf-8-sig")
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
        except csv.Error:
            sample = text[:4096]
            delimiter = max(";,\t", key=sample.count)
        return [{"name": "csv", "rows": list(csv.reader(io.StringIO(text), delimiter=delimiter))[:MAX_ROWS]}]
    if mime_type == XLSX_MIME:
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheets = []
        for sheet in workbook.worksheets:
            rows = []
            for values in sheet.iter_rows(values_only=True):
                rows.append(["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                             for v in values])
                if len(rows) >= MAX_ROWS:
                    break
            sheets.append({"name": sheet.title, "rows": rows})
        workbook.close()
        return sheets
    raise ValueError("Only CSV and XLSX files hold measurement tables")


def preview(sheets: list[dict]) -> list[dict]:
    """First rows of each sheet with 1-based row numbers and column letters, for the agent."""
    result = []
    for sheet in sheets:
        width = max((len(r) for r in sheet["rows"][:PREVIEW_ROWS]), default=0)
        result.append({"sheet": sheet["name"], "total_rows": len(sheet["rows"]),
                       "columns": [column_letter(i) for i in range(width)],
                       "rows": [{"row": n, "cells": r} for n, r in enumerate(sheet["rows"][:PREVIEW_ROWS], start=1)]})
    return result


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def column_index(letter: str) -> int:
    value = 0
    for char in letter.strip().upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Invalid column: {letter}")
        value = value * 26 + ord(char) - 64
    return value - 1


def parse_number(text: str, decimal: str = "auto") -> float | None:
    """A number written with comma or point decimals; thousands separators need `decimal`."""
    cleaned = str(text).strip().replace(" ", "").replace(" ", "")
    if not cleaned or not NUMBER.match(cleaned):
        return None
    if decimal == ",":
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif decimal == ".":
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." in cleaned:
        return None  # ambiguous without knowing the decimal separator
    else:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def extract(sheets: list[dict], *, sheet: str | None, spacing_column: str, value_column: str,
            first_row: int, last_row: int, potential_column: str | None = None,
            decimal: str = "auto") -> dict:
    """Readings from the given columns and rows; rows without numbers are reported, not guessed."""
    table = next((s for s in sheets if sheet in (None, s["name"])), None)
    if table is None:
        raise ValueError(f"Sheet not found: {sheet}")
    if not 1 <= first_row <= last_row <= len(table["rows"]):
        raise ValueError(f"Rows must be within 1..{len(table['rows'])}")
    columns = [column_index(spacing_column), column_index(value_column)]
    if potential_column:
        columns.append(column_index(potential_column))
    readings, skipped = [], []
    for number in range(first_row, last_row + 1):
        cells = table["rows"][number - 1]
        values = [parse_number(cells[c], decimal) if c < len(cells) else None for c in columns]
        if any(v is None for v in values):
            skipped.append({"row": number, "cells": [cells[c] if c < len(cells) else "" for c in columns]})
            continue
        reading = {"spacing_m": values[0], "value": values[1], "locator": f"{table['name']}!{number}"}
        if potential_column:
            reading["potential_spacing_m"] = values[2]
        readings.append(reading)
    return {"sheet": table["name"], "readings": readings, "skipped_rows": skipped}
