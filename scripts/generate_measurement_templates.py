"""Generate the soil-resistivity field templates seeded into the MinIO `plantillas` bucket.

One XLSX (instructions, site data and a reading table with the apparent-resistivity formula)
and one CSV per method, plus `catalogo.json`, which the API reads to list them. The reading
tables keep a single header row and numeric columns so `measurement_tables` can extract them
when the filled file is uploaded to a project.

    python scripts/generate_measurement_templates.py   # writes resources/minio/plantillas-medicion/

Requires openpyxl (a backend dependency).
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

OUTPUT = Path(__file__).resolve().parents[1] / "resources" / "minio" / "plantillas-medicion"
CATALOG_VERSION = 1
FIXED_DATE = datetime(2026, 1, 1)
DATA_ROWS = 20

SITE_FIELDS = [
    ("Proyecto", ""),
    ("Identificador del sondeo", "SEV-1"),
    ("Fecha de medición (AAAA-MM-DD)", ""),
    ("Ubicación / coordenadas", ""),
    ("Dirección del perfil (p. ej. N-S)", ""),
    ("Equipo (marca, modelo, serie)", ""),
    ("Fecha de última calibración", ""),
    ("Responsable de la medición", ""),
    ("Condición del suelo (seco / húmedo / saturado)", ""),
    ("Clima y días desde la última lluvia", ""),
]

# Each column: (header, csv name, width, formula template or None). `{r}` is the row number.
METHODS = [
    {
        "id": "wenner",
        "method": "wenner",
        "title": "Método de Wenner",
        "description": "Cuatro electrodos equiespaciados a una distancia a. Lectura de resistencia R por espaciamiento.",
        "formula": "ρa = 2·π·a·R",
        "columns": [
            ("Lectura", "lectura", 9, None),
            ("Espaciamiento a (m)", "espaciamiento_a_m", 20, None),
            ("Profundidad de electrodos b (m)", "profundidad_electrodo_m", 22, None),
            ("Resistencia medida R (Ω)", "resistencia_ohm", 22, None),
            ("Resistividad aparente ρa (Ω·m)", "resistividad_aparente_ohm_m", 26,
             '=IF(AND(ISNUMBER(B{r}),ISNUMBER(D{r})),2*PI()*B{r}*D{r},"")'),
            ("Observaciones", "observaciones", 34, None),
        ],
        "suggested": {1: [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]},
        "steps": [
            "Clava los cuatro electrodos en línea recta con la misma separación a entre ellos.",
            "La profundidad b de los electrodos no debe superar a/20.",
            "Inyecta corriente por los electrodos externos (C1, C2) y mide el potencial en los internos (P1, P2).",
            "Registra la resistencia R que indica el telurómetro para cada espaciamiento.",
            "Repite el perfil en al menos dos direcciones perpendiculares (usa una hoja o archivo por dirección).",
        ],
    },
    {
        "id": "schlumberger",
        "method": "schlumberger",
        "title": "Método de Schlumberger",
        "description": "Electrodos de potencial fijos (MN) y de corriente que se alejan (AB/2). Útil para sondeos profundos.",
        "formula": "ρa = π·R·((AB/2)² − (MN/2)²) / MN",
        "columns": [
            ("Lectura", "lectura", 9, None),
            ("AB/2 (m)", "ab_medios_m", 14, None),
            ("MN (m)", "mn_m", 12, None),
            ("Resistencia medida R (Ω)", "resistencia_ohm", 22, None),
            ("Factor geométrico K (m)", "factor_k_m", 22,
             '=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r}),C{r}>0),PI()*(B{r}^2-(C{r}/2)^2)/C{r},"")'),
            ("Resistividad aparente ρa (Ω·m)", "resistividad_aparente_ohm_m", 26,
             '=IF(AND(ISNUMBER(E{r}),ISNUMBER(D{r})),E{r}*D{r},"")'),
            ("Observaciones", "observaciones", 34, None),
        ],
        "suggested": {1: [1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 30, 40], 2: [0.5] * 8 + [2] * 4},
        "steps": [
            "Coloca los electrodos de potencial M y N simétricos respecto al centro, separados una distancia MN.",
            "Aleja los electrodos de corriente A y B simétricamente; AB/2 es la distancia del centro a cada uno.",
            "Mantén MN/2 menor que AB/2 / 5; cuando la señal sea débil, aumenta MN y repite una lectura de empalme.",
            "Registra AB/2, MN y la resistencia R en cada posición.",
        ],
    },
    {
        "id": "tres-puntos",
        "method": "three_point",
        "title": "Tres puntos (caída de potencial con varilla)",
        "description": "Varilla de prueba hincada a distintas longitudes; la resistencia se mide por caída de potencial.",
        "formula": "ρa = 2·π·L·R / (ln(8·L/d) − 1)",
        "columns": [
            ("Lectura", "lectura", 9, None),
            ("Longitud enterrada L (m)", "longitud_enterrada_m", 22, None),
            ("Diámetro de la varilla d (m)", "diametro_varilla_m", 22, None),
            ("Distancia al electrodo de corriente C (m)", "distancia_corriente_m", 26, None),
            ("Distancia al electrodo de potencial P (m)", "distancia_potencial_m", 26, None),
            ("Resistencia medida R (Ω)", "resistencia_ohm", 22, None),
            ("Resistividad aparente ρa (Ω·m)", "resistividad_aparente_ohm_m", 26,
             '=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r}),ISNUMBER(F{r}),C{r}>0),2*PI()*B{r}*F{r}/(LN(8*B{r}/C{r})-1),"")'),
            ("Observaciones", "observaciones", 34, None),
        ],
        "suggested": {1: [0.5, 1, 1.5, 2, 2.4, 3], 2: [0.0159] * 6},
        "steps": [
            "Hinca la varilla de prueba hasta la longitud L y anota su diámetro d.",
            "Ubica el electrodo de corriente a una distancia C de al menos 5 veces L.",
            "Ubica el electrodo de potencial al 61,8 % de C (P ≈ 0,618·C) y mide la resistencia R.",
            "Profundiza la varilla y repite; la variación de ρa con L muestra la estratificación.",
        ],
    },
    {
        "id": "polo-dipolo",
        "method": "pole_dipole",
        "title": "Polo–dipolo",
        "description": "Un electrodo de corriente remoto y un dipolo de potencial de longitud a a n·a del polo.",
        "formula": "ρa = 2·π·a·n·(n + 1)·R",
        "columns": [
            ("Lectura", "lectura", 9, None),
            ("Longitud del dipolo a (m)", "dipolo_a_m", 22, None),
            ("Factor de separación n", "factor_n", 20, None),
            ("Resistencia medida R (Ω)", "resistencia_ohm", 22, None),
            ("Resistividad aparente ρa (Ω·m)", "resistividad_aparente_ohm_m", 26,
             '=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r}),ISNUMBER(D{r})),2*PI()*B{r}*C{r}*(C{r}+1)*D{r},"")'),
            ("Observaciones", "observaciones", 34, None),
        ],
        "suggested": {2: [1, 2, 3, 4, 5, 6]},
        "steps": [
            "Ubica el electrodo de corriente remoto a más de 10 veces la máxima apertura n·a.",
            "Coloca el polo de corriente A y el dipolo de potencial MN de longitud a.",
            "Para cada factor n, separa el dipolo n·a del polo y registra la resistencia R.",
        ],
    },
]

GENERAL_NOTES = [
    "Registra los valores con punto o coma decimal, sin unidades dentro de la celda.",
    "Deja vacías las filas que no uses; no borres la fila de encabezados de la tabla.",
    "Anota en Observaciones lecturas dudosas (tuberías, cercas o estructuras metálicas cercanas).",
    "Al terminar, carga el archivo en «Archivos del proyecto» para que el agente extraiga las lecturas.",
]

HEADER_FILL = PatternFill("solid", fgColor="1F4E46")
FORMULA_FILL = PatternFill("solid", fgColor="E8F1EE")
INPUT_FILL = PatternFill("solid", fgColor="FFFBEA")
THIN = Side(style="thin", color="B7C4BF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def workbook(spec: dict) -> bytes:
    book = Workbook()
    book.properties.creator = "Allectricity Workspace"
    book.properties.title = f"Plantilla de resistividad — {spec['title']}"
    book.properties.created = book.properties.modified = FIXED_DATE

    guide = book.active
    guide.title = "Instrucciones"
    guide.column_dimensions["A"].width = 110
    guide["A1"] = f"Plantilla de medición de resistividad — {spec['title']}"
    guide["A1"].font = Font(bold=True, size=14, color="1F4E46")
    guide["A2"] = spec["description"]
    guide["A4"] = f"Fórmula usada: {spec['formula']}"
    guide["A4"].font = Font(bold=True)
    row = 6
    guide.cell(row, 1, "Procedimiento").font = Font(bold=True)
    for number, step in enumerate(spec["steps"], start=1):
        row += 1
        guide.cell(row, 1, f"{number}. {step}")
    row += 2
    guide.cell(row, 1, "Cómo diligenciar").font = Font(bold=True)
    for note in GENERAL_NOTES:
        row += 1
        guide.cell(row, 1, f"• {note}")
    row += 2
    guide.cell(row, 1, "Referencia: IEEE Std 81-2012, mediciones de resistividad del terreno.").font = Font(italic=True)
    for cells in guide.iter_rows(min_row=1, max_row=row):
        cells[0].alignment = Alignment(wrap_text=True, vertical="top")

    data = book.create_sheet("Mediciones")
    data["A1"] = f"Sondeo de resistividad — {spec['title']}"
    data["A1"].font = Font(bold=True, size=13, color="1F4E46")
    for offset, (label, value) in enumerate(SITE_FIELDS, start=3):
        data.cell(offset, 1, label).font = Font(bold=True)
        data.merge_cells(start_row=offset, start_column=1, end_row=offset, end_column=2)
        target = data.cell(offset, 3, value)
        target.fill = INPUT_FILL
        target.border = BOX
        data.merge_cells(start_row=offset, start_column=3, end_row=offset, end_column=5)
    data.cell(3 + len(SITE_FIELDS), 1, f"Método: {spec['method']} · {spec['formula']}").font = Font(italic=True)

    header_row = 3 + len(SITE_FIELDS) + 2
    for column, (header, _, width, _) in enumerate(spec["columns"], start=1):
        cell = data.cell(header_row, column, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        cell.border = BOX
        letter = cell.column_letter
        data.column_dimensions[letter].width = max(width, data.column_dimensions[letter].width or 0)
    data.row_dimensions[header_row].height = 34

    positive = DataValidation(type="decimal", operator="greaterThan", formula1="0", allow_blank=True,
                              showErrorMessage=True, errorTitle="Valor inválido",
                              error="Ingresa un número mayor que cero.")
    data.add_data_validation(positive)
    first, last = header_row + 1, header_row + DATA_ROWS
    for row in range(first, last + 1):
        reading = row - header_row
        for column, (_, _, _, formula) in enumerate(spec["columns"], start=1):
            cell = data.cell(row, column)
            cell.border = BOX
            if column == 1:
                cell.value = reading
            elif formula:
                cell.value = formula.format(r=row)
                cell.fill = FORMULA_FILL
                cell.number_format = "0.00"
            elif column < len(spec["columns"]):
                cell.fill = INPUT_FILL
                suggested = spec["suggested"].get(column - 1, [])
                if reading <= len(suggested):
                    cell.value = suggested[reading - 1]
                positive.add(cell)
    data.freeze_panes = data.cell(header_row + 1, 1)
    book.active = 1

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def csv_template(spec: dict) -> bytes:
    """Semicolon-separated (opens as columns in Spanish-locale Excel); no formulas."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    columns = spec["columns"]
    writer.writerow([name for _, name, _, _ in columns])
    for reading in range(1, DATA_ROWS + 1):
        row = []
        for index, (_, _, _, formula) in enumerate(columns):
            suggested = spec["suggested"].get(index, [])
            if index == 0:
                row.append(reading)
            elif not formula and reading <= len(suggested):
                row.append(str(suggested[reading - 1]).replace(".", ","))
            else:
                row.append("")
        writer.writerow(row)
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    catalog = {"version": CATALOG_VERSION, "templates": []}
    for spec in METHODS:
        base = f"plantilla_resistividad_{spec['id'].replace('-', '_')}"
        files = []
        for fmt, content in (("xlsx", workbook(spec)), ("csv", csv_template(spec))):
            key = f"{spec['id']}/{base}.{fmt}"
            (OUTPUT / spec["id"]).mkdir(exist_ok=True)
            (OUTPUT / key).write_bytes(content)
            files.append({"format": fmt, "key": key, "filename": f"{base}.{fmt}", "size_bytes": len(content)})
        catalog["templates"].append({
            "id": spec["id"], "method": spec["method"], "title": spec["title"],
            "description": spec["description"], "formula": spec["formula"], "files": files,
        })
    (OUTPUT / "catalogo.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    print(f"Plantillas escritas en {OUTPUT}")


if __name__ == "__main__":
    main()
