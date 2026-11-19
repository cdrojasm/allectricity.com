"""Multimodal plan proposal adapter. It never writes an artifact."""

import base64
import json
import math


def propose_plan_from_image(work, data: bytes, mime_type: str, geometry: dict) -> dict:
    """`work` is the spat-plan-vision unit of work (prompt, model and parameters from Phoenix)."""
    if mime_type not in {"image/png", "image/jpeg"}:
        raise ValueError("The vision proposal currently requires a rasterized PNG or JPEG plan")
    prompt = {
        "task": "Identify buildings, roads, foundations and other non-excavatable obstacles in this plan.",
        "output": {"structures": [{"x": "center x in metres", "y": "center y in metres", "width": "metres",
                                    "height": "metres", "label": "short label"}],
                   "zone": {"polygon": [{"x": "metres", "y": "metres"}] }},
        "constraints": "Use the existing plan extent; do not invent a scale or electrical connection. Return [] when unsure.",
        "extent_m": {"length": geometry.get("length_m"), "width": geometry.get("width_m")},
    }
    response = work.complete(
        [{"role": "user", "content": [{"type": "text", "text": json.dumps(prompt, ensure_ascii=False)},
                                      {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"}}]}],
        response_format={"type": "json_object"}, temperature=0,
    )
    content = response.choices[0].message.content or "{}"
    try:
        proposal = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("The vision provider returned invalid JSON") from exc
    raw_structures = proposal.get("structures") or []
    if not isinstance(raw_structures, list) or len(raw_structures) > 200:
        raise ValueError("The vision proposal contains too many structures")
    length = float(geometry.get("length_m") or 0)
    width = float(geometry.get("width_m") or 0)
    structures = []
    rejected = 0
    for item in raw_structures:
        if not isinstance(item, dict):
            rejected += 1
            continue
        try:
            x, y = float(item["x"]), float(item["y"])
            item_width, item_height = float(item["width"]), float(item["height"])
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if not all(math.isfinite(value) for value in (x, y, item_width, item_height)):
            rejected += 1
            continue
        if item_width <= 0 or item_height <= 0 or item_width > length or item_height > width:
            rejected += 1
            continue
        if not (0 <= x <= length and 0 <= y <= width):
            rejected += 1
            continue
        structures.append({"x": x, "y": y, "width": item_width, "height": item_height,
                           "label": str(item.get("label") or "Elemento constructivo")[:120]})
    warnings = ["Propuesta multimodal: revisa y confirma obstáculos antes de aplicarlos."]
    if rejected:
        warnings.append(f"{rejected} detección(es) se descartaron por coordenadas o dimensiones inválidas.")
    return {"requires_confirmation": True, "structures": structures, "zone": proposal.get("zone"),
            "warnings": warnings}
