"""Grounding design agent: orchestrator + grid designer working on the artifact draft.

The orchestrator talks to the user and owns the draft; the grid designer is a subagent that
returns geometry/conductor changes. Every number comes from the user or is an explicit
assumption on a non-critical field. Validated changes become a new artifact version at once
and the client is told to reload it (an `artifact.updated` message); critical inputs may stay
missing, which only blocks the potential calculation.
"""

import json
import os
from pathlib import Path
from time import time

from pydantic import TypeAdapter, ValidationError

from src.application.use_cases.agent_runs import StepOutcome, message_order
from src.domain.agent.events import EventLevel, EventType
from src.domain.agent.patches import (
    CRITICAL, UNCONFIRMED, get_path,
    PatchError, check_change, diff, flatten, set_path, unconfirmed_critical,
)
from src.domain.identity import ServiceError
from src.domain.spat import soil_materials
from src.domain.spat.soundings import apparent_resistivity, missing_in_text
from src.infrastructure.calculations.soil_sounding import fit_sounding
from src.infrastructure.processing import measurement_tables
from src.domain.spat.grid_geometry import (
    area_grid, clip_conductors, geometry_warnings, explicit_conductors, geometry_problems, missing_for_calculation, rod_layout,
)
from src.domain.knowledge_graph.artifact_mapping import map_claims_to_artifact
from src.domain.knowledge_graph.conflict_resolution import resolve_conflicts
from src.domain.agent.run import AgentMode
from src.infrastructure.agents import runtime
from src.infrastructure.entrypoint.api.schemas import (
    ArtifactFaultRequest, ArtifactGeometryRequest, ArtifactSoilLayerRequest, GroundingArtifactRequest,
    GroundingConductorRequest, PotentialCalculationRequest,
)
from src.application.use_cases import potential_calculations
from src.infrastructure.agents.calculation_summary import summarize as summarize_calculation

# Sections checked as soon as they change (geometry is checked when the designer submits, since
# the orchestrator may build it over several calls).
FIELD_NAMES = {"geometry": set(ArtifactGeometryRequest.model_fields), "fault": set(ArtifactFaultRequest.model_fields),
               "conductor": set(GroundingConductorRequest.model_fields)}
SECTION_MODELS = {"soil_layers": TypeAdapter(list[ArtifactSoilLayerRequest]),
                  "fault": TypeAdapter(ArtifactFaultRequest), "conductor": TypeAdapter(GroundingConductorRequest)}

HISTORY_MESSAGES = 20
ORCHESTRATOR_ROUNDS = 14
SOIL_ROUNDS = 10
MAX_TABLE_BYTES = 5 * 1024 * 1024
TABLE_MIMES = {"text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
DESIGNER_ROUNDS = 6
DESIGNER_PATHS = ("name", "geometry.", "conductor.")
DEFAULT_DESIGN_ITERATIONS = 3


def enabled() -> bool:
    setting = os.getenv("DESIGN_AGENT_ENABLED", "auto").lower()
    if setting in {"true", "1", "yes"}:
        return True
    if setting in {"false", "0", "no"}:
        return False
    return bool(os.getenv("LLM_API_KEY"))


def model_for(env: str) -> str:
    return os.getenv(env) or os.getenv("LLM_MODEL", "gpt-4o-mini")


def max_design_iterations() -> int:
    """Return the safe per-run iteration cap; invalid configuration uses the default."""
    try:
        return max(0, int(os.getenv("DESIGN_MAX_ITERATIONS", str(DEFAULT_DESIGN_ITERATIONS))))
    except (TypeError, ValueError):
        return DEFAULT_DESIGN_ITERATIONS


def calculation_score(summary: dict) -> float:
    """Comparable safety margin for choosing the best non-compliant candidate."""
    margins = [criterion.get("margin_percent") for standard in summary.get("standards", [])
               for criterion in (standard.get("touch"), standard.get("step"))
               if isinstance(criterion, dict) and isinstance(criterion.get("margin_percent"), (int, float))]
    thermal = summary.get("conductor_thermal") or {}
    if thermal.get("status") == "no_cumple":
        margins.append(-1.0)
    return min(margins) if margins else float("-inf")


def _prompt_file(name: str) -> str:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "prompts" / "langfuse" / name
        if candidate.exists():
            return candidate.read_text()
    raise FileNotFoundError(name)


def load_prompts() -> dict:
    """System prompts from Langfuse, falling back to the checked-in seeds."""
    prompts = {}
    for key, env, name, file in (
        ("orchestrator", "AGENT_ORCHESTRATOR_PROMPT_NAME", "spat-agent-orchestrator", "agent-orchestrator.md"),
        ("grid_designer", "AGENT_GRID_DESIGNER_PROMPT_NAME", "spat-agent-grid-designer", "agent-grid-designer.md"),
        ("soil_modeler", "AGENT_SOIL_MODELER_PROMPT_NAME", "spat-agent-soil-modeler", "agent-soil-modeler.md"),
        ("safety_analyst", "AGENT_SAFETY_ANALYST_PROMPT_NAME", "spat-agent-safety-analyst", "agent-safety-analyst.md"),
    ):
        seed = _prompt_file(file)
        try:
            _, _, messages = runtime.load_prompt(env, name, fallback=seed)
        except Exception:
            messages = [{"role": "system", "content": seed}]
        prompts[key] = messages
    return prompts


def _errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()]


def _solver_inputs(parameters: dict) -> dict:
    """Calculation parameters without the free-text notes, which do not change the result."""
    inputs = {k: v for k, v in parameters.items() if k != "justification"}
    if inputs.get("fault_split"):
        inputs["fault_split"] = {k: v for k, v in inputs["fault_split"].items() if k != "split_factor_origin"}
    return inputs


