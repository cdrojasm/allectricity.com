from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.spat.grid_geometry import MAX_CONDUCTORS, MAX_RODS, geometry_problems
from src.infrastructure.calculations.safety_criteria import IEEE80_2013, SUPPORTED_STANDARDS
from src.infrastructure.calculations.conductor_thermal import MATERIALS
from src.infrastructure.calculations.conductor_thermal_profiles import (
    DEFAULT_THERMAL_PROFILE, DEFAULT_VOLTAGE_LEVEL, IEEE80_PROFILE, thermal_material_ids, thermal_mode)


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComplianceCriterion(StrictRequestModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    status: str = Field(default="pending", pattern="^(pending|compliant|non_compliant|not_applicable)$")
    evidence: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)


class ComplianceStandard(StrictRequestModel):
    standard_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    edition: str | None = Field(default=None, max_length=80)
    applicability: str = Field(default="conditional", pattern="^(applicable|conditional|not_applicable)$")
    criteria: list[ComplianceCriterion] = Field(default_factory=list, max_length=100)


class SoilLayerRequest(StrictRequestModel):
    resistivity_ohm_m: float = Field(gt=0)
    depth_m: float | None = Field(default=None, gt=0)
    material: str | None = Field(default=None, max_length=120)


class ArtifactSoilLayerRequest(SoilLayerRequest):
    """A layer of the artifact's stratigraphy: it may be described by material and thickness
    before its resistivity is known; the potential calculation requires every resistivity."""

    resistivity_ohm_m: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def described(self):
        if self.resistivity_ohm_m is None and not self.material:
            raise ValueError("a soil layer needs its resistivity or at least its material")
        return self


class SoilMeasurementRequest(StrictRequestModel):
    spacing_m: float = Field(gt=0)
    apparent_resistivity_ohm_m: float = Field(gt=0)
    potential_spacing_m: float | None = Field(default=None, gt=0)
    locator: str | None = Field(default=None, max_length=180)


class SoilMeasurementsRequest(StrictRequestModel):
    array: str = Field(default="wenner", pattern="^(wenner|schlumberger)$")
    measurements: list[SoilMeasurementRequest] = Field(min_length=4, max_length=200)
    outlier_threshold: float = Field(default=0.15, gt=0, lt=1)
    layer_count: int = Field(default=2, ge=2, le=8)
    source: dict | None = None


class SoilFileImportRequest(StrictRequestModel):
    upload_id: str = Field(min_length=36, max_length=36)
    sheet: str | None = Field(default=None, max_length=120)
    spacing_column: str = Field(min_length=1, max_length=3)
    value_column: str = Field(min_length=1, max_length=3)
    potential_column: str | None = Field(default=None, max_length=3)
    first_row: int = Field(ge=1)
    last_row: int = Field(ge=1)
    decimal: str = Field(default="auto", pattern="^(auto|,|\\.)$")
    array: str = Field(default="wenner", pattern="^(wenner|schlumberger)$")
    value_kind: str = Field(default="apparent_resistivity", pattern="^(apparent_resistivity|resistance)$")
    spacing_unit: str = Field(default="m", pattern="^(m|cm|mm)$")
    potential_spacing_unit: str = Field(default="m", pattern="^(m|cm|mm)$")
    value_unit: str = Field(default="ohm_m", pattern="^(ohm_m|ohm_cm|ohm)$")
    layer_count: int = Field(default=2, ge=2, le=8)
    outlier_threshold: float = Field(default=0.15, gt=0, lt=1)


class GridGeometryRequest(StrictRequestModel):
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    burial_depth_m: float = Field(default=0.5, gt=0)
    conductor_spacing_m: float = Field(gt=0)
    rods_count: int = Field(default=0, ge=0)
    rod_length_m: float = Field(default=2.4, gt=0)


class PlanPoint(StrictRequestModel):
    x: float = Field(ge=0, le=1e5, description="m desde la esquina de origen, a lo largo del largo")
    y: float = Field(ge=0, le=1e5, description="m desde la esquina de origen, a lo largo del ancho")


