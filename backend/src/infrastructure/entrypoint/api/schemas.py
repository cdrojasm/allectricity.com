from pydantic import BaseModel, Field, model_validator

from src.infrastructure.calculations.safety_criteria import IEEE80_2013, SUPPORTED_STANDARDS


class ComplianceCriterion(BaseModel):
    criterion_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    status: str = Field(default="pending", pattern="^(pending|compliant|non_compliant|not_applicable)$")
    evidence: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)


class ComplianceStandard(BaseModel):
    standard_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=240)
    edition: str | None = Field(default=None, max_length=80)
    applicability: str = Field(default="conditional", pattern="^(applicable|conditional|not_applicable)$")
    criteria: list[ComplianceCriterion] = Field(default_factory=list, max_length=100)


class SoilLayerRequest(BaseModel):
    resistivity_ohm_m: float = Field(gt=0)
    depth_m: float | None = Field(default=None, gt=0)


class GridGeometryRequest(BaseModel):
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    burial_depth_m: float = Field(default=0.5, gt=0)
    conductor_spacing_m: float = Field(gt=0)
    rods_count: int = Field(default=0, ge=0)
    rod_length_m: float = Field(default=2.4, gt=0)


class FaultScenarioRequest(BaseModel):
    current_a: float = Field(gt=0)
    clearing_time_s: float = Field(gt=0)
    surface_resistivity_ohm_m: float = Field(default=3000, gt=0)
    surface_thickness_m: float = Field(default=0.1, gt=0)
    body_weight_kg: float = Field(default=50, ge=50, le=70)


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


class GroundingArtifactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    geometry: GridGeometryRequest
    soil_layers: list[SoilLayerRequest] = Field(min_length=1, max_length=8)
    fault: FaultScenarioRequest
    compliance: list[ComplianceStandard] = Field(default_factory=default_grounding_compliance, max_length=30)


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


class PotentialCalculationRequest(BaseModel):
    """Engine parameters the artifact does not carry; all are recorded in the calculation trace."""

    conductor_radius_m: float = Field(default=0.00525, ge=1e-4, le=0.5, description="Default: 2/0 AWG copper")
    discretization_m: float = Field(default=1.0, gt=0, le=20, description="Refinement length d; 1 m is the validated default")
    segmentation: str = Field(default="graded", pattern="^(uniform|graded)$",
                              description="uniform: pieces of at most d; graded: 0.25·d at ends, corners and rod joints, "
                                          "d at crossings, growing by 2 up to 7·d")
    estimate_uncertainty: bool = Field(default=False, description="Also solve with 2d and 4d and report the "
                                                                  "discretisation error of R, GPR, touch and step")
    surface_spacing_m: float = Field(default=0.5, description="Surface raster spacing for touch and step search")
    safety_standards: list[str] = Field(default_factory=lambda: [IEEE80_2013], min_length=1, max_length=5,
                                        description="Standards and editions to evaluate; never inferred")
    fault_split: FaultSplitRequest | None = Field(default=None, description="Current division S_f (IEEE 80 §15.9)")
    x_over_r: float | None = Field(default=None, ge=0, le=100, description="Source X/R for the decrement factor D_f")
    system_frequency_hz: float = Field(default=60.0, description="50 or 60 Hz, for D_f")

    @model_validator(mode="after")
    def raster_spacing_divides_step_distance(self):
        if self.surface_spacing_m not in (0.25, 0.5, 1.0):
            raise ValueError("surface_spacing_m must be 0.25, 0.5 or 1.0")
        unknown = [standard for standard in self.safety_standards if standard not in SUPPORTED_STANDARDS]
        if unknown:
            raise ValueError(f"Unsupported safety standards: {unknown}; options: {list(SUPPORTED_STANDARDS)}")
        if self.system_frequency_hz not in (50.0, 60.0):
            raise ValueError("system_frequency_hz must be 50 or 60")
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
