"""Generate the independent-review package for the potential engine validation.

Usage (repository root, after `make potential-engine`):
    python services/potential_engine/validation/review_report.py [--output services/potential_engine/validation/REVIEW.md]
"""

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from src.infrastructure.calculations.potential_engine_client import PotentialEngineClient  # noqa: E402
from src.infrastructure.calculations.potential_engine_validation import (  # noqa: E402
    convergence,
    load_cases,
    validate,
)

CONVERGENCE_CASES = {
    "ieee80_annex_h_grid1": [3.5, 1.75, 1.0, 0.7],
    "ieee80_annex_h_grid2": [3.5, 1.75, 1.0, 0.7],
}


def reference_text(reference: dict) -> str:
    if "value" in reference:
        return f"{reference['value']:g}"
    return f"{reference['min']:g} – {reference['max']:g}"


def build(client: PotentialEngineClient) -> str:
    cases = load_cases()
    rows = validate(client, cases)
    version = rows[0]["engine_version"]
    passed = sum(row["passed"] for row in rows)
    notes = [(case["id"], check.get("label", check["quantity"]), check["note"])
             for case in cases["cases"] for check in case["checks"] if "note" in check]
    lines = [
        "# Paquete de revisión independiente — motor de potencial SPAT",
        "",
        f"Generado el {date.today().isoformat()} con `validation/review_report.py`, solver {version}. "
        "Regenerar después de cualquier cambio del motor o de `reference_cases.json`.",
        "",
        "## Alcance que se revisa",
        "",
        "Motor cuasiestático de electrodos cilíndricos delgados en suelo homogéneo, isotrópico y semiinfinito, "
        "con metal ideal equipotencial por grupo. No cubre suelo estratificado, impedancia del conductor, "
        "reparto de corriente de falla, capa superficial ni criterios tolerables normativos. "
        "La revisión aprueba o rechaza el motor solo para ese alcance.",
        "",
        f"## Resultado: {passed} de {len(rows)} comprobaciones dentro de tolerancia",
        "",
        "| Caso | Magnitud | Motor | Referencia | Desviación | Tolerancia propuesta | Estado | Fuente |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['label']} | {row['value']:.4g} | {reference_text(row['reference'])} "
            f"| {100 * row['deviation_rel']:+.2f} % | ±{100 * row['tolerance_rel']:g} % "
            f"| {'pasa' if row['passed'] else '**falla**'} | {row['source']} |"
        )
    lines += ["", "La desviación es 0 cuando el valor cae dentro del rango publicado; si no, se mide contra el extremo más cercano.", "",
              "## Fuentes", ""]
    for key, source in cases["sources"].items():
        lines.append(f"- **{key}** — {source['citation']}. Método: {source['method']}. Versión: {source['version']}.")
    lines += ["", "## Desviaciones conocidas y notas", ""]
    lines += [f"- **{case} / {label}:** {note}" for case, label, note in notes]
    lines += ["", "## Convergencia de discretización", "",
              "Cambio relativo de cada magnitud respecto al refinamiento anterior.", ""]
    by_id = {case["id"]: case for case in cases["cases"]}
    for case_id, steps in CONVERGENCE_CASES.items():
        report = convergence(client, by_id[case_id], steps)
        lines += [f"**{case_id}**", "", "| Segmento | Segmentos | " + " | ".join(report["quantities"]) + " |",
                  "|---|---|" + "---|" * len(report["quantities"])]
        for row in report["segment_sweep"]:
            changes = row["change_rel"] or [None] * len(row["values"])
            cells = [f"{v:.4g}" + ("" if c is None else f" ({100 * c:.2f} %)") for v, c in zip(row["values"], changes)]
            lines.append(f"| {row['discretization_m']} m | {row['segment_count']} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## Preguntas para el revisor",
        "",
        "1. ¿Son aceptables las tolerancias propuestas (±2–2,5 % en resistencia, ±5 % en tensiones; ±0,5 % en la regresión interna)?",
        "2. Cotejar cada valor de las fuentes `ieee80_2013_annex_h` y `ieee80_2013_annex_b` con una copia licenciada de IEEE Std 80-2013/Cor 1-2015; se transcribieron de un tercero.",
        "3. ¿Se acepta la explicación de la desviación del paso S1 del Grid 1 (referencia sub-resuelta en la esquina), o se exige confirmarla con la Tabla H.5 o con una corrida fina en un programa comercial?",
        "4. ¿Es adecuada la recomendación de segmentos de 1 m o menos cerca de varillas y esquinas?",
        "5. ¿Hace falta algún caso adicional dentro del alcance homogéneo antes de exponer resultados a usuarios?",
        "",
        "## Dictamen",
        "",
        "| Campo | Valor |",
        "|---|---|",
        "| Revisor | |",
        "| Matrícula profesional | |",
        "| Independencia respecto al desarrollo | |",
        "| Fecha | |",
        "| Commit revisado | |",
        "| Dictamen (aprobado / aprobado con condiciones / rechazado) | |",
        "| Tolerancias modificadas | |",
        "| Condiciones u observaciones | |",
        "",
        "Al aprobar, actualizar `review.status` en `reference_cases.json` y la fila de validación en `BACKLOG.md`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("REVIEW.md"))
    args = parser.parse_args()
    args.output.write_text(build(PotentialEngineClient()), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