class ConductorLineRequest(StrictRequestModel):
    start: PlanPoint
    end: PlanPoint


class RodRequest(PlanPoint):
    length_m: float | None = Field(default=None, gt=0, le=100, description="Por defecto, rod_length_m")


class StructureRequest(PlanPoint):
    """Constructive element represented as a non-traversable rectangular obstacle."""

    width: float = Field(gt=0, le=1e5)
    height: float = Field(gt=0, le=1e5)
    label: str | None = Field(default=None, max_length=160)


class SiteAreaRequest(StrictRequestModel):
    """Polygonal site zone. Legacy rectangular artifacts are normalized on input."""

    type: Literal["intervenible", "non_intervenible"]
    label: str | None = Field(default=None, max_length=160)
    polygon: list[PlanPoint] = Field(min_length=3, max_length=1000,
                                     description="Vértices del polígono en metros, sin repetir el primero al final")

    @model_validator(mode="before")
    @classmethod
    def convert_legacy_rectangle(cls, value):
        if isinstance(value, dict) and "polygon" not in value and all(
                key in value for key in ("x_min", "x_max", "y_min", "y_max")):
            bounds = {key: value[key] for key in ("x_min", "x_max", "y_min", "y_max")}
            value = {key: item for key, item in value.items()
                     if key not in {"x_min", "x_max", "y_min", "y_max"}}
            value["polygon"] = [
                {"x": bounds["x_min"], "y": bounds["y_min"]},
                {"x": bounds["x_max"], "y": bounds["y_min"]},
                {"x": bounds["x_max"], "y": bounds["y_max"]},
                {"x": bounds["x_min"], "y": bounds["y_max"]},
            ]
        return value

    @model_validator(mode="after")
    def polygon_is_valid(self):
        from src.domain.spat.grid_geometry import area_polygon
        points = area_polygon(self.model_dump(mode="python"))
        area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
        if abs(area2) < 1e-3:
            raise ValueError("an area polygon must have nonzero area")
        return self


class PlanBackgroundRequest(StrictRequestModel):
    """Calibrated image/PDF page used only as a plan reference, never as solver geometry."""
    upload_id: str = Field(min_length=36, max_length=36)
    source_page: int | None = Field(default=None, ge=1)
    width_px: int = Field(gt=0, le=100000)
    height_px: int = Field(gt=0, le=100000)
    scale_m_per_pixel: float = Field(gt=0, le=1000)
    offset_x_m: float = 0
    offset_y_m: float = 0
    calibrated: bool = True
    calibration_points: list[PlanPoint] = Field(default_factory=list, max_length=2)
    calibration_distance_m: float | None = Field(default=None, gt=0)
    pixel_distance: float | None = Field(default=None, gt=0)