class ArtifactWorkspace:
    """The run's draft of the artifact and the tools that read and change it."""

    def __init__(self, store, runs, run, storage=None):
        self.store, self.runs, self.run = store, runs, run
        self._storage = storage
        self.sounding, self.fits = None, {}
        self.pending_layout = None  # a rod layout that failed and is retried when the grid changes
        self.queued_calculation = None
        self.applied = False
        with store.transaction() as db:
            state = db.one("agent_conversation_state", id=run["conversation_id"]) or {}
            self.artifacts = {row["artifact_id"]: row for row in db.designs.latest_by_artifact(run["project_id"])}
        saved = run.get("draft_snapshot")
        if saved:
            self.artifact_id, self.base_version = saved["artifact_id"], saved["base_version"]
            self.base, self.draft = saved["base"], saved["snapshot"]
            self.provenance = saved["provenance"]
            self.sounding = saved.get("sounding")
            return
        artifact_id = run.get("artifact_id") or state.get("artifact_id")
        if not artifact_id and len(self.artifacts) == 1:
            artifact_id = next(iter(self.artifacts))
        self._load(artifact_id)

    def _load(self, artifact_id):
        row = self.artifacts.get(artifact_id) if artifact_id else None
        self.artifact_id = row["artifact_id"] if row else None
        self.base_version = row["version"] if row else None
        self.base = row["snapshot"] if row else None
        self.draft = dict(self.base) if self.base else {}
        origin = (row or {}).get("origin") or {}
        self.provenance = dict(origin.get("provenance") or {})
        if row and not self.provenance and origin.get("kind", "user") == "user":
            # Entered by the user in the forms or the API: their data, like a chat message.
            self.provenance = {path: {"kind": "user", "ref": f"version {row['version']}",
                                      "note": "Ingresado por el usuario"} for path in flatten(row["snapshot"])}

    def persisted_provenance(self) -> dict:
        """Provenance of the saved version the draft is based on (user form data counts as the user's)."""
        row = self.artifacts.get(self.artifact_id) if self.artifact_id else None
        if not row:
            return {}
        origin = row.get("origin") or {}
        if origin.get("provenance"):
            return origin["provenance"]
        if origin.get("kind", "user") == "user":
            return {path: {"kind": "user"} for path in flatten(row["snapshot"])}
        return {}

    def pending_confirmations(self) -> list[str]:
        """Critical inputs the user confirmed in this conversation whose value did not change, so they
        still need a new version to record the confirmation."""
        saved = self.persisted_provenance()
        return [path for path in sorted(CRITICAL)
                if (saved.get(path) or {}).get("kind") in UNCONFIRMED
                and (self.provenance.get(path) or {}).get("kind") not in UNCONFIRMED
                and get_path(self.draft, path) not in (None, [])
                and get_path(self.draft, path) == get_path(self.base, path)]

    def confirm_inputs(self, args) -> dict:
        """Record that the user confirmed the current value of critical inputs (e.g. a default)."""
        message_id = str(args.get("message_id") or "")
        if not self._is_user_message(message_id):
            return {"error": "message_id must be the user message where they confirmed the values"}
        confirmed, errors = [], []
        for path in args.get("paths") or []:
            if path not in CRITICAL:
                errors.append(f"{path}: only critical inputs need confirmation ({sorted(CRITICAL)})")
            elif get_path(self.draft, path) in (None, []):
                errors.append(f"{path}: has no value to confirm; set it with set_fields")
            else:
                self.provenance[path] = {"kind": "user", "ref": message_id, "note": "Confirmado por el usuario"}
                confirmed.append({"path": path, "value": get_path(self.draft, path)})
        if confirmed:
            self._save()
            self.runs.progress(self.run["id"], EventType.TOOL_CALLED, f"Registré {len(confirmed)} dato(s) confirmado(s)",
                               payload={"paths": [c["path"] for c in confirmed], "message_id": message_id})
        return {"confirmed": confirmed, "errors": errors,
                "next": "Call request_potential_calculation (it saves the confirmation) or apply_changes"}

    def _save(self):
        self.runs.save_workspace(self.run["id"], artifact_id=self.artifact_id, base_version=self.base_version,
                                 draft_snapshot={"artifact_id": self.artifact_id, "base_version": self.base_version,
                                                 "base": self.base, "snapshot": self.draft,
                                                 "provenance": self.provenance, "sounding": self.sounding})

    def artifacts_summary(self) -> list[dict]:
        return [{"artifact_id": row["artifact_id"], "name": row["name"], "version": row["version"],
                 "selected": row["artifact_id"] == self.artifact_id} for row in self.artifacts.values()]

    # Tools ----------------------------------------------------------------------------

    def get_draft(self, _args=None) -> dict:
        return {"artifact_id": self.artifact_id, "base_version": self.base_version,
                "is_new_artifact": self.artifact_id is None,
                "draft": {k: v for k, v in self.draft.items() if k != "compliance"},
                "provenance": self.provenance,
                "unconfirmed_critical": unconfirmed_critical(self.draft, self.provenance),
                "pending_changes": diff(self.base, self.draft)}

    def use_artifact(self, args) -> dict:
        artifact_id = args.get("artifact_id")
        if artifact_id not in self.artifacts:
            return {"error": "Unknown artifact id", "artifacts": self.artifacts_summary()}
        if self.artifact_id and self.artifact_id != artifact_id:
            return {"error": "This conversation already works on another artifact; the user changes it"}
        self._load(artifact_id)
        with self.store.transaction(write=True) as db:
            conversation = db.one("conversations", id=self.run["conversation_id"])
            self.runs.ensure_state(db, conversation)
            db.change("agent_conversation_state", conversation["id"], artifact_id=artifact_id)
        self._save()
        return self.get_draft()

    def set_fields(self, args, allowed=None) -> dict:
        """Apply changes to the draft. `geometry.rods` also accepts a layout
        {"pattern", "spacing_x_m", "spacing_y_m"} that is expanded on the updated grid, and
        `geometry.conductors` a grid inside chosen intervenible areas
        {"pattern": "areas", "areas", "spacing_x_m", "spacing_y_m", "bounds"?} (see grid_in_areas)."""
        applied, errors, layouts, grids = [], [], [], []
        for change in args.get("changes") or []:
            path, value = change.get("path"), change.get("value")
            try:
                if allowed and not any(path == p or (p.endswith(".") and str(path).startswith(p)) for p in allowed):
                    raise PatchError(f"{path} is outside this agent's scope")
                entry = check_change(path, change.get("source") or {},
                                     draft=(change.get("source") or {}).get("draft") is True)
                if entry["kind"] == "user" and not self._is_user_message(entry["ref"]):
                    raise PatchError(f"{path}: {entry['ref']} is not a user message of this conversation")
            except PatchError as exc:
                errors.append(str(exc))
                continue
            if path == "geometry.rods" and isinstance(value, dict):
                layouts.append((value, entry))
                continue
            if path == "geometry.conductors" and isinstance(value, dict):
                grids.append((value, entry))
                continue
            section, _, field = path.partition(".")
            if field and section in FIELD_NAMES and field not in FIELD_NAMES[section]:
                errors.append(f"{path}: unknown field; {section} has {sorted(FIELD_NAMES[section])}")
                continue
            candidate = set_path(self.draft, path, value)
            if section in SECTION_MODELS:
                try:
                    SECTION_MODELS[section].validate_python(candidate[section])
                except ValidationError as exc:
                    errors.append(f"{path}: not applied, " + "; ".join(_errors(exc)))
                    continue
            self.draft = candidate
            self.provenance[path] = entry
            applied.append(path)
        for layout, entry in grids:  # before the rods, which are placed on the conductors
            result = self.grid_in_areas(layout)
            if "error" in result:
                errors.append(f"geometry.conductors: {result['error']}")
                continue
            self.provenance["geometry.conductors"] = {**entry, "note": entry.get("note") or result["note"]}
            applied.append("geometry.conductors")
        if not layouts and self.pending_layout and any(p.startswith("geometry.") for p in applied):
            layouts = [self.pending_layout]  # the grid changed: place the rods that could not be placed before
        for layout, entry in layouts:
            try:
                rods = rod_layout(str(layout.get("pattern")), self.draft.get("geometry") or {},
                                  layout.get("spacing_x_m"), layout.get("spacing_y_m"), layout.get("count"))
            except (KeyError, TypeError, ZeroDivisionError):
                self.pending_layout = (layout, entry)
                errors.append("geometry.rods: set the outline and the conductor spacing (or the conductors) first; "
                              "the layout is kept and placed as soon as the grid allows it")
                continue
            except ValueError as exc:
                self.pending_layout = (layout, entry)
                errors.append(f"geometry.rods: {exc}; the layout is kept and placed as soon as the grid allows it")
                continue
            self.pending_layout = None
            self.draft = set_path(self.draft, "geometry.rods", rods)
            self.provenance["geometry.rods"] = {**entry, "note": entry.get("note") or f"Patrón {layout.get('pattern')}"}
            applied.append("geometry.rods")
        if applied:
            self._save()
            self.runs.progress(self.run["id"], EventType.TOOL_CALLED,
                               f"Actualicé {len(applied)} campo(s) del borrador",
                               payload={"paths": applied, "reason": str(args.get("reason") or "")[:300]})
        return {"applied": applied, "errors": errors}

    def _set_conductors(self, conductors: list[dict], ref: str, note: str) -> dict:
        self.draft = set_path(self.draft, "geometry.conductors", conductors)
        self.provenance["geometry.conductors"] = {"kind": "tool", "ref": ref, "note": note[:300]}
        self._save()
        problems = [p for p in geometry_problems(self.draft.get("geometry") or {}) if "rods" in p]
        return {"conductors": len(conductors), "conductor_list": conductors, "rod_problems": problems}

    def explode_grid(self, _args=None) -> dict:
        """Turn the regular grid into explicit conductors so individual lines can be edited."""
        geometry = self.draft.get("geometry") or {}
        if geometry.get("conductors"):
            return {"conductors": len(geometry["conductors"]), "conductor_list": geometry["conductors"],
                    "note": "The grid was already drawn conductor by conductor"}
        try:
            conductors = explicit_conductors(geometry)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return {"error": "Set the outline and the spacing first"}
        return self._set_conductors(conductors, "explode_grid", "Retícula regular convertida en conductores")

    def clip_zone(self, args) -> dict:
        """Remove the conductor parts inside a rectangular zone, keeping the zone's outline."""
        geometry = self.draft.get("geometry") or {}
        base = geometry.get("conductors") or None
        try:
            conductors = base or explicit_conductors(geometry)
            clipped = clip_conductors(conductors, float(args["x_min"]), float(args["x_max"]),
                                      float(args["y_min"]), float(args["y_max"]))
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            return {"error": str(exc) or "Invalid zone"}
        zone = f"x {args['x_min']:g}–{args['x_max']:g} m, y {args['y_min']:g}–{args['y_max']:g} m"
        return self._set_conductors(clipped, f"clip_zone({zone})", f"Conductores interiores retirados en {zone}")

    def grid_in_areas(self, args) -> dict:
        """Draw a regular grid inside the chosen intervenible areas (or part of them)."""
        geometry = self.draft.get("geometry") or {}
        try:
            conductors = area_grid(geometry, float(args["spacing_x_m"]), float(args["spacing_y_m"]),
                                   args.get("areas") or None, args.get("bounds") or None)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            return {"error": str(exc) or "Invalid spacing"}
        spacing = f"{float(args['spacing_x_m']):g} × {float(args['spacing_y_m']):g} m"
        where = ", ".join(str(a) for a in args.get("areas") or []) or "el área intervenible"
        note = f"Retícula de {spacing} en {where}"
        result = self._set_conductors(conductors, f"grid_in_areas({spacing}; {where})", note)
        return {**result, "note": note, "warnings": [w["message"] for w in geometry_warnings(self.draft["geometry"])]}

    # Soil ---------------------------------------------------------------------------

    def storage(self):
        if self._storage is None:
            from src.infrastructure.storage.object_storage import ObjectStorage

            self._storage = ObjectStorage()
        return self._storage

    def soil_state(self, _args=None) -> dict:
        return {"soil_layers": self.draft.get("soil_layers") or [],
                "soil_measurements": self.draft.get("soil_measurements"),
                "provenance": {k: v for k, v in self.provenance.items() if k.startswith("soil")},
                "staged_sounding": self.sounding,
                "fits": {str(n): self._fit_summary(fit) for n, fit in self.fits.items()}}

    def user_messages(self, limit: int = 5) -> list[dict]:
        with self.store.transaction() as db:
            rows = db.many("chat_messages", conversation_id=self.run["conversation_id"], source="user", limit=None)
        return [{"message_id": m["id"], "text": m["text"]} for m in sorted(rows, key=message_order)[-limit:]]

    def read_user_message(self, args) -> dict:
        with self.store.transaction() as db:
            message = db.one("chat_messages", id=str(args.get("message_id")), conversation_id=self.run["conversation_id"])
        if not message or message["source"] != "user":
            return {"error": "Not a user message of this conversation"}
        return {"message_id": message["id"], "text": message["text"]}

    def list_tables(self, _args=None) -> dict:
        with self.store.transaction() as db:
            uploads = db.many("file_uploads", project_id=self.run["project_id"], status="available", limit=None)
        return {"files": [{"upload_id": u["id"], "filename": u["filename"], "mime_type": u["expected_mime"]}
                          for u in uploads if u["expected_mime"] in TABLE_MIMES]}

    def _table(self, upload_id: str) -> list[dict]:
        with self.store.transaction() as db:
            upload = db.one("file_uploads", id=str(upload_id), project_id=self.run["project_id"], status="available")
        if not upload or upload["expected_mime"] not in TABLE_MIMES:
            raise ValueError("Not an available CSV/XLSX file of this project")
        data = self.storage().read_object(upload["target_bucket"], upload["object_key"], MAX_TABLE_BYTES)
        return measurement_tables.read_table(data, upload["expected_mime"])

    def preview_table(self, args) -> dict:
        try:
            return {"sheets": measurement_tables.preview(self._table(args["upload_id"]))}
        except (KeyError, ValueError) as exc:
            return {"error": str(exc)}

    def _stage(self, array: str, quantity: str, readings: list[dict], source: dict) -> dict:
        staged, errors = [], []
        for index, reading in enumerate(readings):
            try:
                spacing, value = float(reading["spacing_m"]), float(reading["value"])
                potential = reading.get("potential_spacing_m")
                potential = float(potential) if potential not in (None, "") else None
                rho = value if quantity == "resistivity" else apparent_resistivity(array, spacing, value, potential)
                if spacing <= 0 or rho <= 0:
                    raise ValueError("values must be positive")
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"reading {index + 1}: {exc}")
                continue
            entry = {"spacing_m": spacing, "apparent_resistivity_ohm_m": round(rho, 6)}
            if potential is not None:
                entry["potential_spacing_m"] = potential
            staged.append(entry)
        if errors:
            return {"error": "Some readings are invalid", "errors": errors}
        if len(staged) < 4:
            return {"error": f"A fit needs at least 4 readings; got {len(staged)}"}
        self.sounding = {"array": array, "quantity": quantity, "readings": staged, "source": source}
        self.fits = {}
        self._save()
        self.runs.progress(self.run["id"], EventType.TOOL_CALLED, f"Leí {len(staged)} mediciones {array}",
                           payload={"source": source})
        return {"staged": len(staged), "readings": staged}

    def stage_from_message(self, args) -> dict:
        message_id, readings = str(args.get("message_id")), args.get("readings") or []
        with self.store.transaction() as db:
            message = db.one("chat_messages", id=message_id, conversation_id=self.run["conversation_id"])
        if not message or message["source"] != "user":
            return {"error": "message_id must be a user message of this conversation"}
        numbers = [float(r[k]) for r in readings for k in ("spacing_m", "value", "potential_spacing_m")
                   if isinstance(r, dict) and r.get(k) not in (None, "")]
        missing = missing_in_text(numbers, message["text"])
        if missing:
            return {"error": "These values do not appear in the user's message; copy the readings exactly",
                    "not_found": missing}
        return self._stage(str(args.get("array")), str(args.get("quantity")), readings,
                           {"kind": "user", "ref": message_id})

    def stage_from_table(self, args) -> dict:
        try:
            sheets = self._table(args["upload_id"])
            extracted = measurement_tables.extract(
                sheets, sheet=args.get("sheet"), spacing_column=args["spacing_column"],
                value_column=args["value_column"], potential_column=args.get("potential_column"),
                first_row=int(args["first_row"]), last_row=int(args["last_row"]),
                decimal=args.get("decimal") or "auto")
        except (KeyError, TypeError, ValueError) as exc:
            return {"error": str(exc)}
        result = self._stage(str(args.get("array")), str(args.get("quantity")), extracted["readings"],
                             {"kind": "document", "ref": str(args["upload_id"]),
                              "note": f"{extracted['sheet']} filas {args['first_row']}–{args['last_row']}"})
        return {**result, "skipped_rows": extracted["skipped_rows"]}

    def stage_from_artifact(self, _args=None) -> dict:
        measurements = self.draft.get("soil_measurements")
        if not measurements:
            return {"error": "The artifact has no stored measurements"}
        readings = [{"spacing_m": m["spacing_m"], "value": m["apparent_resistivity_ohm_m"],
                     "potential_spacing_m": m.get("potential_spacing_m")} for m in measurements["measurements"]]
        source = self.provenance.get("soil_measurements") or {"kind": "document", "ref": "artifact"}
        return self._stage(measurements["array"], "resistivity", readings, source)

    @staticmethod
    def _fit_summary(fit: dict) -> dict:
        return {k: fit[k] for k in ("layer_count", "soil_layers", "rms_error_percent", "relative_uncertainty_percent",
                                    "uniform_resistivity_ohm_m", "uniform_rms_error_percent", "excluded", "warnings")}

    def fit_soil(self, args) -> dict:
        if not self.sounding:
            return {"error": "Stage the readings first"}
        counts = sorted({int(n) for n in (args.get("layer_counts") or [2])})
        threshold = float(args.get("outlier_threshold") or 0.15)
        results = {}
        for count in counts:
            if not 2 <= count <= 8:
                results[str(count)] = {"error": "layer_count must be between 2 and 8"}
                continue
            try:
                fit = fit_sounding(self.sounding["readings"], self.sounding["array"], count, threshold)
            except (ValueError, ArithmeticError) as exc:
                results[str(count)] = {"error": str(exc)}
                continue
            fit["outlier_threshold"] = threshold
            self.fits[count] = fit
            results[str(count)] = self._fit_summary(fit)
        self.runs.progress(self.run["id"], EventType.TOOL_CALLED, f"Ajusté el sondeo a {', '.join(map(str, counts))} capas",
                           payload={"layer_counts": counts})
        return {"fits": results}

    def lookup_material(self, args) -> dict:
        value = args.get("resistivity_ohm_m")
        return {"materials": soil_materials.search(args.get("query") or None,
                                                   float(value) if value not in (None, "") else None),
                "note": "Indicative values: never use them as soil data without the user's confirmation"}

    def apply_soil_model(self, layer_count: int, rationale: str) -> dict:
        fit = self.fits.get(int(layer_count))
        if not fit or not self.sounding:
            return {"error": f"There is no fit with {layer_count} layers; run fit_soil first"}
        self.draft = set_path(self.draft, "soil_measurements", {
            "array": self.sounding["array"], "measurements": self.sounding["readings"],
            "outlier_threshold": fit["outlier_threshold"], "layer_count": int(layer_count)})
        self.provenance["soil_measurements"] = dict(self.sounding["source"])
        layers = [{**layer, "material": None} for layer in fit["soil_layers"]]
        self.draft = set_path(self.draft, "soil_layers", layers)
        self.provenance["soil_layers"] = {
            "kind": "tool", "ref": f"fit_sounding:{layer_count}",
            "note": f"Ajuste {fit['forward_model']}, RMS {fit['rms_error_percent']:.2f} %. {rationale}"[:300]}
        self._save()
        return {"applied": ["soil_measurements", "soil_layers"], "soil_layers": layers,
                "rms_error_percent": fit["rms_error_percent"], "warnings": fit["warnings"]}

    def _is_user_message(self, message_id) -> bool:
        with self.store.transaction() as db:
            message = db.one("chat_messages", id=str(message_id), conversation_id=self.run["conversation_id"])
        return bool(message and message["source"] == "user")

    def validate(self, _args=None) -> dict:
        try:
            normalized = GroundingArtifactRequest.model_validate(self.draft).model_dump(mode="json")
            if normalized.get("schema_version") == "1.0":
                for key in ("buildings", "networks", "electrodes"):
                    normalized.pop(key, None)
            else:
                normalized.pop("geometry", None)
        except ValidationError as exc:
            return {"valid": False, "errors": _errors(exc)}
        return {"valid": True, "errors": [], "normalized": normalized,
                "warnings": [w["message"] for w in geometry_warnings(normalized.get("geometry") or {})],
                "unconfirmed_critical": unconfirmed_critical(normalized, self._provenance_for(normalized)),
                "missing_for_calculation": missing_for_calculation(normalized)}

    def validate_tool(self, _args=None) -> dict:
        if not self.draft.get("name") and self.draft:
            self._default_name()
            self._save()
        return {k: v for k, v in self.validate().items() if k != "normalized"}

    def request_calculation(self, args=None) -> dict:
        """Validate the exact persisted artifact version and create its calculation.

        The worker is dispatched by `run_step` only after the run is suspended, so the result always
        resumes the run; the orchestrator then reads it in `finished_calculation`.
        """
        if self.queued_calculation:
            return {"queued": False, "suggestion": "Ya hay un cálculo encolado en este paso; termina con waits_for 'calculation'."}
        check = self.validate()
        if not check["valid"]:
            return {"queued": False, "errors": check["errors"], "suggestion": "Corrige los errores del artefacto antes de calcular."}
        if check["missing_for_calculation"]:
            return {"queued": False, "missing": check["missing_for_calculation"],
                    "suggestion": "Pide al usuario los datos faltantes o complétalos desde una fuente confirmada."}
        if check["unconfirmed_critical"]:
            return {"queued": False, "unconfirmed_critical": check["unconfirmed_critical"],
                    "current_values": {p: get_path(check["normalized"], p) for p in check["unconfirmed_critical"]},
                    "suggestion": "If the user already confirmed these values in a message, call confirm_inputs with "
                                  "those paths and that message_id, then call request_potential_calculation again. "
                                  "Otherwise ask the user to confirm them or give other values (set_fields)."}
        if not self.artifact_id or self.base_version is None:
            return {"queued": False, "suggestion": "Guarda primero el borrador como una versión del artefacto."}
        if diff(self.base, check["normalized"]):
            return {"queued": False, "suggestion": "Aplica primero los cambios del borrador para calcular la versión persistida."}
        if self.pending_confirmations():
            # The user confirmed defaults without changing them: record it in a version before calculating.
            saved = self.apply({"summary": "Confirmación de datos críticos para el cálculo"})
            if "error" in saved:
                return {"queued": False, "errors": [saved["error"]], "suggestion": "No se pudo guardar la confirmación."}
        options = {k: v for k, v in (args or {}).items() if v not in (None, [], "") and k not in
                   {"split_factor", "split_factor_origin"}}
        if (args or {}).get("split_factor") not in (None, ""):
            options["fault_split"] = {"split_factor": args["split_factor"],
                                      "split_factor_origin": str(args.get("split_factor_origin") or "Indicado por el usuario")}
        try:
            parameters = PotentialCalculationRequest.model_validate(options).model_dump()
        except ValidationError as exc:
            return {"queued": False, "errors": _errors(exc), "suggestion": "Corrige los parámetros del cálculo."}
        with self.store.transaction() as db:
            done = [row for row in db.many("calculos_potencial_tierras", project_id=self.run["project_id"],
                                           artifact_id=self.artifact_id, artifact_version=self.base_version)
                    if row["status"] == "completed" and _solver_inputs(row["parameters"]) == _solver_inputs(parameters)]
        if done:
            # The solver is deterministic: the same version and parameters give the same result.
            latest = max(done, key=lambda row: row["updated_at"])
            return {"queued": False, "already_calculated": True, "calculation_id": latest["id"],
                    "version": self.base_version, "result": summarize_calculation(latest),
                    "suggestion": "This version was already calculated with these parameters: report this result "
                                  "and do not wait for a calculation. To recalculate, change the design or the "
                                  "parameters first."}
        try:
            with self.store.transaction(write=True) as db:
                row = potential_calculations.create_calculation(db, self.run["project_id"], self.artifact_id,
                                                                self.base_version, parameters, self.run["created_by"])
        except potential_calculations.CalculationBlocked as exc:
            return {"queued": False, "detail": exc.detail,
                    "suggestion": "Completa o confirma lo indicado y guarda una nueva versión antes de calcular."}
        self.queued_calculation = row["id"]
        self.runs.progress(self.run["id"], EventType.CALCULATION_QUEUED,
                           f"Cálculo de seguridad encolado (versión {self.base_version})",
                           level=EventLevel.PROGRESS, payload={"calculation_id": row["id"]})
        return {"queued": True, "calculation_id": row["id"], "artifact_id": self.artifact_id,
                "version": self.base_version, "status": "pending",
                "parameters": {k: parameters[k] for k in ("safety_standards", "x_over_r", "system_frequency_hz",
                                                          "fault_split", "discretization_m")},
                "next": "Termina ahora con respond_to_user waits_for 'calculation'; se te reanudará con el resultado."}

    def calculation_result(self) -> dict | None:
        calculation_id = self.run.get("pending_calculation_id")
        if not calculation_id:
            return None
        with self.store.transaction() as db:
            row = db.one("calculos_potencial_tierras", id=calculation_id, project_id=self.run["project_id"])
        return summarize_calculation(row) if row and row["status"] not in {"pending", "running"} else None

    def _provenance_for(self, normalized: dict) -> dict:
        provenance = dict(self.provenance)
        for path in flatten(normalized):
            provenance.setdefault(path, {"kind": "schema_default", "ref": None} if path not in flatten(self.base)
                                  else None)
        return {path: entry for path, entry in provenance.items() if entry is not None}

    def _default_name(self) -> None:
        """The name is never worth a question: derive one from the grid as an assumption."""
        if self.draft.get("name"):
            return
        geometry = self.draft.get("geometry") or {}
        size = (f" {geometry['length_m']:g} × {geometry['width_m']:g} m"
                if all(isinstance(geometry.get(k), (int, float)) for k in ("length_m", "width_m")) else "")
        self.draft = set_path(self.draft, "name", f"Malla de puesta a tierra{size}" if geometry
                              else "Diseño de puesta a tierra")
        self.provenance["name"] = {"kind": "assumption", "ref": None, "note": "Nombre generado"}

    def _drop_invalid_sections(self, errors: list[str]) -> dict:
        """Put the sections that fail validation back to the current version, so one bad section
        never blocks the rest of the work. Returns {section: errors} of what was left out."""
        skipped = {}
        for error in errors:
            skipped.setdefault(error.split(".")[0].split(":")[0], []).append(error)
        for section in skipped:
            if self.base and section in self.base:
                self.draft = set_path(self.draft, section, self.base[section])
            else:
                self.draft = {k: v for k, v in self.draft.items() if k != section}
            for path in [p for p in self.provenance if p.split(".")[0] == section]:
                previous = (((self.artifacts.get(self.artifact_id) or {}).get("origin") or {}).get("provenance")
                            or {}).get(path)
                if previous:
                    self.provenance[path] = previous
                else:
                    self.provenance.pop(path)
        self._save()
        return skipped

    def apply(self, args) -> dict:
        """Create the new artifact version from the draft; the user gets an `artifact.updated` card.

        Sections that do not validate are left at their current value and reported in `skipped`.
        """
        self._default_name()
        check = self.validate()
        skipped, kept = {}, (self.draft, dict(self.provenance))

        def keep_draft(result):
            # Nothing was saved: the draft stays as it was, so the work in progress is not lost.
            self.draft, self.provenance = kept
            self._save()
            return result

        if not check["valid"]:
            skipped = self._drop_invalid_sections(check["errors"])
            check = self.validate()
            if not check["valid"]:
                return keep_draft({"error": "The draft is not valid", "errors": check["errors"], "skipped": skipped})
        normalized = check["normalized"]
        changes = diff(self.base, normalized)
        confirmations = self.pending_confirmations()
        if not changes and not confirmations:
            return keep_draft({"error": "The draft has no changes against the current version", "skipped": skipped})
        provenance = self._provenance_for(normalized)
        # The card lists what the agent changed, not the fields the schema filled with defaults.
        shown = [c for c in changes if (provenance.get(c["path"]) or {}).get("kind") != "schema_default"]
        shown += [{"path": path, "before": get_path(normalized, path), "after": get_path(normalized, path),
                   "confirmed": True} for path in confirmations]
        if skipped and all(c["path"] == "name" for c in shown):
            return keep_draft({"error": "Nothing valid to save", "skipped": skipped})
        change = {"summary": str(args.get("summary") or "Cambios al artefacto")[:300], "artifact_id": self.artifact_id,
                  "base_version": self.base_version, "snapshot": normalized,
                  "provenance": provenance, "diff": shown,
                  "unconfirmed_critical": check["unconfirmed_critical"],
                  "missing_for_calculation": check["missing_for_calculation"],
                  "draft": bool(check["unconfirmed_critical"]),
                  "draft_watermark": (f"Borrador · {len(check['unconfirmed_critical'])} supuesto(s) sin confirmar"
                                      if check["unconfirmed_critical"] else None)}
        try:
            row = self.runs.apply_changes(self.run["id"], change)
        except ServiceError as exc:
            # Someone versioned the artifact meanwhile: rebase the draft on the latest version.
            with self.store.transaction() as db:
                latest = db.designs.latest(self.run["project_id"], self.artifact_id)
            self.artifacts[self.artifact_id] = latest
            pending = {c["path"]: c["after"] for c in changes}
            self._load(self.artifact_id)
            for path, value in pending.items():
                self.draft = set_path(self.draft, path, value)
            self._save()
            return {"error": f"{exc.message}; the draft was rebased on version {latest['version']}, "
                             "review it with get_draft and apply again"}
        self.artifact_id, self.base_version = row["artifact_id"], row["version"]
        self.base, self.draft = row["snapshot"], dict(row["snapshot"])
        self.provenance = dict(row["origin"]["provenance"])
        self.artifacts[row["artifact_id"]] = row
        self.applied = True
        return {"artifact_id": row["artifact_id"], "version": row["version"], "name": row["name"],
                "unconfirmed_critical": change["unconfirmed_critical"],
                "missing_for_calculation": change["missing_for_calculation"],
                "skipped": skipped or None}


