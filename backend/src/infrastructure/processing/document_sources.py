"""Parseo documental que conserva el origen de cada pasaje (EG-04, EG-09).

PDF por página (texto nativo, tablas por fila y celda, y OCR de páginas escaneadas o
vectoriales rasterizadas), CSV por fila y celda, XLSX por hoja,
fila y celda, DOCX por párrafo y fila de tabla, e imágenes por línea OCR con región.
Los fallos parciales por página quedan registrados en `coverage` y el documento no se
presenta como completo.
"""

import base64
import csv
import io
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.domain.knowledge_graph.source import Segment, SourceDocument

PARSER_VERSION = "doc-sources/2"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DXF_MIME = "application/dxf"
MIN_PAGE_TEXT = 20


class OCRUnavailable(RuntimeError):
    """El servicio OCR no respondió; la tarea puede reintentarse."""


class _Builder:
    def __init__(self):
        self.parts, self.segments, self.length = [], [], 0

    def add(self, segment_id, text, locator, **extra):
        text = text.strip("\n")
        if not text.strip():
            return
        if self.parts:
            self.parts.append("\n")
            self.length += 1
        start = self.length
        self.parts.append(text)
        self.length += len(text)
        self.segments.append(Segment(segment_id, start, self.length, locator, **extra))

    def build(self, mime_type, coverage, ocr=None):
        return SourceDocument("".join(self.parts), self.segments, mime_type, PARSER_VERSION,
                              coverage, ocr or {})


