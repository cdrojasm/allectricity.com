from src.application.ports.design_repository import DesignRepository
from src.domain.spat.models import GroundingDesign


class InMemoryDesignRepository(DesignRepository):
    def __init__(self) -> None:
        self._designs: dict[str, GroundingDesign] = {}

    def save(self, design: GroundingDesign) -> GroundingDesign:
        self._designs[design.design_id] = design
        return design

    def get(self, design_id: str) -> GroundingDesign | None:
        return self._designs.get(design_id)