def _field_guide() -> dict:
    return {"geometry": ArtifactGeometryRequest.model_json_schema(),
            "conductor": GroundingConductorRequest.model_json_schema()["properties"],
            "rod_layout_patterns": ["count", "corners", "perimeter_nodes", "grid_nodes", "lattice", "lattice_perimeter"]}


def run_grid_designer(client, prompts, workspace: ArtifactWorkspace, task: str, usage: dict) -> dict:
    """Subagent: returns geometry/conductor changes and applies them to the draft."""
    messages = [*prompts["grid_designer"], {"role": "user", "content": json.dumps({
        "task": task, "draft": workspace.get_draft(), "fields": _field_guide()}, ensure_ascii=False)}]
    submit = runtime.tool("submit_grid_design", "Return the field changes for the grid and conductor.", {
        "changes": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"},
            "value": {"type": ["number", "integer", "string", "array", "object"]},
            "source_kind": {"type": "string", "enum": ["user", "assumption"]},
            "message_id": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
        }, "required": ["path", "value", "source_kind", "message_id", "note"], "additionalProperties": False}},
        "rationale": {"type": "string"},
    }, ["changes", "rationale"])
    zone = {k: {"type": "number"} for k in ("x_min", "x_max", "y_min", "y_max")}
    tools = [runtime.tool("get_draft", "Current artifact draft.", {}, []),
             runtime.tool("explode_grid", "Convert the regular grid into explicit conductors (deterministic), "
                          "before editing individual lines.", {}, []),
             runtime.tool("clip_zone", "Remove the conductor parts inside a rectangular zone of the plan, keeping the "
                          "zone's border (deterministic). Use it for 'remove the interior conductors of ...'.",
                          zone, list(zone)),
             runtime.tool("grid_in_areas", "Redraw the grid inside the chosen intervenible areas of the draft, or "
                          "inside `bounds` within them, skipping structures and non-intervenible areas (deterministic).",
                          {"spacing_x_m": {"type": "number"}, "spacing_y_m": {"type": "number"},
                           "areas": {"type": "array", "items": {"type": "string"},
                                     "description": "Labels of the intervenible areas the grid uses"},
                           "bounds": {"type": ["object", "null"], "properties": zone}},
                          ["spacing_x_m", "spacing_y_m", "areas"]),
             submit]
    outcome = {}

    def finalize(args):
        changes = [{"path": c.get("path"), "value": c.get("value"),
                    "source": {"kind": c.get("source_kind"), "ref": c.get("message_id"), "note": c.get("note")}}
                   for c in args.get("changes") or []]
        result = workspace.set_fields({"changes": changes, "reason": args.get("rationale")}, allowed=DESIGNER_PATHS)
        if not result["errors"]:
            try:
                ArtifactGeometryRequest.model_validate(workspace.draft.get("geometry") or {})
            except ValidationError as exc:
                result["errors"] = [f"geometry.{error}" for error in _errors(exc)]
        outcome.update(result, rationale=args.get("rationale", ""))
        return not result["errors"], result

    runtime.run_tool_agent(client, model_for("AGENT_GRID_DESIGNER_MODEL"), messages, tools,
                           {"get_draft": workspace.get_draft, "explode_grid": workspace.explode_grid,
                            "clip_zone": workspace.clip_zone, "grid_in_areas": workspace.grid_in_areas},
                           "submit_grid_design", finalize, usage,
                           max_rounds=DESIGNER_ROUNDS)
    assumptions = [path for path in outcome.get("applied", [])
                   if (workspace.provenance.get(path) or {}).get("kind") == "assumption"]
    geometry = workspace.draft.get("geometry") or {}
    summary = {key: geometry.get(key) for key in ("length_m", "width_m", "conductor_spacing_m", "conductor_spacing_x_m",
                                                   "conductor_spacing_y_m", "burial_depth_m", "rod_length_m")}
    summary.update(conductors=len(geometry.get("conductors") or []) or "regular grid",
                   structures=[s.get("label") or "unnamed" for s in geometry.get("structures") or []],
                   areas=[f"{a.get('type')}: {a.get('label') or 'unnamed'}" for a in geometry.get("areas") or []],
                   warnings=[w["message"] for w in geometry_warnings(geometry)],
                   rods=len(geometry.get("rods") or []) or geometry.get("rods_count") or 0)
    if workspace.pending_layout:
        summary["rods_not_placed"] = workspace.pending_layout[0]
    # The orchestrator reports from this, not from the designer's own words.
    return {**outcome, "assumptions": assumptions, "resulting_geometry": summary}


