from src.application.ports.design_repository import DesignRepository
from src.application.ports.grounding_calculator import GroundingCalculator
from src.domain.spat.models import DesignStatus, GroundingDesign


class AssessGroundingDesign:
    def __init__(self, repository: DesignRepository, calculator: GroundingCalculator) -> None:
        self._repository = repository
        self._calculator = calculator

    def execute(self, design: GroundingDesign) -> GroundingDesign:
        assessment = self._calculator.assess(design.geometry, design.soil_layers, design.fault)
        design.assessment = assessment
        design.status = DesignStatus.VALID if assessment.is_compliant else DesignStatus.NON_COMPLIANT
        return self._repository.save(design)
