from abc import ABC, abstractmethod
from src.domain.spat.models import GroundingDesign


class DesignRepository(ABC):
    @abstractmethod
    def save(self, design: GroundingDesign) -> GroundingDesign: ...

    @abstractmethod
    def get(self, design_id: str) -> GroundingDesign | None: ...