class ArtifactGeometryRequest(StrictRequestModel):
    """Plan of the site and of its grid: regular (spacing per axis) or drawn conductor by conductor.

    `length_m` × `width_m` is the site; the grid is a layer inside it, limited to the
    intervenible `areas` when there are any and kept out of `structures` and non-intervenible areas.
    """

    length_m: float = Field(gt=0, le=1e5, description="Largo del terreno (X)")
    width_m: float = Field(gt=0, le=1e5, description="Ancho del terreno (Y)")
    burial_depth_m: float = Field(default=0.5, gt=0)
    conductor_spacing_m: float | None = Field(default=None, gt=0, description="Retícula homogénea")
    conductor_spacing_x_m: float | None = Field(default=None, gt=0,
                                                description="Separación entre conductores medida a lo largo de X")
    conductor_spacing_y_m: float | None = Field(default=None, gt=0,
                                                description="Separación entre conductores medida a lo largo de Y")
    conductors: list[ConductorLineRequest] = Field(default_factory=list, max_length=MAX_CONDUCTORS,
                                                   description="Conductores trazados; reemplazan la retícula regular")
    rods_count: int = Field(default=0, ge=0)
    rod_length_m: float = Field(default=2.4, gt=0)
    rods: list[RodRequest] = Field(default_factory=list, max_length=MAX_RODS,
                                   description="Varillas en posiciones explícitas; reemplazan rods_count")
    structures: list[StructureRequest] = Field(default_factory=list, max_length=500,
                                               description="Elementos constructivos no atravesables")
    snap_m: float | None = Field(default=None, gt=0, le=10,
                                 description="Paso constructivo de las líneas generadas y del dibujo; por defecto 0,5 m")
    areas: list[SiteAreaRequest] = Field(default_factory=list, max_length=100,
                                         description="Zonas intervenibles (la malla debe quedar dentro) "
                                                     "y no intervenibles (la malla no puede entrar)")
    background: PlanBackgroundRequest | None = Field(default=None, description="Plano de fondo calibrado")

    @model_validator(mode="after")
    def plan_is_buildable(self):
        problems = geometry_problems(self.model_dump(mode="json"))
        if problems:
            raise ValueError("; ".join(problems))
        if self.rods:
            self.rods_count = len(self.rods)
        return self


class FaultScenarioRequest(StrictRequestModel):
    current_a: float = Field(gt=0)
    clearing_time_s: float = Field(gt=0)
    surface_resistivity_ohm_m: float = Field(default=3000, gt=0)
    surface_thickness_m: float = Field(default=0.1, gt=0)
    body_weight_kg: float = Field(default=50, ge=50, le=70)
    exposure_class: Literal["public", "occupational"] | None = None
    surface_layer_present: bool | None = None


class ArtifactFaultRequest(FaultScenarioRequest):
    """Fault data of an artifact; it may stay incomplete until the calculation is requested."""

    current_a: float | None = Field(default=None, gt=0)
    clearing_time_s: float | None = Field(default=None, gt=0)


class GroundingConductorRequest(StrictRequestModel):
    material_id: str = Field(default="copper_hard_drawn", min_length=1, max_length=60)
    cross_section_mm2: float = Field(default=86.590147, gt=0, le=10000)
    joint_type: str = Field(default="bolted", pattern="^(bolted|brazed|welded|other)$")
    maximum_temperature_c: float = Field(default=250, gt=-273.15, le=2000)
    thermal_duration_s: float = Field(default=1.0, gt=0, le=60, description="t_c; independiente del tiempo de choque t_s")
    ambient_temperature_c: float = Field(default=40, ge=-50, le=200)
    thermal_profile: str = Field(
        default=DEFAULT_THERMAL_PROFILE, min_length=1, max_length=40,
        description="Norma con la que se dimensiona el conductor: 'IEEE 80-2013', 'IEC 60364-5-54:2011' o 'RETIE 2024'. "
                    "Con IEC, ambient_temperature_c es la temperatura inicial y maximum_temperature_c la final.")
    voltage_level: str = Field(
        default=DEFAULT_VOLTAGE_LEVEL, pattern="^(low|medium_high_extra_high)$",
        description="Solo aplica a RETIE 2024: 'low' (baja tensión, Ecuación 3) o 'medium_high_extra_high' (Ecuación 4, "
                    "con Tm y Kf de la Tabla 3.12.2.2.a; maximum_temperature_c no se usa).")

    @model_validator(mode="after")
    def material_and_temperature_are_valid(self):
        try:
            mode = thermal_mode(self.thermal_profile, self.voltage_level)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if self.material_id not in thermal_material_ids(self.thermal_profile, self.voltage_level):
            if self.thermal_profile == IEEE80_PROFILE:
                raise ValueError(f"Material IEEE 80 no soportado: {self.material_id}")
            raise ValueError(f"Material no soportado por {self.thermal_profile}"
                             f"{' (' + self.voltage_level + ')' if mode['voltage_level'] else ''}: {self.material_id}")
        if mode["max_duration_s"] is not None and self.thermal_duration_s > mode["max_duration_s"]:
            raise ValueError(f"{self.thermal_profile} solo aplica a tiempos de hasta {mode['max_duration_s']:g} s "
                             "(para tiempos mayores se requiere IEC 60949)")
        if mode["temperature_inputs"] == "table":
            if self.ambient_temperature_c != 40:
                raise ValueError("La Tabla 3.12.2.2.a de RETIE está definida para una temperatura ambiente de 40 °C")
            return self
        if self.maximum_temperature_c <= self.ambient_temperature_c:
            raise ValueError("La temperatura máxima debe ser superior a la temperatura ambiente")
        if mode["temperature_inputs"] == "ambient_and_maximum":
            material = MATERIALS.get(self.material_id)
            if self.maximum_temperature_c > material["fusion_temp_c"]:
                raise ValueError("La temperatura máxima supera la de fusión del material")
        return self


