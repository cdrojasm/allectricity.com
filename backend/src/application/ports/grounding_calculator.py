from abc import ABC, abstractmethod
from src.domain.spat.models import FaultScenario, GridGeometry, SafetyAssessment, SoilLayer


class GroundingCalculator(ABC):
    @abstractmethod
    def assess(
        self, geometry: GridGeometry, soil_layers: list[SoilLayer], fault: FaultScenario
    ) -> SafetyAssessment: ...
