"""Adaptador del grafo al ajuste de sondeo ya existente (PR-22)."""

from src.domain.knowledge_graph.artifact_mapping import map_soil_measurements
from src.infrastructure.calculations.soil_sounding import fit_sounding


def fit_graph_soil_measurements(claims: list[dict], *, layer_count: int = 2,
                                outlier_threshold: float = 0.15) -> dict:
    """Mapea lecturas extraídas y ejecuta el mismo ajuste usado por la API manual."""
    mapped = map_soil_measurements(claims)
    if not mapped["valid"]:
        problems = []
        if mapped["state"] != "encontrado":
            problems.append("el arreglo Wenner/Schlumberger falta o está en conflicto")
        if mapped["pending"]:
            problems.append(f"faltan datos en {len(mapped['pending'])} lectura(s)")
        if mapped["count"] < 4:
            problems.append("se requieren al menos 4 lecturas completas")
        raise ValueError("No se puede ajustar el sondeo extraído: " + "; ".join(problems))
    fit = fit_sounding(mapped["measurements"], mapped["array"], layer_count, outlier_threshold)
    return {"soil_measurements": {"array": mapped["array"],
                                  "measurements": mapped["measurements"],
                                  "source": {"kind": "knowledge_graph",
                                             "claim_ids": [claim_id for reading in mapped["measurements"]
                                                           for claim_id in reading["claim_ids"]]}},
            "fit": fit}
