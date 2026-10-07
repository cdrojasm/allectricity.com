"""Compatibility wrappers over the locator-preserving document parser.

The knowledge-graph pipeline lives in `knowledge_extraction`; the legacy
`ElectricalAsset`/`ElectricalParameter` writer was retired in favour of claims with provenance.
"""

from src.infrastructure.processing.document_sources import parse_document


def extract_document(data: bytes, mime_type: str) -> tuple[str, dict]:
    source = parse_document(data, mime_type)
    return source.text, source.ocr


def extract_text(data: bytes, mime_type: str) -> str:
    """Compatibility wrapper returning only extracted text."""
    return extract_document(data, mime_type)[0]
