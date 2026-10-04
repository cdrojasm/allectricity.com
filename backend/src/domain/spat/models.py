"""Entidades puras del dominio SPAT; sin dependencias de framework o proveedor."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DesignStatus(str, Enum):
    DRAFT = "draft"
    VALID = "valid"
    NON_COMPLIANT = "non_compliant"


@dataclass(frozen=True)
class SoilLayer:
    resistivity_ohm_m: float
    depth_m: float | None = None


@dataclass(frozen=True)
class GridGeometry:
    length_m: float
    width_m: float
    burial_depth_m: float
    conductor_spacing_m: float
    rods_count: int = 0
    rod_length_m: float = 2.4

    @property
    def conductor_length_m(self) -> float:
        longitudinal = (int(self.width_m / self.conductor_spacing_m) + 1) * self.length_m
        transverse = (int(self.length_m / self.conductor_spacing_m) + 1) * self.width_m
        return longitudinal + transverse


@dataclass(frozen=True)
class FaultScenario:
    current_a: float
    clearing_time_s: float
    surface_resistivity_ohm_m: float = 3000.0
    surface_thickness_m: float = 0.1
    body_weight_kg: float = 50.0


@dataclass(frozen=True)
class SafetyAssessment:
    grid_resistance_ohm: float
    grid_potential_rise_v: float
    touch_actual_v: float
    touch_tolerable_v: float
    step_actual_v: float
    step_tolerable_v: float

    @property
    def is_compliant(self) -> bool:
        return self.touch_actual_v <= self.touch_tolerable_v and self.step_actual_v <= self.step_tolerable_v


@dataclass
class GroundingDesign:
    design_id: str
    name: str
    geometry: GridGeometry
    soil_layers: list[SoilLayer]
    fault: FaultScenario
    status: DesignStatus = DesignStatus.DRAFT
    assessment: SafetyAssessment | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
