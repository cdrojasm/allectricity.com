"""Documento fuente con localizadores estructurados (página, hoja/fila/celda, párrafo, región)."""

import hashlib
from dataclasses import dataclass, field

LOCATOR_KEYS = ("page", "sheet", "row", "paragraph", "table", "cell")


@dataclass(frozen=True)
class Segment:
    """Fragmento contiguo del texto plano con su origen legible.

    `cells` guarda (inicio relativo, fin relativo, referencia) para filas tabulares, de modo
    que una cita puede llevar a la celda exacta. `quality` es la confianza OCR (0-100) o
    None para texto nativo.
    """

    id: str
    start: int
    end: int
    locator: dict
    quality: float | None = None
    needs_review: bool = False
    region: tuple | None = None  # (x, y, ancho, alto) en píxeles de la página OCR
    cells: tuple = ()


@dataclass
class SourceDocument:
    text: str
    segments: list
    mime_type: str
    parser_version: str
    coverage: dict = field(default_factory=dict)
    ocr: dict = field(default_factory=dict)

    def __post_init__(self):
        self._by_id = {segment.id: segment for segment in self.segments}

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def complete(self) -> bool:
        return not self.coverage.get("failed_pages")

    def segment(self, segment_id: str) -> Segment | None:
        return self._by_id.get(segment_id)

    def segment_text(self, segment: Segment) -> str:
        return self.text[segment.start:segment.end]

    def resolve(self, locator: dict) -> list:
        """Segmentos designados por un localizador del contrato de extracción."""
        if locator.get("segment"):
            found = self.segment(locator["segment"])
            return [found] if found else []
        wanted = {key: locator[key] for key in LOCATOR_KEYS if key in locator}
        if not wanted:
            return []
        return [segment for segment in self.segments
                if all(segment.locator.get(key) == value for key, value in wanted.items())]

    def find_quote(self, quote: str, segments) -> tuple[int, int] | None:
        """Ubica la cita dentro de los segmentos, sin distinguir mayúsculas ni espacios."""
        needle, _ = _normalized(quote)
        if not needle:
            return None
        for segment in segments:
            haystack, index = _normalized(self.text[segment.start:segment.end])
            position = haystack.find(needle)
            if position >= 0:
                start = segment.start + index[position]
                end = segment.start + index[position + len(needle) - 1] + 1
                return start, end
        return None

    def locator_for(self, start: int, end: int) -> dict:
        """Localizador legible para un intervalo: el usuario puede volver al pasaje original."""
        covered = [s for s in self.segments if s.start < end and s.end > start] or \
            [s for s in self.segments if s.start <= start <= s.end][:1]
        if not covered:
            return {"start": start, "end": end}
        first = covered[0]
        locator = dict(first.locator, start=start, end=end, segment=first.id)
        if len(covered) > 1:
            locator["end_segment"] = covered[-1].id
        cells = [ref for segment in covered for rel_start, rel_end, ref in segment.cells
                 if segment.start + rel_start < end and segment.start + rel_end > start]
        if cells:
            locator["cells"] = cells
        regions = [s.region for s in covered if s.region]
        if regions:
            left = min(r[0] for r in regions)
            top = min(r[1] for r in regions)
            right = max(r[0] + r[2] for r in regions)
            bottom = max(r[1] + r[3] for r in regions)
            locator["region"] = [left, top, right - left, bottom - top]
        return locator

    def quality_for(self, start: int, end: int) -> tuple[float | None, bool]:
        covered = [s for s in self.segments if s.start < end and s.end > start]
        qualities = [s.quality for s in covered if s.quality is not None]
        return (min(qualities) if qualities else None,
                any(s.needs_review for s in covered))


def _normalized(text: str) -> tuple[str, list]:
    """Minúsculas y espacios colapsados, con el índice original de cada carácter."""
    characters, index, previous_space = [], [], False
    for position, character in enumerate(text):
        if character.isspace():
            if previous_space or not characters:
                continue
            characters.append(" ")
            index.append(position)
            previous_space = True
            continue
        lowered = character.lower()
        characters.append(lowered if len(lowered) == 1 else character)
        index.append(position)
        previous_space = False
    if characters and characters[-1] == " ":
        characters.pop()
        index.pop()
    return "".join(characters), index


def normalized_text(text: str) -> str:
    return _normalized(text)[0]
