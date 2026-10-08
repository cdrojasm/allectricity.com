"""Taxonomía del grafo de puesta a tierra (borrador v1, pendiente de revisión especialista).

Es la única fuente de verdad sobre qué tipos de nodo, relaciones y atributos puede
proponer la extracción documental. El contrato JSON, las validaciones y el prompt
del extractor se derivan de aquí, de modo que el LLM nunca crea tipos arbitrarios.
"""

from dataclasses import dataclass, field

# Cambia con cualquier ajuste de tipos, relaciones, atributos o unidades; entra en el ID de
# ejecución para que reprocesar con otra taxonomía cree una ejecución nueva.
TAXONOMY_VERSION = "taxonomy/1.1"

# Categorías: objeto físico, dato medido, escenario/supuesto y salida calculada.
PHYSICAL, MEASUREMENT, SCENARIO, CALCULATED = "physical", "measurement", "scenario", "calculated"
# Orígenes admitidos de un nodo; los resultados de cálculo solo llegan del solver.
LLM, USER, IMPORT, SOLVER = "llm", "user", "import", "solver"


@dataclass(frozen=True)
class EntityType:
    name: str
    area: str
    category: str
    origins: frozenset = frozenset({LLM, USER, IMPORT})

    @property
    def llm_extractable(self) -> bool:
        return LLM in self.origins


def _entities(area, category, *names, origins=frozenset({LLM, USER, IMPORT})):
    return {name: EntityType(name, area, category, origins) for name in names}


ENTITY_TYPES: dict[str, EntityType] = {
    **_entities("installation", PHYSICAL, "Site", "Substation", "Zone", "Structure"),
    **_entities("topology", PHYSICAL, "Transformer", "Busbar", "Feeder", "Circuit", "Breaker",
                "ElectricalPanel", "Motor", "PowerSource", "ConnectionPoint"),
    **_entities("grounding", PHYSICAL, "GroundingSystem", "GroundingGrid", "GridConductor",
                "RodElectrode", "DownConductor", "Fence", "BondingConnection"),
    **_entities("soil", MEASUREMENT, "SoilSurvey", "ResistivityReading"),
    **_entities("soil", CALCULATED, "SoilModel", "SoilLayer"),
    **_entities("fault", SCENARIO, "FaultScenario"),
    **_entities("analysis", CALCULATED, "DesignVersion", "CalculationRun", "CalculationResult",
                origins=frozenset({SOLVER, IMPORT})),
}

INSTALLATION = frozenset({"Site", "Substation", "Zone"})
TOPOLOGY = frozenset(t for t, spec in ENTITY_TYPES.items() if spec.area == "topology")
GROUNDING = frozenset(t for t, spec in ENTITY_TYPES.items() if spec.area == "grounding")
PHYSICAL_TYPES = frozenset(t for t, spec in ENTITY_TYPES.items() if spec.category == PHYSICAL)


@dataclass(frozen=True)
class RelationRule:
    name: str
    sources: frozenset
    targets: frozenset
    symmetric: bool = False
    origins: frozenset = frozenset({LLM, USER, IMPORT})

    def allows(self, source_type: str, target_type: str) -> bool:
        if source_type in self.sources and target_type in self.targets:
            return True
        return self.symmetric and target_type in self.sources and source_type in self.targets

    @property
    def llm_extractable(self) -> bool:
        return LLM in self.origins


RELATION_RULES: dict[str, RelationRule] = {rule.name: rule for rule in (
    RelationRule("CONTAINS", INSTALLATION, PHYSICAL_TYPES - {"Site"}),
    RelationRule("LOCATED_AT", PHYSICAL_TYPES | {"SoilSurvey"}, INSTALLATION),
    RelationRule("CONNECTED_TO", TOPOLOGY, TOPOLOGY, symmetric=True),
    RelationRule("SUPPLIES", frozenset({"Transformer", "Busbar", "Feeder", "Circuit",
                                        "PowerSource", "ElectricalPanel"}),
                 TOPOLOGY - {"PowerSource", "Breaker"}),
    RelationRule("PROTECTED_BY", TOPOLOGY - {"Breaker"}, frozenset({"Breaker"})),
    RelationRule("PART_OF", GROUNDING | frozenset({"ResistivityReading", "SoilLayer"}),
                 frozenset({"GroundingSystem", "GroundingGrid", "SoilSurvey", "SoilModel"})),
    RelationRule("BONDED_TO", GROUNDING | TOPOLOGY | frozenset({"Structure"}),
                 GROUNDING, symmetric=True),
    RelationRule("TERMINATES_AT", frozenset({"DownConductor", "GridConductor"}),
                 frozenset({"RodElectrode", "GroundingGrid", "ConnectionPoint", "Structure"})),
    RelationRule("JOINS", frozenset({"BondingConnection"}),
                 frozenset({"GridConductor", "RodElectrode", "DownConductor"})),
    RelationRule("MEASURED_AT", frozenset({"SoilSurvey", "ResistivityReading"}), INSTALLATION),
    RelationRule("FITTED_AS", frozenset({"SoilSurvey"}), frozenset({"SoilModel"})),
    RelationRule("APPLIES_TO", frozenset({"FaultScenario"}),
                 INSTALLATION | frozenset({"GroundingSystem", "GroundingGrid", "Transformer",
                                           "Busbar"})),
    # Relaciones de análisis: solo las crea la sincronización con diseño/solver.
    RelationRule("EVALUATES", frozenset({"CalculationRun"}), frozenset({"DesignVersion"}),
                 origins=frozenset({SOLVER})),
    RelationRule("USES_SCENARIO", frozenset({"CalculationRun"}), frozenset({"FaultScenario"}),
                 origins=frozenset({SOLVER})),
    RelationRule("PRODUCES", frozenset({"CalculationRun"}), frozenset({"CalculationResult"}),
                 origins=frozenset({SOLVER})),
)}

