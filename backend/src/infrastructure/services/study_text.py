"""Guards for the study text a model writes; shared by the API and the agent worker (no web framework)."""

import re

_DENIALS = ("no se cuenta", "no se dispone", "sin resultados", "no hay resultados", "no existen resultados", "aún no se ha calculado", "no se ha realizado")

_VERDICT_CODES = {"no_cumple": "no cumple", "no_evaluado": "no evaluado", "no_evaluable": "no evaluable", "cumple": "cumple"}


def plain_codes(text: str) -> str:
    """Verdict codes the model copied from the result («"no_cumple"») read as plain Spanish."""
    def plain(match):
        return _VERDICT_CODES[match.group(1)]
    return re.sub(r"[\"“”«»']?\b(no_cumple|no_evaluado|no_evaluable)\b[\"“”«»']?", plain, text)


def denies_results(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _DENIALS)


def latest_completed(db, study):
    rows = [row for row in db.many("calculos_potencial_tierras", project_id=study["project_id"], artifact_id=study["artifact_id"], artifact_version=study["artifact_version"], limit=1000) if row["status"] == "completed"]
    return max(rows, key=lambda row: row["created_at"]) if rows else None