def _row(builder, segment_id, values, locator, reference):
    """Una fila tabular con spans por celda, unida con « | »."""
    text, cells = "", []
    for column, value in values:
        if value is None or str(value).strip() == "":
            continue
        if text:
            text += " | "
        cell_start = len(text)
        text += str(value).strip()
        cells.append((cell_start, len(text), reference(column)))
    builder.add(segment_id, text, locator, cells=tuple(cells))


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def ocr_image(data: bytes) -> dict:
    endpoint = os.getenv("OCR_SERVICE_URL", "http://ocr:8080").rstrip("/") + "/v1/ocr"
    headers = {"Content-Type": "application/json"}
    if os.getenv("OCR_INTERNAL_API_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['OCR_INTERNAL_API_TOKEN']}"
    request = Request(
        endpoint,
        data=json.dumps({"image_base64": base64.b64encode(data).decode("ascii"),
                         "language": "eng+spa"}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        if exc.code in {400, 413, 415}:
            raise ValueError(f"OCR rechazó la imagen ({exc.code})") from exc
        raise OCRUnavailable(f"OCR respondió {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise OCRUnavailable("No se pudo contactar el servicio OCR") from exc


def _add_ocr(builder, result, page, prefix):
    """Agrega líneas OCR como segmentos con región; tolera respuestas sin `lines`."""
    lines = result.get("lines")
    if not lines:
        builder.add(f"{prefix}l1", result.get("text", ""), {"page": page},
                    quality=result.get("mean_confidence"),
                    needs_review=result.get("needs_review", False))
        return
    for number, line in enumerate(lines, start=1):
        builder.add(f"{prefix}l{number}", line["text"], {"page": page},
                    quality=line.get("confidence"),
                    needs_review=result.get("needs_review", False),
                    region=tuple(line["bbox"]) if line.get("bbox") else None)


def _summarize_ocr(results: list) -> dict:
    if not results:
        return {}
    words = sum(r.get("word_count", 0) for r in results)
    weight = words or len(results)
    mean = sum(r.get("mean_confidence", 0) * (r.get("word_count", 0) if words else 1)
               for r in results) / weight
    low = sum(r.get("low_confidence_ratio", 1) * (r.get("word_count", 0) if words else 1)
              for r in results) / weight
    return {"mean_confidence": round(mean, 2), "low_confidence_ratio": round(low, 3),
            "word_count": words, "needs_review": any(r.get("needs_review") for r in results)}


def _page_image(page):
    """La imagen más grande de una página (típico de un PDF escaneado), como PNG."""
    images = list(page.images)
    if not images:
        return None
    largest = max(images, key=lambda image: len(image.data))
    if largest.data[:3] == b"\xff\xd8\xff" or largest.data[:8] == b"\x89PNG\r\n\x1a\n":
        return largest.data
    buffer = io.BytesIO()
    largest.image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _has_marks(page) -> bool:
    """Una página sin imágenes ni operadores de dibujo está en blanco y no merece OCR."""
    if list(page.images):
        return True
    contents = page.get_contents()
    return contents is not None and bool(contents.get_data().strip())


class _PdfRaster:
    """Rasteriza páginas completas con PDFium: cubre escaneos y PDF vectoriales sin imagen
    embebida (texto convertido a curvas, planos). Si PDFium falla se usa la imagen embebida."""

    def __init__(self, data: bytes):
        self.data, self.document = data, None
        self.dpi = int(os.getenv("PDF_OCR_DPI", "200"))

    def page(self, index: int, page) -> bytes:
        try:
            import pypdfium2

            if self.document is None:
                self.document = pypdfium2.PdfDocument(self.data)
            bitmap = self.document[index].render(scale=self.dpi / 72, grayscale=True)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception:
            image = _page_image(page)
            if image is None:
                raise
            return image

    def close(self):
        if self.document is not None:
            self.document.close()


def _pdf_tables(plumber_page) -> tuple[str, list]:
    """Tablas con líneas de una página (pdfplumber) y el texto que queda fuera de ellas."""
    tables = [table for table in plumber_page.find_tables()
              if any(any(cell for cell in row) for row in table.extract())]
    if not tables:
        return "", []
    boxes = [table.bbox for table in tables]

    def outside(obj):
        if obj.get("object_type") != "char":
            return True
        x = (obj["x0"] + obj["x1"]) / 2
        y = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= x <= x1 and top <= y <= bottom for x0, top, x1, bottom in boxes)

    text = plumber_page.filter(outside).extract_text() or ""
    return text, [table.extract() for table in tables]


def _add_pdf_tables(builder, number, tables):
    for table_number, rows in enumerate(tables, start=1):
        for row_number, row in enumerate(rows, start=1):
            _row(builder, f"p{number}t{table_number}r{row_number}",
                 [(column, " ".join(str(cell).split()) if cell else None)
                  for column, cell in enumerate(row, start=1)],
                 {"page": number, "table": table_number, "row": row_number},
                 lambda column, t=table_number, r=row_number:
                     f"P{number}T{t}R{r}C{column}")


def _parse_pdf(data: bytes) -> SourceDocument:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    builder = _Builder()
    max_ocr_pages = int(os.getenv("PDF_OCR_MAX_PAGES", "50"))
    max_table_pages = int(os.getenv("PDF_TABLE_MAX_PAGES", "200"))
    coverage = {"pages": len(reader.pages), "text_pages": [], "ocr_pages": [],
                "empty_pages": [], "failed_pages": [], "table_pages": [], "tables": 0,
                "low_quality_pages": [], "page_quality": []}
    results, unavailable = [], 0
    raster, plumber = _PdfRaster(data), None
    try:
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if len(text.strip()) >= MIN_PAGE_TEXT:
                tables = []
                if number <= max_table_pages:
                    try:
                        if plumber is None:
                            import pdfplumber

                            plumber = pdfplumber.open(io.BytesIO(data))
                        outside, tables = _pdf_tables(plumber.pages[number - 1])
                    except Exception as exc:  # una tabla ilegible no invalida el texto
                        coverage.setdefault("table_errors", []).append(
                            {"page": number, "error": f"{type(exc).__name__}"[:200]})
                if tables:
                    builder.add(f"p{number}", outside, {"page": number})
                    _add_pdf_tables(builder, number, tables)
                    coverage["table_pages"].append(number)
                    coverage["tables"] += len(tables)
                else:
                    builder.add(f"p{number}", text, {"page": number})
                coverage["text_pages"].append(number)
                continue
            if not _has_marks(page):
                builder.add(f"p{number}", text, {"page": number})
                (coverage["text_pages"] if text.strip() else coverage["empty_pages"]).append(number)
                continue
            if len(coverage["ocr_pages"]) + len(coverage["failed_pages"]) >= max_ocr_pages:
                coverage["failed_pages"].append({"page": number, "error": "límite de páginas OCR"})
                continue
            try:
                image = raster.page(number - 1, page)
            except Exception as exc:  # imagen corrupta o filtro no soportado
                coverage["failed_pages"].append({"page": number,
                                                 "error": f"imagen ilegible: {exc}"[:200]})
                continue
            try:
                result = ocr_image(image)
            except ValueError as exc:
                coverage["failed_pages"].append({"page": number, "error": str(exc)})
                continue
            except OCRUnavailable as exc:
                unavailable += 1
                coverage["failed_pages"].append({"page": number, "error": str(exc)})
                continue
            results.append(result)
            if not result.get("text", "").strip():
                if text.strip():
                    builder.add(f"p{number}", text, {"page": number})
                    coverage["text_pages"].append(number)
                    continue
                coverage["failed_pages"].append({"page": number, "error": "OCR sin texto legible"})
                continue
            coverage["ocr_pages"].append(number)
            coverage["page_quality"].append({
                "page": number, "mean_confidence": result.get("mean_confidence"),
                "low_confidence_ratio": result.get("low_confidence_ratio"),
                "needs_review": bool(result.get("needs_review"))})
            if result.get("needs_review"):
                coverage["low_quality_pages"].append(number)
            _add_ocr(builder, result, number, f"p{number}")
    finally:
        raster.close()
        if plumber is not None:
            plumber.close()
    if unavailable and not coverage["text_pages"] and not coverage["ocr_pages"]:
        raise OCRUnavailable("El OCR no estuvo disponible para ninguna página")
    ocr = _summarize_ocr(results)
    if coverage["failed_pages"] and ocr:
        ocr["needs_review"] = True
    return builder.build("application/pdf", coverage, ocr)


def _parse_csv(data: bytes) -> SourceDocument:
    builder = _Builder()
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    for number, row in enumerate(rows, start=1):
        _row(builder, f"r{number}", list(enumerate(row, start=1)), {"row": number},
             lambda column, number=number: f"{_column_letter(column)}{number}")
    return builder.build("text/csv", {"rows": len(rows)})


def _cell_text(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value


def _parse_xlsx(data: bytes) -> SourceDocument:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    builder = _Builder()
    coverage = {"sheets": []}
    for sheet_number, sheet in enumerate(workbook.worksheets, start=1):
        rows = 0
        for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            rows += 1
            _row(builder, f"s{sheet_number}r{row_number}",
                 [(column, _cell_text(value)) for column, value in enumerate(values, start=1)],
                 {"sheet": sheet.title, "row": row_number},
                 lambda column, row=row_number, title=sheet.title:
                     f"{title}!{_column_letter(column)}{row}")
        coverage["sheets"].append({"sheet": sheet.title, "rows": rows})
    workbook.close()
    return builder.build(XLSX_MIME, coverage)


def _parse_docx(data: bytes) -> SourceDocument:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    builder = _Builder()
    paragraphs = tables = 0
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraphs += 1
            builder.add(f"para{paragraphs}", Paragraph(element, document).text,
                        {"paragraph": paragraphs})
        elif tag == "tbl":
            tables += 1
            for row_number, row in enumerate(Table(element, document).rows, start=1):
                cells, previous = [], None
                for cell in row.cells:
                    if cell._tc is previous:  # celdas combinadas se repiten en python-docx
                        continue
                    previous = cell._tc
                    cells.append((len(cells) + 1, cell.text))
                _row(builder, f"t{tables}r{row_number}", cells,
                     {"table": tables, "row": row_number},
                     lambda column, t=tables, r=row_number: f"T{t}R{r}C{column}")
    return builder.build(DOCX_MIME, {"paragraphs": paragraphs, "tables": tables})


def _parse_image(data: bytes, mime_type: str) -> SourceDocument:
    result = ocr_image(data)
    builder = _Builder()
    _add_ocr(builder, result, 1, "p1")
    return builder.build(mime_type, {"pages": 1, "ocr_pages": [1], "failed_pages": []},
                         _summarize_ocr([result]))


def parse_document(data: bytes, mime_type: str) -> SourceDocument:
    if mime_type == DXF_MIME:
        return SourceDocument("", [], mime_type, PARSER_VERSION,
                              {"entities": "available to the plan importer"}, {})
    if mime_type == "application/pdf":
        return _parse_pdf(data)
    if mime_type == "text/csv":
        return _parse_csv(data)
    if mime_type == XLSX_MIME:
        return _parse_xlsx(data)
    if mime_type == DOCX_MIME:
        return _parse_docx(data)
    if mime_type in {"image/png", "image/jpeg"}:
        return _parse_image(data, mime_type)
    raise ValueError("No parser is configured for this file type")