# Unidad literal (en minúsculas) -> (dimensión, unidad canónica, factor a SI).
UNITS: dict[str, tuple[str, str, float]] = {
    "v": ("voltage", "V", 1.0), "kv": ("voltage", "V", 1e3),
    "a": ("current", "A", 1.0), "ka": ("current", "A", 1e3),
    "w": ("active_power", "W", 1.0), "kw": ("active_power", "W", 1e3),
    "va": ("apparent_power", "VA", 1.0), "kva": ("apparent_power", "VA", 1e3),
    "s": ("time", "s", 1.0), "ms": ("time", "s", 1e-3),
    "hz": ("frequency", "Hz", 1.0),
    "ω": ("resistance", "ohm", 1.0), "ohm": ("resistance", "ohm", 1.0),
    "ohms": ("resistance", "ohm", 1.0), "ohmios": ("resistance", "ohm", 1.0),
    "kω": ("resistance", "ohm", 1e3),
    "ω·m": ("resistivity", "ohm·m", 1.0), "ω.m": ("resistivity", "ohm·m", 1.0),
    "ωm": ("resistivity", "ohm·m", 1.0), "ω-m": ("resistivity", "ohm·m", 1.0),
    "ω m": ("resistivity", "ohm·m", 1.0), "ohm·m": ("resistivity", "ohm·m", 1.0),
    "ohm-m": ("resistivity", "ohm·m", 1.0), "ohm.m": ("resistivity", "ohm·m", 1.0),
    "ohm m": ("resistivity", "ohm·m", 1.0), "ohmios-m": ("resistivity", "ohm·m", 1.0),
    "kω·m": ("resistivity", "ohm·m", 1e3),
    "m": ("length", "m", 1.0), "cm": ("length", "m", 1e-2), "mm": ("length", "m", 1e-3),
    "km": ("length", "m", 1e3), "ft": ("length", "m", 0.3048), "in": ("length", "m", 0.0254),
    "mm2": ("area", "m²", 1e-6), "mm²": ("area", "m²", 1e-6), "m2": ("area", "m²", 1.0),
    "m²": ("area", "m²", 1.0), "kcmil": ("area", "m²", 0.506707479e-6),
    "%": ("ratio", "1", 1e-2), "p.u.": ("ratio", "1", 1.0), "pu": ("ratio", "1", 1.0),
    "": ("ratio", "1", 1.0),
}
# Unidades donde «m» (mili) y «M» (mega) cambian el valor, tal como se escriben. Se buscan
# respetando la mayúscula del prefijo: «mV» ≠ «MV»; «mva» (miliVA) no se acepta.
PREFIXED_UNITS: dict[str, tuple[str, str, float]] = {
    "mV": ("voltage", "V", 1e-3), "MV": ("voltage", "V", 1e6),
    "mA": ("current", "A", 1e-3),
    "mW": ("active_power", "W", 1e-3), "MW": ("active_power", "W", 1e6),
    "MVA": ("apparent_power", "VA", 1e6),
    "mΩ": ("resistance", "ohm", 1e-3), "MΩ": ("resistance", "ohm", 1e6),
}
_PREFIXED_KEYS = {unit[0] + unit[1:].casefold(): spec for unit, spec in PREFIXED_UNITS.items()}
_PREFIX_SENSITIVE = {unit.casefold() for unit in PREFIXED_UNITS}


@dataclass(frozen=True)
class AttributeSpec:
    name: str
    dimensions: tuple  # vacío = atributo de texto
    subjects: frozenset
    feeds_calculation: bool = False
    si_range: tuple | None = None  # (mínimo, máximo) inclusivos en SI
    choices: tuple = ()
    description: str = ""

    @property
    def is_quantity(self) -> bool:
        return bool(self.dimensions)


