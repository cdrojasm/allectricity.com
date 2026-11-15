"""Queue potential-engine calculations for artifact versions (API and agent)."""

from time import time
from uuid import uuid4

from src.domain.agent.patches import unconfirmed_critical
from src.domain.spat.grid_geometry import missing_for_calculation
from src.domain.spat.input_coherence import coherence_errors


class CalculationBlocked(Exception):
    """The artifact version cannot be calculated yet; `detail` says why."""

    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


def create_calculation(db, project_id: str, artifact_id: str, version: int, parameters: dict, actor_id: str) -> dict:
    """Insert a pending calculation; the caller dispatches the worker after commit."""
    artifact = db.designs.get_version(project_id, artifact_id, version)
    if not artifact:
        raise CalculationBlocked(404, "Artifact version not found")
    missing = missing_for_calculation(artifact["snapshot"])
    if missing:
        raise CalculationBlocked(409, {"message": "El artefacto está incompleto para calcular", "missing": missing})
    provenance = (artifact.get("origin") or {}).get("provenance") or {}
    unconfirmed = unconfirmed_critical(artifact["snapshot"], provenance) if provenance else []
    if unconfirmed:
        raise CalculationBlocked(409, {"message": "Confirma los datos críticos antes de calcular",
                                       "unconfirmed_critical": unconfirmed})
    # BL-15: deterministic coherence rules; an error means the data cannot describe a real design.
    incoherent = coherence_errors(artifact["snapshot"])
    if incoherent:
        raise CalculationBlocked(409, {"message": "Los datos de entrada no son coherentes; corrígelos antes de calcular: "
                                                  + " ".join(d["message"] for d in incoherent),
                                       "coherence": incoherent})
    now = int(time())
    row = {"id": str(uuid4()), "project_id": project_id, "artifact_id": artifact_id, "artifact_version": version,
           "status": "pending", "parameters": parameters, "result": None, "trace": None, "error": None,
           "created_by": actor_id, "created_at": now, "updated_at": now}
    db.add("calculos_potencial_tierras", **row)
    return row


def mark_dispatch_failed(store, calculation_id: str) -> None:
    with store.transaction(write=True) as db:
        db.change("calculos_potencial_tierras", calculation_id, status="failed",
                  error="No se pudo encolar el cálculo", updated_at=int(time()))
