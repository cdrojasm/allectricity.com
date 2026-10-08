"""Safe, bounded DXF-to-plan conversion.

The importer intentionally returns a proposal. Applying it remains a versioned
artifact edit, so a malformed or surprising CAD file cannot mutate a design.
"""

from io import BytesIO
from math import isfinite


MAX_ENTITIES = 4000


def import_dxf(data: bytes, *, max_entities: int = MAX_ENTITIES) -> dict:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("DXF import requires the optional 'parsers' dependency") from exc
    try:
        from ezdxf import recover

        document, _auditor = recover.read(BytesIO(data))  # ezdxf.read only accepts text streams
        modelspace = document.modelspace()
    except Exception as exc:
        raise ValueError("The DXF file could not be read") from exc
    lines, layers, points = [], {}, []
    for index, entity in enumerate(modelspace):
        if index >= max_entities:
            raise ValueError(f"The DXF contains more than {max_entities} entities")
        layer = str(entity.dxf.get("layer") or "0")
        layers[layer] = layers.get(layer, 0) + 1
        kind = entity.dxftype()
        if kind == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            lines.append((float(start.x), float(start.y), float(end.x), float(end.y), layer))
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            vertices = list(entity.get_points("xy")) if kind == "LWPOLYLINE" else [tuple(v.dxf.location)[:2] for v in entity.vertices]
            for start, end in zip(vertices, vertices[1:]):
                lines.append((float(start[0]), float(start[1]), float(end[0]), float(end[1]), layer))
        elif kind == "CIRCLE":
            center = entity.dxf.center
            points.append({"x": float(center.x), "y": float(center.y), "length_m": float(entity.dxf.radius) * 2,
                           "label": f"DXF círculo · capa {layer}"})
    coordinates = [(x, y) for x1, y1, x2, y2, _ in lines for x, y in ((x1, y1), (x2, y2))]
    coordinates += [(item["x"], item["y"]) for item in points]
    if not coordinates:
        raise ValueError("The DXF contains no supported LINE, POLYLINE or CIRCLE geometry")
    min_x, min_y = min(x for x, _ in coordinates), min(y for _, y in coordinates)
    max_x, max_y = max(x for x, _ in coordinates), max(y for _, y in coordinates)
    conductors = [{"start": {"x": round(x1 - min_x, 6), "y": round(y1 - min_y, 6)},
                   "end": {"x": round(x2 - min_x, 6), "y": round(y2 - min_y, 6)}}
                  for x1, y1, x2, y2, _ in lines if all(isfinite(v) for v in (x1, y1, x2, y2))]
    rods = [{"x": round(item["x"] - min_x, 6), "y": round(item["y"] - min_y, 6),
             "length_m": None} for item in points]
    return {"geometry": {"length_m": round(max_x - min_x, 6), "width_m": round(max_y - min_y, 6),
                          "burial_depth_m": 0.5, "conductors": conductors, "rods": rods},
            "layers": [{"name": name, "entities": count} for name, count in sorted(layers.items())],
            "entity_count": len(lines) + len(points), "normalization": {"origin_x": min_x, "origin_y": min_y}}
