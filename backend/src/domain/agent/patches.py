"""Rules for the agent's edits to the artifact draft.

Every edited value carries its source. Critical inputs (fault current and duration, soil
resistivity, surface layer) only come from project data; non-critical ones may take a
typical value as an explicit assumption the user approves.
"""

from copy import deepcopy

from src.domain.spat.artifact_contract import validate_document

EDITABLE = ("name", "geometry.", "conductor.", "soil_layers", "fault.")
CRITICAL = frozenset({
    "soil_layers",
    "fault.current_a",
    "fault.clearing_time_s",
    "fault.surface_resistivity_ohm_m",
    "fault.surface_thickness_m",
})
# Sections compared and shown as a whole (a sounding is one dataset).
LEAVES = frozenset({"soil_measurements"})
SOURCE_KINDS = frozenset({"user", "claim", "document", "tool", "assumption"})
# Provenance kinds that leave a critical input unconfirmed.
UNCONFIRMED = frozenset({"schema_default", "assumption", None})


class PatchError(ValueError):
    pass


def is_critical(path: str) -> bool:
    return path in CRITICAL


def check_change(path: str, source: dict, *, draft: bool = False) -> dict:
    """Validate one change; critical assumptions require an explicit draft marker."""
    if not isinstance(path, str) or not any(path == p or (p.endswith(".") and path.startswith(p) and len(path) > len(p))
                                            for p in EDITABLE):
        raise PatchError(f"Path not editable by the agent: {path}")
    if path.count(".") > 1:
        raise PatchError(f"Path too deep: {path}")
    kind = (source or {}).get("kind")
    if kind not in SOURCE_KINDS:
        raise PatchError(f"{path}: every change needs a source kind among {sorted(SOURCE_KINDS)}")
    if kind == "assumption" and is_critical(path) and not (draft and source.get("draft") is True):
        raise PatchError(f"{path} is a critical input: it needs project data (a user message, an accepted "
                         "claim or a confirmed document), never a typical value")
    if kind == "assumption" and is_critical(path) and not str(source.get("note") or "").strip():
        raise PatchError(f"{path}: a draft assumption needs a visible note")
    ref = source.get("ref")
    if kind != "assumption" and not ref:
        raise PatchError(f"{path}: source {kind} needs a ref (message id, claim id, document or tool result)")
    entry = {"kind": kind, "ref": ref}
    if kind == "assumption" and is_critical(path):
        entry["draft"] = True
    if source.get("note"):
        entry["note"] = str(source["note"])[:300]
    return entry


def set_path(snapshot: dict, path: str, value) -> dict:
    result = deepcopy(snapshot)
    head, _, tail = path.partition(".")
    if tail:
        section = result.get(head)
        result[head] = {**(section if isinstance(section, dict) else {}), tail: value}
    else:
        result[head] = value
    return result


def get_path(snapshot: dict | None, path: str):
    head, _, tail = path.partition(".")
    value = (snapshot or {}).get(head)
    if tail:
        return value.get(tail) if isinstance(value, dict) else None
    return value


def flatten(snapshot: dict | None) -> dict:
    """Editable leaves of a snapshot as {path: value} (lists are leaves)."""
    flat = {}
    for key, value in (snapshot or {}).items():
        if key == "compliance":
            continue
        if isinstance(value, dict) and key not in LEAVES:
            for sub, item in value.items():
                flat[f"{key}.{sub}"] = item
        else:
            flat[key] = value
    return flat


def diff(before: dict | None, after: dict) -> list[dict]:
    old, new = flatten(before), flatten(after)
    changes = [{"path": path, "before": old.get(path), "after": new.get(path)}
               for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path)]
    return validate_document("artifact_diff", changes)


def unconfirmed_critical(snapshot: dict | None, provenance: dict) -> list[str]:
    """Critical inputs that are missing or not backed by project data."""
    return [path for path in sorted(CRITICAL)
            if get_path(snapshot, path) in (None, [])
            or (provenance.get(path) or {}).get("kind") in UNCONFIRMED]
