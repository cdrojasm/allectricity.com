import pytest

from src.domain.agent.patches import PatchError, check_change


def test_critical_assumptions_are_allowed_only_with_explicit_draft_marker():
    source = {"kind": "assumption", "ref": None, "note": "Valor provisional para mostrar el borrador"}
    with pytest.raises(PatchError, match="critical input"):
        check_change("fault.current_a", source)

    entry = check_change("fault.current_a", {**source, "draft": True}, draft=True)
    assert entry == {"kind": "assumption", "ref": None, "draft": True, "note": source["note"][:300]}


def test_draft_critical_assumptions_need_a_visible_note():
    with pytest.raises(PatchError, match="visible note"):
        check_change("fault.current_a", {"kind": "assumption", "draft": True}, draft=True)
