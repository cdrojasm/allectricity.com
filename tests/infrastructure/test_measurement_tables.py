import io

from src.infrastructure.processing.measurement_tables import XLSX_MIME, extract, parse_number, preview, read_table


def test_csv_with_semicolons_and_comma_decimals():
    data = "Ensayo Wenner;;\nSeparación a (m);Resistividad (Ω·m);Nota\n1;136,5;\n2;120,1;\n4;n/d;repetir\n8;98,25;\n".encode()
    sheets = read_table(data, "text/csv")
    assert preview(sheets)[0]["rows"][1]["cells"][0] == "Separación a (m)"
    result = extract(sheets, sheet=None, spacing_column="A", value_column="B", first_row=3, last_row=6)
    assert [(r["spacing_m"], r["value"]) for r in result["readings"]] == [(1, 136.5), (2, 120.1), (8, 98.25)]
    assert result["skipped_rows"] == [{"row": 5, "cells": ["4", "n/d"]}]
    assert parse_number("1.250,5") is None and parse_number("1.250,5", ",") == 1250.5


def test_xlsx_sheet_and_columns():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sondeo"
    sheet.append(["AB/2", "MN", "R (ohm)"])
    for row in ([10, 2, 1.5], [20, 2, 0.4], [40, 4, 0.15], [80, 4, 0.05]):
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    sheets = read_table(buffer.getvalue(), XLSX_MIME)
    result = extract(sheets, sheet="Sondeo", spacing_column="A", value_column="C", potential_column="B",
                     first_row=2, last_row=5)
    assert result["readings"][0] == {"spacing_m": 10, "value": 1.5, "locator": "Sondeo!2", "potential_spacing_m": 2}