def default_grounding_compliance():
    standards = [
        ("IEEE 80", "Seguridad de la puesta a tierra de subestaciones AC", "conditional", [
            ("touch-voltage", "Tensión de contacto", "Comparar la tensión de contacto calculada con el límite tolerable para el tiempo de despeje y condiciones de superficie del proyecto."),
            ("step-voltage", "Tensión de paso", "Comparar la tensión de paso calculada con el límite tolerable para el tiempo de despeje y condiciones de superficie del proyecto."),
            ("gpr", "Elevación de potencial de tierra", "Documentar la elevación de potencial y revisar tensiones transferidas y zonas de influencia."),
            ("conductor-thermal", "Dimensionamiento térmico de conductores", "Verificar sección y material frente a corriente de falla, duración y límites térmicos aplicables."),
        ]),
        ("IEC 61936-1", "Instalaciones eléctricas de potencia de tensión superior a 1 kV AC", "conditional", [
            ("earthing-design", "Diseño del sistema de puesta a tierra", "Registrar la verificación de seguridad, funcionamiento previsto y condiciones de la instalación."),
            ("touch-step", "Tensiones de contacto y de paso", "Registrar método, escenarios y evidencia usados para verificar seguridad de las personas."),
            ("installation-verification", "Verificación de la instalación", "Documentar inspecciones, mediciones y verificaciones requeridas para el alcance del proyecto."),
        ]),
        ("IEC 60364-5-54", "Instalaciones de baja tensión: puesta a tierra y conductores de protección", "conditional", [
            ("electrode-arrangement", "Disposición de electrodos y puesta a tierra", "Documentar configuración, materiales, conexiones y coordinación con el esquema de puesta a tierra."),
            ("protective-conductors", "Conductores de protección", "Verificar selección, continuidad, sección y protección mecánica/corrosiva según aplique."),
        ]),
        ("IEEE 81", "Medición de resistividad del suelo e impedancia de tierra", "conditional", [
            ("soil-measurement", "Medición de resistividad del suelo", "Registrar método de medición, espaciamientos, condiciones del sitio y datos usados en el modelo."),
            ("ground-measurement", "Medición de impedancia y potenciales", "Documentar método de prueba y resultados de resistencia/impedancia y potenciales superficiales."),
        ]),
        ("RETIE", "Reglamento Técnico de Instalaciones Eléctricas de Colombia", "conditional", [
            ("retie-scope", "Aplicabilidad y alcance reglamentario", "Confirmar jurisdicción, tipo de instalación, libro/numeral aplicable y versión vigente para la fecha del proyecto."),
            ("retie-earthing", "Puesta a tierra y equipotencialidad", "Registrar evidencia de los requisitos aplicables de puesta a tierra, equipotencialidad e inspección."),
        ]),
    ]
    return [
        {"standard_id": code, "title": title, "edition": None, "applicability": applicability,
         "criteria": [{"criterion_id": key, "title": name, "description": description,
                       "status": "pending", "evidence": None, "notes": None}
                      for key, name, description in criteria]}
        for code, title, applicability, criteria in standards
    ]