ALL = frozenset(t for t, spec in ENTITY_TYPES.items() if spec.llm_extractable)
SOIL_MODEL_SUBJECTS = frozenset({"SoilModel", "Site", "Substation", "Zone"})
SURFACE_SUBJECTS = frozenset({"GroundingSystem", "Substation", "Site", "Zone"})
FAULT_SUBJECTS = frozenset({"FaultScenario", "Busbar", "Substation", "Transformer"})


def _attr(name, dimensions, subjects, **kwargs):
    return name, AttributeSpec(name, tuple(dimensions), frozenset(subjects), **kwargs)


ATTRIBUTES: dict[str, AttributeSpec] = dict((
    _attr("rated_voltage", ["voltage"], TOPOLOGY | INSTALLATION, si_range=(1, 1.2e6)),
    _attr("rated_current", ["current"], TOPOLOGY, si_range=(0.001, 1e5)),
    _attr("rated_power", ["apparent_power", "active_power"], TOPOLOGY, si_range=(1, 5e9)),
    _attr("frequency", ["frequency"], TOPOLOGY | INSTALLATION, si_range=(1, 1000)),
    _attr("impedance_percent", ["ratio"], frozenset({"Transformer"}), si_range=(0, 1)),
    _attr("x_r_ratio", ["ratio"], FAULT_SUBJECTS, feeds_calculation=True, si_range=(0, 200)),
    _attr("fault_current", ["current"], FAULT_SUBJECTS, feeds_calculation=True,
          si_range=(1, 5e5), description="Corriente de falla a tierra simétrica (If o 3I0)."),
    _attr("shock_duration", ["time"], FAULT_SUBJECTS, feeds_calculation=True,
          si_range=(0.01, 10), description="Duración de choque t_s para tensiones tolerables."),
    _attr("thermal_duration", ["time"], FAULT_SUBJECTS, feeds_calculation=True,
          si_range=(0.01, 60), description="Duración térmica t_c para dimensionar conductores."),
    _attr("current_division_factor", ["ratio"], FAULT_SUBJECTS, feeds_calculation=True,
          si_range=(0, 1), description="Factor de división de corriente S_f."),
    _attr("decrement_factor", ["ratio"], FAULT_SUBJECTS, feeds_calculation=True,
          si_range=(1, 2), description="Factor de decremento D_f."),
    _attr("apparent_resistivity", ["resistivity"], frozenset({"ResistivityReading"}),
          si_range=(0.1, 1e6)),
    _attr("probe_spacing", ["length"], frozenset({"ResistivityReading"}), si_range=(0.01, 1000)),
    _attr("array_type", [], frozenset({"SoilSurvey", "ResistivityReading"}),
          choices=("wenner", "schlumberger")),
    _attr("measurement_date", [], frozenset({"SoilSurvey", "ResistivityReading"})),
    _attr("soil_resistivity", ["resistivity"], SOIL_MODEL_SUBJECTS, feeds_calculation=True,
          si_range=(0.1, 1e6), description="Resistividad de suelo uniforme o equivalente."),
    _attr("layer_resistivity", ["resistivity"], frozenset({"SoilLayer"}), feeds_calculation=True,
          si_range=(0.1, 1e6)),
    _attr("layer_thickness", ["length"], frozenset({"SoilLayer"}), feeds_calculation=True,
          si_range=(0.01, 1000)),
    _attr("surface_layer_resistivity", ["resistivity"], SURFACE_SUBJECTS,
          feeds_calculation=True, si_range=(1, 1e6)),
    _attr("surface_layer_thickness", ["length"], SURFACE_SUBJECTS, feeds_calculation=True,
          si_range=(0.01, 1)),
    _attr("burial_depth", ["length"], frozenset({"GroundingGrid", "GridConductor",
                                                  "RodElectrode"}),
          feeds_calculation=True, si_range=(0, 20)),
    _attr("conductor_cross_section", ["area"], GROUNDING, feeds_calculation=True,
          si_range=(1e-6, 1e-2)),
    _attr("conductor_size", [], GROUNDING, description="Calibre literal, p. ej. «4/0 AWG»."),
    _attr("conductor_material", [], GROUNDING),
    _attr("rod_length", ["length"], frozenset({"RodElectrode", "GroundingGrid"}),
          feeds_calculation=True, si_range=(0.1, 100)),
    _attr("rod_diameter", ["length"], frozenset({"RodElectrode"}), si_range=(0.001, 0.2)),
    _attr("grid_length", ["length"], frozenset({"GroundingGrid"}), feeds_calculation=True,
          si_range=(0.5, 5000)),
    _attr("grid_width", ["length"], frozenset({"GroundingGrid"}), feeds_calculation=True,
          si_range=(0.5, 5000)),
    _attr("grid_area", ["area"], frozenset({"GroundingGrid"}), si_range=(0.25, 2.5e7)),
    _attr("conductor_spacing", ["length"], frozenset({"GroundingGrid"}),
          feeds_calculation=True, si_range=(0.1, 100)),
    _attr("elevation", ["length"], PHYSICAL_TYPES, si_range=(-1000, 9000)),
    _attr("operating_state", [], TOPOLOGY),
    _attr("standard_edition", [], frozenset({"FaultScenario", "GroundingSystem", "SoilSurvey",
                                             "SoilModel"}),
          description="Norma y edición citadas, p. ej. «IEEE 80-2013»."),
    # Resultados informados por un documento: afirmación documental, nunca resultado del solver.
    _attr("reported_grid_resistance", ["resistance"], frozenset({"GroundingGrid",
                                                                  "GroundingSystem"}),
          si_range=(0, 1e4)),
    _attr("reported_gpr", ["voltage"], frozenset({"GroundingGrid", "GroundingSystem"}),
          si_range=(0, 1e7)),
    _attr("reported_touch_voltage", ["voltage"], frozenset({"GroundingGrid",
                                                             "GroundingSystem"}),
          si_range=(0, 1e6)),
    _attr("reported_step_voltage", ["voltage"], frozenset({"GroundingGrid",
                                                            "GroundingSystem"}),
          si_range=(0, 1e6)),
    _attr("tolerable_touch_voltage", ["voltage"], frozenset({"GroundingGrid",
                                                              "GroundingSystem"}),
          si_range=(0, 1e5)),
    _attr("tolerable_step_voltage", ["voltage"], frozenset({"GroundingGrid",
                                                             "GroundingSystem"}),
          si_range=(0, 1e6)),
))


