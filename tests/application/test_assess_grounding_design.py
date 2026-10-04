from src.application.use_cases.assess_grounding_design import AssessGroundingDesign
from src.domain.spat.models import FaultScenario, GroundingDesign, GridGeometry, SoilLayer
from src.infrastructure.calculations.ieee80_calculator import PreliminaryIEEE80Calculator
from src.infrastructure.persistence.in_memory_design_repository import InMemoryDesignRepository


def test_assessment_persists_a_design_with_safety_results() -> None:
    design = GroundingDesign(
        design_id="design-1",
        name="Subestación piloto",
        geometry=GridGeometry(20, 20, 0.5, 4, rods_count=8),
        soil_layers=[SoilLayer(100)],
        fault=FaultScenario(1000, 0.5),
    )
    result = AssessGroundingDesign(InMemoryDesignRepository(), PreliminaryIEEE80Calculator()).execute(design)
    assert result.assessment is not None
    assert result.assessment.grid_resistance_ohm > 0
