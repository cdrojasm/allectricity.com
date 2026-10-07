import pytest

from src.domain.spat import soil_materials
from src.domain.spat.soundings import apparent_resistivity, missing_in_text


def test_lookup_by_name_and_by_resistivity():
    clay = soil_materials.search("arcilla")
    assert {m["id"] for m in clay} >= {"soft_clay", "compact_clay"}
    assert soil_materials.search("Turba")[0]["id"] == "peat"  # accents and case are ignored
    assert soil_materials.search("tierra vegetal")[0]["id"] == "humus"
    plausible = soil_materials.search(resistivity_ohm_m=2000)
    assert plausible and all(m["min_ohm_m"] <= 2000 <= m["max_ohm_m"] for m in plausible)
    assert soil_materials.search("granito", resistivity_ohm_m=50) == []
    record = soil_materials.BY_ID["granite_sandstone"].record()
    assert record["typical_ohm_m"] == 3870 and record["source"].startswith("IEC 60364-5-54")
    assert len(soil_materials.table()) == len(soil_materials.MATERIALS)


def test_apparent_resistivity_from_resistance():
    assert apparent_resistivity("wenner", 2, 10) == pytest.approx(125.6637, rel=1e-6)
    # Schlumberger: AB/2 = 10 m, MN = 2 m, R = 1 ohm -> pi·(100 − 1)/2
    assert apparent_resistivity("schlumberger", 10, 1, 2) == pytest.approx(155.5088, rel=1e-6)
    with pytest.raises(ValueError):
        apparent_resistivity("schlumberger", 10, 1)


def test_readings_must_appear_in_the_message():
    text = "a=1 m: 136,5 Ω·m; a = 2 m 1.250; a=4 → 98.2"
    assert missing_in_text([1, 136.5, 2, 1250, 4, 98.2], text) == []
    assert missing_in_text([3, 136.6], text) == [3, 136.6]