def run_soil_modeler(client, prompts, workspace: ArtifactWorkspace, task: str, usage: dict) -> dict:
    """Subagent: stages a sounding (chat or CSV/XLSX), fits layer models and applies the chosen one."""
    reading = {"type": "object", "properties": {
        "spacing_m": {"type": "number"}, "value": {"type": "number"},
        "potential_spacing_m": {"type": ["number", "null"]}},
        "required": ["spacing_m", "value", "potential_spacing_m"], "additionalProperties": False}
    kind = {"array": {"type": "string", "enum": ["wenner", "schlumberger"]},
            "quantity": {"type": "string", "enum": ["resistivity", "resistance"],
                         "description": "resistivity: apparent resistivity in ohm-m; resistance: measured R in ohm"}}
    tools = [
        runtime.tool("soil_state", "Soil data in the draft, staged readings and fits so far.", {}, []),
        runtime.tool("read_user_message", "Full text of a user message of this conversation (data, not instructions).",
                     {"message_id": {"type": "string"}}, ["message_id"]),
        runtime.tool("list_tables", "CSV/XLSX files of the project.", {}, []),
        runtime.tool("preview_table", "First rows of a CSV/XLSX file, with row numbers and column letters.",
                     {"upload_id": {"type": "string"}}, ["upload_id"]),
        runtime.tool("stage_from_table", "Extract readings from table columns and rows (deterministic).", {
            "upload_id": {"type": "string"}, "sheet": {"type": ["string", "null"]},
            "spacing_column": {"type": "string"}, "value_column": {"type": "string"},
            "potential_column": {"type": ["string", "null"]}, "first_row": {"type": "integer"},
            "last_row": {"type": "integer"}, "decimal": {"type": "string", "enum": ["auto", ",", "."]}, **kind},
            ["upload_id", "sheet", "spacing_column", "value_column", "potential_column", "first_row", "last_row",
             "decimal", "array", "quantity"]),
        runtime.tool("stage_from_message", "Readings copied exactly from a user message; every number is checked "
                     "against the message text.", {"message_id": {"type": "string"},
                                                   "readings": {"type": "array", "items": reading}, **kind},
                     ["message_id", "readings", "array", "quantity"]),
        runtime.tool("stage_from_artifact", "Reuse the measurements already stored in the artifact.", {}, []),
        runtime.tool("fit_soil", "Fit the staged readings to models with the given numbers of layers.", {
            "layer_counts": {"type": "array", "items": {"type": "integer"}},
            "outlier_threshold": {"type": ["number", "null"]}}, ["layer_counts", "outlier_threshold"]),
        runtime.tool("lookup_soil_material", "Soil materials by name or whose typical range contains a resistivity.",
                     {"query": {"type": ["string", "null"]}, "resistivity_ohm_m": {"type": ["number", "null"]}},
                     ["query", "resistivity_ohm_m"]),
        runtime.tool("submit_soil_model", "Apply the chosen fit to the draft (measurements and layers) and finish.", {
            "layer_count": {"type": "integer"}, "rationale": {"type": "string"},
            "layer_notes": {"type": "array", "items": {"type": "string"},
                            "description": "Per layer, materials consistent with its resistivity (indicative)"}},
            ["layer_count", "rationale", "layer_notes"]),
    ]
    handlers = {"soil_state": workspace.soil_state, "list_tables": workspace.list_tables,
                "read_user_message": workspace.read_user_message,
                "preview_table": workspace.preview_table, "stage_from_table": workspace.stage_from_table,
                "stage_from_message": workspace.stage_from_message, "stage_from_artifact": workspace.stage_from_artifact,
                "fit_soil": workspace.fit_soil, "lookup_soil_material": workspace.lookup_material}
    messages = [*prompts["soil_modeler"], {"role": "user", "content": json.dumps({
        "task": task, "recent_user_messages": workspace.user_messages(), "soil": workspace.soil_state(),
        "files": workspace.list_tables()["files"]},
        ensure_ascii=False)}]
    outcome = {}

    def finalize(args):
        result = workspace.apply_soil_model(args.get("layer_count", 0), str(args.get("rationale") or ""))
        outcome.update(result, rationale=args.get("rationale", ""), layer_notes=args.get("layer_notes") or [])
        return "error" not in result, result

    runtime.run_tool_agent(client, model_for("AGENT_SOIL_MODELER_MODEL"), messages, tools, handlers,
                           "submit_soil_model", finalize, usage, max_rounds=SOIL_ROUNDS)
    return outcome