class BuildingRequest(StrictRequestModel):
    """A building's result grouping, linked many-to-many to networks and electrodes."""

    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    network_ids: list[str] = Field(default_factory=list, max_length=100)
    electrode_ids: list[str] = Field(default_factory=list, max_length=100)


class GroundingNetworkRequest(StrictRequestModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    geometry: ArtifactGeometryRequest


class ElectricalConnectionRequest(StrictRequestModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal["bond", "resistor"]
    group_a: str = Field(min_length=1, max_length=100)
    group_b: str = Field(min_length=1, max_length=100)
    resistance_ohm: float | None = Field(default=None, ge=1e-9, le=1e9)

    @model_validator(mode="after")
    def resistance_matches_kind(self):
        if self.group_a == self.group_b:
            raise ValueError("an electrical connection must join two different entities")
        if self.kind == "bond" and self.resistance_ohm is not None:
            raise ValueError("an ideal bond cannot specify resistance_ohm")
        if self.kind == "resistor" and self.resistance_ohm is None:
            raise ValueError("a resistor connection requires resistance_ohm")
        return self


class ElectrodeRequest(StrictRequestModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    geometry: ArtifactGeometryRequest


class GroundingArtifactRequest(StrictRequestModel):
    """A version of the design. The grid, the soil or the fault data may be missing while the
    design is built up in any order; the potential calculation refuses an incomplete artifact."""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    name: str = Field(min_length=1, max_length=160)
    geometry: ArtifactGeometryRequest | None = None
    soil_layers: list[ArtifactSoilLayerRequest] = Field(default_factory=list, max_length=8)
    soil_measurements: SoilMeasurementsRequest | None = None
    soil_model: dict | None = None
    fault: ArtifactFaultRequest = Field(default_factory=ArtifactFaultRequest)
    conductor: GroundingConductorRequest = Field(default_factory=GroundingConductorRequest)
    compliance: list[ComplianceStandard] = Field(default_factory=default_grounding_compliance, max_length=30,
                                                 validate_default=True)
    buildings: list[BuildingRequest] = Field(default_factory=list, max_length=500)
    networks: list[GroundingNetworkRequest] = Field(default_factory=list, max_length=500)
    electrodes: list[ElectrodeRequest] = Field(default_factory=list, max_length=500)
    connections: list[ElectricalConnectionRequest] = Field(default_factory=list, max_length=100000)

    @model_validator(mode="after")
    def entities_match_schema_version(self):
        if self.schema_version == "1.0" and (self.buildings or self.networks or self.electrodes or self.connections):
            raise ValueError("buildings, networks, electrodes and connections require schema_version 2.0")
        if self.schema_version == "2.0" and self.geometry is not None:
            raise ValueError("schema_version 2.0 stores geometry under networks/electrodes")
        for field_name in ("buildings", "networks", "electrodes"):
            items = getattr(self, field_name)
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} ids must be unique")
        network_ids = {item.id for item in self.networks}
        electrode_ids = {item.id for item in self.electrodes}
        connection_ids = [item.id for item in self.connections]
        if len(connection_ids) != len(set(connection_ids)):
            raise ValueError("electrical connection ids must be unique")
        entity_ids = network_ids | electrode_ids
        for connection in self.connections:
            if connection.group_a not in entity_ids or connection.group_b not in entity_ids:
                raise ValueError(f"connection {connection.id!r} references an unknown network or electrode")
        for building in self.buildings:
            if not set(building.network_ids) <= network_ids:
                raise ValueError(f"building {building.id!r} references an unknown network")
            if not set(building.electrode_ids) <= electrode_ids:
                raise ValueError(f"building {building.id!r} references an unknown electrode")
        return self


class ReturnPathRequest(BaseModel):
    """One return path to remote earth (shield wires, neutral, cable screen) as a lumped impedance."""

    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="other", pattern="^(shield_wire|neutral|cable_screen|remote_ground|other)$")
    resistance_ohm: float = Field(ge=0, le=1e6)
    reactance_ohm: float = Field(default=0.0, ge=-1e6, le=1e6)

    @model_validator(mode="after")
    def impedance_is_not_zero(self):
        if self.resistance_ohm == 0 and self.reactance_ohm == 0:
            raise ValueError("return path impedance must not be zero")
        return self


class FaultSplitRequest(BaseModel):
    """Either a known split factor S_f with its origin, or the return paths to compute it."""

    split_factor: float | None = Field(default=None, gt=0, le=1)
    split_factor_origin: str | None = Field(default=None, min_length=1, max_length=200)
    return_paths: list[ReturnPathRequest] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def one_source(self):
        if (self.split_factor is None) == (not self.return_paths):
            raise ValueError("give either split_factor or return_paths")
        if self.split_factor is not None and not self.split_factor_origin:
            raise ValueError("split_factor_origin is required with split_factor")
        return self


class TransferExposureRequest(StrictRequestModel):
    """A documented scenario in which an accessible metal object may transfer potential."""

    id: str = Field(min_length=1, max_length=100)
    scenario_id: str = Field(min_length=1, max_length=80)
    metal_entity_id: str = Field(min_length=1, max_length=100)
    contact_surface_xyz_m: tuple[float, float, float] = Field(
        description="Contact point in metres; z must be zero because this contract records a ground surface point"
    )
    accessibility: Literal["confirmed", "assumed", "not_accessible"]
    evidence: str | None = Field(default=None, max_length=4000)
    exposure_class: Literal["public", "occupational"] | None = None
    surface_layer_present: bool | None = None
    surface_resistivity_ohm_m: float | None = Field(default=None, gt=0)
    surface_thickness_m: float | None = Field(default=None, gt=0)
    clearing_time_s: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_contact_surface(self):
        if not all(isfinite(coordinate) for coordinate in self.contact_surface_xyz_m):
            raise ValueError("contact_surface_xyz_m coordinates must be finite")
        if self.contact_surface_xyz_m[2] != 0:
            raise ValueError("contact_surface_xyz_m z coordinate must be 0")
        if self.accessibility in {"confirmed", "not_accessible"} and not (self.evidence or "").strip():
            raise ValueError("evidence is required when accessibility is confirmed or not_accessible")
        if self.accessibility == "confirmed":
            if self.exposure_class is None or self.surface_layer_present is None:
                raise ValueError("confirmed transfer exposure requires exposure_class and surface_layer_present")
            if self.surface_layer_present and (
                self.surface_resistivity_ohm_m is None or self.surface_thickness_m is None
            ):
                raise ValueError("a declared surface layer requires its resistivity and thickness")
        if self.surface_layer_present is False and (
            self.surface_resistivity_ohm_m is not None or self.surface_thickness_m is not None
        ):
            raise ValueError("surface layer properties cannot be supplied when surface_layer_present is false")
        return self


class PotentialCalculationRequest(BaseModel):
    """Engine parameters the artifact does not carry; all are recorded in the calculation trace."""

    justification: str = Field(default="Configuración predeterminada validada por el motor.", min_length=10, max_length=500,
                               description="Why these solver settings were selected; stored in the calculation trace")
    conductor_radius_m: float = Field(default=0.00525, ge=1e-4, le=0.5, description="Default: 2/0 AWG copper")
    discretization_m: float = Field(default=1.0, gt=0, le=20, description="Refinement length d; 1 m is the validated default")
    segmentation: str = Field(default="graded", pattern="^(uniform|graded)$",
                              description="uniform: pieces of at most d; graded: 0.25·d at ends, corners and rod joints, "
                                          "d at crossings, growing by 2 up to 7·d")
    estimate_uncertainty: bool = Field(default=False, description="Also solve with 2d and 4d and report the "
                                                                  "discretisation error of R, GPR, touch and step")
    surface_spacing_m: float = Field(default=0.5, description="Surface raster spacing for touch and step search")
    touch_reach_m: float = Field(default=0.0, ge=0, le=5,
                                 description="Margin around the grid's footprint where touch voltage is searched; "
                                             "0 keeps the IEEE 80 search inside the grid perimeter")
    safety_standards: list[str] = Field(default_factory=lambda: [IEEE80_2013], min_length=1, max_length=5,
                                        description="Standards and editions to evaluate; never inferred")
    fault_split: FaultSplitRequest | None = Field(default=None, description="Current division S_f (IEEE 80 §15.9)")
    x_over_r: float | None = Field(default=None, ge=0, le=100, description="Source X/R for the decrement factor D_f")
    system_frequency_hz: float = Field(default=60.0, description="50 or 60 Hz, for D_f")
    scenarios: list["PotentialExcitationScenario"] = Field(
        default_factory=list, max_length=100,
        description="Named signed current injections for a joint 2.0 network calculation",
    )
    transfer_assessment_complete: bool | None = Field(
        default=None,
        description="True only when transfer-voltage exposure assessment is complete and documented",
    )
    transfer_assessment_evidence: str | None = Field(
        default=None, max_length=4000,
        description="Evidence supporting a complete transfer-voltage exposure assessment",
    )
    transfer_exposures: list[TransferExposureRequest] = Field(
        default_factory=list, max_length=500,
        description="Documented accessible-metal transfer exposure scenarios; inputs only, not a safety result",
    )

    @model_validator(mode="after")
    def raster_spacing_divides_step_distance(self):
        if self.surface_spacing_m not in (0.25, 0.5, 1.0):
            raise ValueError("surface_spacing_m must be 0.25, 0.5 or 1.0")
        unknown = [standard for standard in self.safety_standards if standard not in SUPPORTED_STANDARDS]
        if unknown:
            raise ValueError(f"Unsupported safety standards: {unknown}; options: {list(SUPPORTED_STANDARDS)}")
        if self.system_frequency_hz not in (50.0, 60.0):
            raise ValueError("system_frequency_hz must be 50 or 60")
        scenario_ids = [scenario.id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario ids must be unique")
        if (self.transfer_exposures or self.transfer_assessment_complete is True) and not scenario_ids:
            raise ValueError("transfer assessment requires at least one named scenario")
        if self.scenarios and (self.fault_split is not None or self.x_over_r is not None):
            raise ValueError("scenario injections must already include current division and decrement factors")
        if self.transfer_assessment_complete is True and not (self.transfer_assessment_evidence or "").strip():
            raise ValueError("transfer_assessment_evidence is required when transfer_assessment_complete is true")
        if self.transfer_assessment_complete is not True and self.transfer_assessment_evidence is not None:
            raise ValueError("transfer_assessment_evidence cannot be supplied unless the assessment is complete")
        exposure_ids = [exposure.id for exposure in self.transfer_exposures]
        if len(exposure_ids) != len(set(exposure_ids)):
            raise ValueError("transfer exposure ids must be unique")
        unknown_exposure_scenarios = sorted({exposure.scenario_id for exposure in self.transfer_exposures} - set(scenario_ids))
        if unknown_exposure_scenarios:
            raise ValueError(f"transfer exposures reference unknown scenarios: {unknown_exposure_scenarios}")
        return self


class PotentialExcitationScenario(StrictRequestModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    injections_a: dict[str, float] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def finite_injections(self):
        if any(not key or len(key) > 100 for key in self.injections_a):
            raise ValueError("scenario entity ids must contain 1 to 100 characters")
        if any(not (-1e6 <= value <= 1e6) for value in self.injections_a.values()):
            raise ValueError("scenario current magnitudes must not exceed 1e6 A")
        return self


class DesignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geometry: GridGeometryRequest
    soil_layers: list[SoilLayerRequest] = Field(min_length=1, max_length=8)
    fault: FaultScenarioRequest


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    project_type: str = Field(default="land", pattern="^land$")
    country: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    attachments: list[dict] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def coordinates_are_a_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must both be provided or both be empty")
        return self
