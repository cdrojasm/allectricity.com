from types import SimpleNamespace

from src.infrastructure.agents import uow
from src.infrastructure.processing.plan_vision import propose_plan_from_image


class FakeCompletions:
    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"structures": [{"x": 10, "y": 8, "width": 6, "height": 4, "label": "Edificio"}, {"x": 99, "y": 8, "width": 6, "height": 4, "label": "Fuera"}]}'))])


class FakeClient:
    chat = SimpleNamespace(completions=FakeCompletions())


def test_plan_vision_returns_bounded_reviewable_proposal():
    work = uow.UnitOfWork("spat-plan-vision", client=FakeClient(), prompt=uow.seed_prompt("spat-plan-vision"))
    proposal = propose_plan_from_image(work, b"image", "image/png", {"length_m": 40, "width_m": 30})

    assert proposal["requires_confirmation"] is True
    assert proposal["structures"] == [{"x": 10.0, "y": 8.0, "width": 6.0, "height": 4.0, "label": "Edificio"}]
    assert any("descartaron" in warning for warning in proposal["warnings"])