def run_safety_analyst(client, prompts, workspace: ArtifactWorkspace, result: dict, usage: dict) -> dict:
    """Subagent: explains a finished calculation and recommends the next design action.
    The verdict is copied from the deterministic summary, never decided by the model."""
    snapshot = workspace.draft
    context = {"calculation": result, "geometry": snapshot.get("geometry"), "soil_layers": snapshot.get("soil_layers"),
               "fault": snapshot.get("fault"), "conductor": snapshot.get("conductor")}
    messages = [*prompts["safety_analyst"], {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
    submit = runtime.tool("submit_safety_report", "Explain the result and recommend the next actions.", {
        "explanation": {"type": "string"}, "dominant_constraint": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}}},
        ["explanation", "dominant_constraint", "recommendations"])
    report = runtime.run_tool_agent(client, model_for("AGENT_SAFETY_ANALYST_MODEL"), messages, [submit], {},
                                    "submit_safety_report", lambda args: (True, {"ok": True}), usage, max_rounds=3)
    return {"verdict": result.get("verdict"), "summary": result, **report}


class GroundingDesignAgent:
    """Callable used by the worker: `agent(run, runs) -> StepOutcome`."""

    def __init__(self, store, client=None, prompts=None, storage=None):
        self.store, self._client, self._prompts, self._storage = store, client, prompts, storage

    def __call__(self, run, runs) -> StepOutcome:
        client = self._client or runtime.clients()[1]
        prompts = self._prompts or load_prompts()
        workspace = ArtifactWorkspace(self.store, runs, run, storage=self._storage)
        usage = runtime.new_usage()
        try:
            return self._orchestrate(client, prompts, workspace, run, runs, usage)
        finally:
            runs.add_usage(run["id"], {"prompt_tokens": usage["prompt_tokens"],
                                       "completion_tokens": usage["completion_tokens"],
                                       "llm_rounds": usage["rounds"]})

    def _history(self, run) -> list[dict]:
        with self.store.transaction() as db:
            messages = db.many("chat_messages", conversation_id=run["conversation_id"], limit=None)
        messages = sorted(messages, key=message_order)[-HISTORY_MESSAGES:]
        history = []
        for message in messages:
            if message["source"] == "user":
                history.append({"role": "user", "content": f"[mensaje {message['id']}] {message['text']}"})
            elif message["source"] == "agent":
                history.append({"role": "assistant", "content": message["text"]})
        return history

    def _project_context(self, run, workspace) -> dict:
        with self.store.transaction() as db:
            memory = db.one("project_context_memory", project_id=run["project_id"])
            files = db.many("file_uploads", project_id=run["project_id"], status="available", limit=None)
        context = {
            "mode": run["mode"],
            "artifacts": workspace.artifacts_summary(),
            "project_memory": memory or {"summary": "", "items": []},
            "sources": {"files": [{"upload_id": row["id"], "filename": row["filename"],
                                    "mime_type": row["expected_mime"]} for row in files]},
        }
        try:
            from src.infrastructure.persistence.knowledge_graph_store import Neo4jKnowledgeGraph
            graph = Neo4jKnowledgeGraph.from_env()
            if graph:
                try:
                    context["sources"]["knowledge_graph"] = graph.summary(run["project_id"])
                    claims = graph.list_claims(run["project_id"], limit=5000)["items"]
                    # PR-24: el orquestador recibe el resultado del mapeo completo, no una
                    # muestra arbitraria de 12 afirmaciones recientes.
                    context["sources"]["artifact_inputs"] = map_claims_to_artifact(claims)
                    context["sources"]["input_resolution"] = resolve_conflicts(claims)
                    context["sources"]["claims_count"] = len(claims)
                finally:
                    graph.close()
        except Exception:
            # Chat remains available when the optional graph service is offline.
            pass
        return context

    def _save_project_memory(self, run, args) -> dict:
        summary = str(args.get("summary") or "").strip()[:6000]
        items = args.get("items") or []
        if len(items) > 40:
            return {"error": "At most 40 memory items are allowed"}
        project_message_ids = set()
        with self.store.transaction() as db:
            conversations = db.many("conversations", project_id=run["project_id"], limit=None)
            for conversation in conversations:
                project_message_ids.update(row["id"] for row in db.many(
                    "chat_messages", conversation_id=conversation["id"], source="user", limit=None))
        normalized = []
        for item in items:
            kind = item.get("kind")
            text = str(item.get("text") or "").strip()[:1000]
            refs = list(dict.fromkeys(str(value) for value in (item.get("source_message_ids") or [])))
            if kind not in {"decision", "assumption", "open_question"} or not text or not refs:
                return {"error": "Each item needs a valid kind, text and at least one source message"}
            if any(ref not in project_message_ids for ref in refs):
                return {"error": "Memory sources must be user messages from this project"}
            normalized.append({"kind": kind, "text": text, "source_message_ids": refs})
        now = int(time())
        with self.store.transaction(write=True) as db:
            current = db.one("project_context_memory", project_id=run["project_id"])
            values = {"summary": summary, "items": normalized, "updated_at": now}
            if current:
                db.change("project_context_memory", run["project_id"], **values)
            else:
                db.add("project_context_memory", project_id=run["project_id"], **values)
        return {"saved": True, "items": len(normalized)}

    def _orchestrate(self, client, prompts, workspace, run, runs, usage) -> StepOutcome:
        mode = AgentMode(run["mode"])
        context = self._project_context(run, workspace)
        finished = workspace.calculation_result()
        if finished:
            context["finished_calculation"] = finished
            best_candidate = self._record_design_candidate(run, runs, finished)
            loop = self._automatic_iteration(client, prompts, workspace, run, runs, finished, mode, usage)
            if loop is not None:
                return loop
            context["design_loop"] = self._design_loop_context(run, finished, best_candidate)
        messages = [*prompts["orchestrator"],
                    {"role": "system", "content": "Context: " + json.dumps(context, ensure_ascii=False) +
                     "\nConstruction rule: when artifact_inputs contain confirmed values, build in this order: "
                     "map inputs, delegate soil_modeler for resistivity readings, delegate grid_designer for geometry, "
                     "apply the resulting draft, then request_potential_calculation. Do not ask the user to retype "
                     "a value already present in artifact_inputs; ask only for missing or conflicting inputs." +
                     "\nLong-term memory rule: reuse project_memory across all conversations." + (
                         "" if mode == AgentMode.CONSULTA else
                         " When the user confirms a durable decision, assumption or pending question, call "
                         "save_project_memory and preserve other still-valid items. Cite exact user message ids "
                         "from the history; never turn an unverified inference into a decision.")},
                    *self._history(run)]
        tools = [runtime.tool("get_draft", "Artifact draft, sources and unconfirmed critical inputs.", {}, []),
                 runtime.tool("validate_draft", "Validate the draft against the artifact schema.", {}, [])]
        tools.append(runtime.tool("lookup_soil_material", "Indicative resistivity of soil materials, by name or by "
                                  "a resistivity value.", {"query": {"type": ["string", "null"]},
                                                           "resistivity_ohm_m": {"type": ["number", "null"]}},
                                  ["query", "resistivity_ohm_m"]))
        handlers = {"get_draft": workspace.get_draft, "validate_draft": workspace.validate_tool,
                    "lookup_soil_material": workspace.lookup_material}
        if mode != AgentMode.CONSULTA:  # guardar memoria escribe en el proyecto
            tools.append(runtime.tool("save_project_memory", "Save the concise, durable project context after the user confirms an important decision, assumption or pending question. Keep only current information; cite user message ids exactly. Do not save guesses as facts.", {
                "summary": {"type": "string"},
                "items": {"type": "array", "items": {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": ["decision", "assumption", "open_question"]},
                    "text": {"type": "string"},
                    "source_message_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["kind", "text", "source_message_ids"], "additionalProperties": False}}},
                ["summary", "items"]))
            handlers["save_project_memory"] = lambda args: self._save_project_memory(run, args)
        source = {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["user", "assumption"]},
            "ref": {"type": ["string", "null"], "description": "User message id for kind user"},
            "note": {"type": ["string", "null"]},
            "draft": {"type": "boolean", "description": "Required for a visible critical assumption"}},
            "required": ["kind", "ref", "note"], "additionalProperties": False}
        if mode != AgentMode.CONSULTA:
            tools += [
                runtime.tool("use_artifact", "Select the project artifact this conversation works on.",
                             {"artifact_id": {"type": "string"}}, ["artifact_id"]),
                runtime.tool("set_fields", "Set draft fields. Paths: name, soil_layers (the whole list, top layer "
                             "first: {resistivity_ohm_m|null, depth_m, material|null} where depth_m is the THICKNESS of "
                             "that layer, not its depth from the surface, and the bottom layer has depth_m null), "
                             "geometry.<field>, conductor.<field>, fault.<field>.", {
                                 "changes": {"type": "array", "items": {"type": "object", "properties": {
                                     "path": {"type": "string"},
                                     "value": {"type": ["number", "integer", "string", "array", "object"]},
                                     "source": source}, "required": ["path", "value", "source"],
                                     "additionalProperties": False}},
                                 "reason": {"type": "string"}}, ["changes", "reason"]),
                runtime.tool("delegate_grid_designer", "Ask the grid designer to set geometry (outline, spacing per "
                             "axis or drawn conductors, rods) and conductor fields. Include the user's explicit values "
                             "and their message ids.", {"task": {"type": "string"}}, ["task"]),
                runtime.tool("delegate_soil_modeler", "Ask the soil modeler to read a resistivity sounding (pasted in "
                             "the chat or in a project CSV/XLSX), fit layered models and set soil_measurements and "
                             "soil_layers. Include the message id or file name.", {"task": {"type": "string"}},
                             ["task"]),
                runtime.tool("apply_changes", "Validate the draft and create the new artifact version now; the user "
                             "sees an 'artifact edited' card and the artifact view reloads.",
                             {"summary": {"type": "string"}}, ["summary"]),
                runtime.tool("confirm_inputs", "Record that the user confirmed the CURRENT value of critical inputs "
                             "(for example the default surface layer 3000 ohm-m / 0.1 m) in a message.", {
                                 "paths": {"type": "array", "items": {"type": "string"}},
                                 "message_id": {"type": "string"}}, ["paths", "message_id"]),
                runtime.tool("request_potential_calculation", "Run the grounding solver only after deterministic checks "
                             "confirm that the saved artifact is valid, complete, and has no unconfirmed critical inputs. "
                             "If blocked, return missing fields and a suggestion; if queued, finish with waits_for "
                             "'calculation' and you are resumed with the result. Optional values only when the user "
                             "gave them.", {
                                 "surface_spacing_m": {"type": "number", "enum": [0.25, 0.5, 1.0]},
                                 "justification": {"type": "string", "description": "Why the solver settings fit this artifact; stored in the calculation trace"},
                                 "estimate_uncertainty": {"type": "boolean"},
                                 "discretization_m": {"type": "number"},
                                 "safety_standards": {"type": "array", "items": {"type": "string"},
                                                      "description": "Default ['IEEE 80-2013']"},
                                 "x_over_r": {"type": "number"},
                                 "system_frequency_hz": {"type": "number", "enum": [50, 60]},
                                 "split_factor": {"type": "number", "description": "S_f, 0 < S_f <= 1"},
                                 "split_factor_origin": {"type": "string"}}, []),
            ]
            handlers.update(use_artifact=workspace.use_artifact, set_fields=workspace.set_fields,
                            apply_changes=workspace.apply, confirm_inputs=workspace.confirm_inputs,
                            request_potential_calculation=workspace.request_calculation,
                            delegate_grid_designer=lambda args: self._delegate(client, prompts, workspace, runs,
                                                                               run, args, usage),
                            delegate_soil_modeler=lambda args: self._delegate(client, prompts, workspace, runs, run,
                                                                              args, usage, soil=True))
        if finished:
            tools.append(runtime.tool("delegate_safety_analyst", "Have the safety analyst explain the finished "
                                      "calculation and recommend the next design actions.", {}, []))
            handlers["delegate_safety_analyst"] = lambda _args: self._analyze(client, prompts, workspace, runs, run,
                                                                             finished, usage)
        tools.append(runtime.tool("respond_to_user", "Finish this step with your message to the user.", {
            "text": {"type": "string"},
            "waits_for": {"type": "string", "enum": ["nothing", "answer", "calculation"],
                          "description": "'calculation' only right after request_potential_calculation queued one"}},
            ["text", "waits_for"]))

        reminded = []

        def finalize(args):
            if not str(args.get("text") or "").strip():
                return False, {"error": "The message is empty"}
            if args.get("waits_for") == "calculation" and not workspace.queued_calculation:
                return False, {"error": "No calculation was queued; call request_potential_calculation first or use "
                                        "another waits_for"}
            pending = diff(workspace.base, workspace.draft) or [{"path": p} for p in workspace.pending_confirmations()]
            if mode != AgentMode.CONSULTA and pending and not reminded:
                reminded.append(True)
                return False, {"error": "The draft has changes that were not applied: call apply_changes, or call "
                                        "respond_to_user again to leave them unapplied",
                               "pending_changes": [c["path"] for c in pending]}
            return True, {"ok": True}

        result = runtime.run_tool_agent(client, model_for("AGENT_ORCHESTRATOR_MODEL"), messages, tools, handlers,
                                        "respond_to_user", finalize, usage, max_rounds=ORCHESTRATOR_ROUNDS)
        text = str(result.get("text") or "").strip() or "Listo."
        if workspace.queued_calculation:
            # A queued calculation always suspends the run until its worker finishes.
            return StepOutcome(text, calculation_id=workspace.queued_calculation)
        return StepOutcome(text, wait_for_user=result.get("waits_for") == "answer")

    @staticmethod
    def _design_loop_context(run, finished, best_candidate=None) -> dict:
        usage = run.get("usage") or {}
        return {
            "mode": run.get("mode"),
            "iterations_used": int(usage.get("design_iterations", 0)),
            "max_iterations": max_design_iterations(),
            "best_candidate": best_candidate or usage.get("best_candidate"),
            "current_score": calculation_score(finished),
        }

    def _record_design_candidate(self, run, runs, finished) -> dict:
        """Keep the strongest result across suspended calculation steps."""
        score = calculation_score(finished)
        previous = (run.get("usage") or {}).get("best_candidate")
        if previous and previous.get("score", float("-inf")) >= score:
            return previous
        candidate = {
            "score": score,
            "verdict": finished.get("verdict"),
            "calculation_id": finished.get("calculation_id"),
            "artifact_version": finished.get("artifact_version"),
        }
        runs.set_usage_fields(run["id"], best_candidate=candidate)
        return candidate

    def _automatic_iteration(self, client, prompts, workspace, run, runs, finished, mode, usage):
        """Improve a failing autonomous design and suspend it on a new calculation."""
        if mode != AgentMode.AUTONOMO or finished.get("verdict") != "no_cumple":
            return None
        used = int((run.get("usage") or {}).get("design_iterations", 0))
        limit = max_design_iterations()
        if used >= limit:
            runs.progress(run["id"], EventType.STEP_COMPLETED,
                          f"Bucle automático detenido tras {used} iteración(es)",
                          level=EventLevel.WARNING,
                          payload={"reason": "iteration_limit", "iterations": used, "max_iterations": limit})
            return None
        iteration = used + 1
        runs.set_usage_fields(run["id"], design_iterations=iteration)
        runs.progress(run["id"], EventType.SUBAGENT_STARTED,
                      f"Iteración automática {iteration}/{limit}: ajustando la malla",
                      level=EventLevel.PROGRESS,
                      payload={"iteration": iteration, "max_iterations": limit})
        task = ("El cálculo no cumple. Mejora la geometría conservando todos los datos críticos y las restricciones "
                "del usuario. Prioriza la restricción dominante y aplica el cambio más conservador que pueda mejorar "
                f"el margen. Resultado determinista: {json.dumps(finished, ensure_ascii=False)}")
        designed = run_grid_designer(client, prompts, workspace, task, usage)
        if not designed.get("applied"):
            runs.progress(run["id"], EventType.SUBAGENT_COMPLETED,
                          "No se pudo proponer una mejora automática",
                          level=EventLevel.WARNING, payload={"iteration": iteration})
            return None
        saved = workspace.apply({"summary": f"Iteración automática {iteration}: mejora de seguridad"})
        if "error" in saved:
            runs.progress(run["id"], EventType.SUBAGENT_COMPLETED,
                          "La mejora automática no pudo guardarse",
                          level=EventLevel.WARNING,
                          payload={"iteration": iteration, "error": saved["error"]})
            return None
        queued = workspace.request_calculation({})
        if not queued.get("queued"):
            return StepOutcome("No pude recalcular la mejora automática: "
                               + "; ".join(queued.get("errors") or [queued.get("suggestion", "revisa los datos")]))
        runs.progress(run["id"], EventType.SUBAGENT_COMPLETED,
                      f"Iteración automática {iteration}/{limit} encolada",
                      level=EventLevel.SUCCESS,
                      payload={"iteration": iteration, "max_iterations": limit,
                               "artifact_version": saved["version"], "calculation_id": queued["calculation_id"]})
        return StepOutcome(f"Ajusté la malla en la iteración {iteration}/{limit} y lancé un nuevo cálculo.",
                           calculation_id=queued["calculation_id"])

    def _analyze(self, client, prompts, workspace, runs, run, finished, usage) -> dict:
        runs.progress(run["id"], EventType.SUBAGENT_STARTED, "Analista de seguridad trabajando",
                      level=EventLevel.PROGRESS, payload={"subagent": "safety_analyst"})
        report = run_safety_analyst(client, prompts, workspace, finished, usage)
        runs.progress(run["id"], EventType.SUBAGENT_COMPLETED, "Analista de seguridad terminó",
                      payload={"subagent": "safety_analyst", "verdict": report["verdict"]})
        return report

    def _delegate(self, client, prompts, workspace, runs, run, args, usage, soil=False) -> dict:
        if runs.cancelling(run["id"]):
            return {"error": "The run is being cancelled; finish now"}
        name, label, worker = (("soil_modeler", "Modelador de suelo", run_soil_modeler) if soil
                               else ("grid_designer", "Diseñador de malla", run_grid_designer))
        runs.progress(run["id"], EventType.SUBAGENT_STARTED, f"{label} trabajando",
                      level=EventLevel.PROGRESS, payload={"subagent": name})
        result = worker(client, prompts, workspace, str(args.get("task") or ""), usage)
        runs.progress(run["id"], EventType.SUBAGENT_COMPLETED, f"{label} terminó",
                      payload={"subagent": name, "applied": result.get("applied", [])})
        return result
