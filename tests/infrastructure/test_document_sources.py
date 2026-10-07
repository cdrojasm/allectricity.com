import io

import pytest
from PIL import Image

from src.infrastructure.processing import document_sources
from src.infrastructure.processing.document_sources import (
    DOCX_MIME, XLSX_MIME, OCRUnavailable, parse_document,
)


def _pdf(pages) -> bytes:
    """PDF mínimo: cada página es texto (str) o una imagen JPEG (bytes)."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 "
               b"/BaseFont /Helvetica >>"}
    kids, number = [], 4
    for page in pages:
        page_id, content_id = number, number + 1
        number += 2
        resources = b"<< /Font << /F1 3 0 R >> >>"
        if isinstance(page, bytes):
            image_id = number
            number += 1
            width, height = Image.open(io.BytesIO(page)).size
            objects[image_id] = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                                 b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                                 b"/Length %d >>\nstream\n" % (width, height, len(page))
                                 + page + b"\nendstream")
            resources = b"<< /XObject << /Im1 %d 0 R >> >>" % image_id
            stream = b"q 500 0 0 300 50 400 cm /Im1 Do Q"
        else:
            lines = b" T* ".join(b"(" + line.encode("latin-1").replace(b"(", b"\\(")
                                 .replace(b")", b"\\)") + b") Tj" for line in page.split("\n"))
            stream = b"BT /F1 11 Tf 14 TL 50 750 Td " + lines + b" ET"
        objects[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objects[page_id] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                            b"/Resources " + resources + b" /Contents %d 0 R >>" % content_id)
        kids.append(page_id)
    objects[2] = (b"<< /Type /Pages /Count %d /Kids [" % len(kids)
                  + b" ".join(b"%d 0 R" % kid for kid in kids) + b"] >>")
    output, offsets = io.BytesIO(), {}
    output.write(b"%PDF-1.4\n")
    for object_id in sorted(objects):
        offsets[object_id] = output.tell()
        output.write(b"%d 0 obj\n" % object_id + objects[object_id] + b"\nendobj\n")
    xref = output.tell()
    size = max(objects) + 1
    output.write(b"xref\n0 %d\n0000000000 65535 f \n" % size)
    for object_id in range(1, size):
        output.write(b"%010d 00000 n \n" % offsets.get(object_id, 0))
    output.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref))
    return output.getvalue()


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def _ocr_result(lines, confidence=91.0):
    return {"text": "\n".join(lines), "mean_confidence": confidence,
            "low_confidence_ratio": 0.0, "word_count": sum(len(l.split()) for l in lines),
            "needs_review": confidence < 60,
            "lines": [{"text": line, "confidence": confidence, "bbox": [10, 20 * i, 300, 18]}
                      for i, line in enumerate(lines, start=1)]}


def test_pdf_text_keeps_page_locators():
    source = parse_document(_pdf(["Portada del proyecto de puesta a tierra",
                                  "El transformador T1, 13,8 kV, alimenta el tablero TD-2"]),
                            "application/pdf")
    assert [s.locator for s in source.segments] == [{"page": 1}, {"page": 2}]
    start = source.text.index("T1")
    locator = source.locator_for(start, start + 2)
    assert locator["page"] == 2 and locator["segment"] == "p2"
    assert source.coverage["text_pages"] == [1, 2] and source.complete


def test_scanned_pdf_pages_are_ocred_with_regions_and_partial_failures(monkeypatch):
    calls = []

    def fake_ocr(data):
        calls.append(data)
        if len(calls) == 2:
            raise ValueError("OCR rechazó la imagen (415)")
        return _ocr_result(["Malla de puesta a tierra", "Profundidad 0,5 m"])

    monkeypatch.setattr(document_sources, "ocr_image", fake_ocr)
    source = parse_document(_pdf(["Memoria descriptiva del sistema de puesta a tierra",
                                  _jpeg(), _jpeg()]), "application/pdf")
    assert source.coverage["ocr_pages"] == [2]
    assert source.coverage["failed_pages"][0]["page"] == 3
    assert not source.complete and source.ocr["needs_review"]
    start = source.text.index("Profundidad")
    locator = source.locator_for(start, start + 11)
    assert locator["page"] == 2 and locator["region"] == [10, 40, 300, 18]
    assert source.quality_for(start, start + 11) == (91.0, False)


def test_illegible_scanned_page_marks_the_document_incomplete(monkeypatch):
    monkeypatch.setattr(document_sources, "ocr_image",
                        lambda data: dict(_ocr_result([], confidence=0.0), text="", lines=[]))
    source = parse_document(_pdf(["Memoria descriptiva del sistema de puesta a tierra",
                                  _jpeg()]), "application/pdf")
    assert source.coverage["failed_pages"] == [{"page": 2, "error": "OCR sin texto legible"}]
    assert not source.complete and source.ocr["needs_review"]


def test_pdf_retries_when_ocr_is_unavailable_for_every_page(monkeypatch):
    def unavailable(data):
        raise OCRUnavailable("down")

    monkeypatch.setattr(document_sources, "ocr_image", unavailable)
    with pytest.raises(OCRUnavailable):
        parse_document(_pdf([_jpeg()]), "application/pdf")


def test_csv_rows_and_cells():
    source = parse_document("equipo,tensión\nT1,\"13,8 kV\"\n".encode(), "text/csv")
    start = source.text.index("13,8")
    locator = source.locator_for(start, start + 7)
    assert locator["row"] == 2 and locator["cells"] == ["B2"]


def test_xlsx_sheet_row_and_cell():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Resistividad"
    sheet.append(["Espaciamiento (m)", "Resistividad aparente (Ω·m)"])
    sheet.append([2, 145.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    source = parse_document(buffer.getvalue(), XLSX_MIME)
    start = source.text.index("145.5")
    locator = source.locator_for(start, start + 5)
    assert locator["sheet"] == "Resistividad" and locator["row"] == 2
    assert locator["cells"] == ["Resistividad!B2"]
    assert source.resolve({"sheet": "Resistividad", "row": 2})[0].id == "s1r2"


def test_docx_paragraphs_and_tables_in_document_order():
    from docx import Document

    document = Document()
    document.add_paragraph("Memoria de puesta a tierra")
    document.add_paragraph("La malla se entierra a 0,5 m.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Parámetro", "Valor"
    table.cell(1, 0).text, table.cell(1, 1).text = "If", "12,5 kA"
    buffer = io.BytesIO()
    document.save(buffer)
    source = parse_document(buffer.getvalue(), DOCX_MIME)
    assert [s.id for s in source.segments] == ["para1", "para2", "t1r1", "t1r2"]
    start = source.text.index("12,5")
    assert source.locator_for(start, start + 4)["cells"] == ["T1R2C2"]
    assert source.resolve({"paragraph": 2})[0].id == "para2"


def test_unsupported_type_is_rejected():
    with pytest.raises(ValueError):
        parse_document(b"x", "application/zip")