@dataclass(frozen=True)
class Quantity:
    literal: str
    unit_literal: str
    value: float
    dimension: str
    unit: str
    value_si: float
    notes: tuple = field(default=())


def parse_number(literal: str) -> tuple[float, tuple]:
    """Lee un número literal de documento; devuelve valor y notas de ambigüedad."""
    text = literal.strip().replace("−", "-").replace(" ", "")
    notes = ()
    if not text or not any(c.isdigit() for c in text):
        raise ValueError(f"«{literal}» no es un número")
    if "," in text and "." in text:
        # El último separador es el decimal: 1.234,5 o 1,234.5.
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif text.count(",") == 1:
        whole, fraction = text.split(",")
        if len(fraction) == 3 and whole.lstrip("-") not in {"", "0"}:
            notes = ("separador «,» ambiguo (decimal o miles); se interpretó como decimal",)
        text = text.replace(",", ".")
    elif text.count(",") > 1:
        text = text.replace(",", "")
    try:
        return float(text), notes
    except ValueError as exc:
        raise ValueError(f"«{literal}» no es un número") from exc


def normalize_unit(unit_literal: str) -> str:
    """Clave de búsqueda de la unidad; conserva la mayúscula del prefijo m/M cuando importa."""
    text = " ".join(unit_literal.split())
    folded = text.casefold()
    if folded in _PREFIX_SENSITIVE:
        return text[0] + text[1:].casefold()
    return folded


def unit_spec(unit_literal: str) -> tuple[str, str, float] | None:
    """(dimensión, unidad canónica, factor a SI) de una unidad literal, o None si es desconocida."""
    key = normalize_unit(unit_literal)
    return _PREFIXED_KEYS.get(key) or UNITS.get(key)


def parse_quantity(literal: str, unit_literal: str) -> Quantity:
    value, notes = parse_number(literal)
    spec = unit_spec(unit_literal)
    if spec is None:
        raise ValueError(f"unidad desconocida «{unit_literal}»")
    dimension, unit, factor = spec
    return Quantity(literal, unit_literal, value, dimension, unit, value * factor, notes)


def taxonomy_summary() -> dict:
    """Resumen compacto que se entrega al extractor junto con el contrato."""
    return {
        "entity_types": sorted(t for t, spec in ENTITY_TYPES.items() if spec.llm_extractable),
        "relations": {
            name: {"sources": sorted(rule.sources), "targets": sorted(rule.targets),
                   "symmetric": rule.symmetric}
            for name, rule in RELATION_RULES.items() if rule.llm_extractable
        },
        "attributes": {
            name: {"subjects": sorted(spec.subjects),
                   "units": sorted({unit for unit, (dimension, _, _)
                                    in (UNITS | PREFIXED_UNITS).items()
                                    if dimension in spec.dimensions and unit}),
                   **({"choices": list(spec.choices)} if spec.choices else {}),
                   **({"description": spec.description} if spec.description else {})}
            for name, spec in ATTRIBUTES.items()
        },
    }
