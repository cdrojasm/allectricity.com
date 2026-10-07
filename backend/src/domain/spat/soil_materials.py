"""Lookup table of soil materials and their typical resistivity.

Values are indicative ranges for orientation, labelling layers and sanity checks. They are
never project data: a table value only becomes a design input when the user confirms it,
and a site sounding always prevails. Verify the ranges against the edition in force.
"""

from dataclasses import asdict, dataclass
from math import sqrt
from unicodedata import combining, normalize

IEC = "IEC 60364-5-54, Anexo B (informativo): resistividad según el tipo de terreno"
IEEE80 = "IEEE Std 80-2013, Tabla 8: rango de resistividad del terreno (orden de magnitud)"


@dataclass(frozen=True)
class SoilMaterial:
    id: str
    name: str
    category: str
    min_ohm_m: float
    max_ohm_m: float
    source: str
    aliases: tuple[str, ...] = ()

    @property
    def typical_ohm_m(self) -> float:
        """Central value of the range (geometric mean, as resistivity spans orders of magnitude)."""
        return round(sqrt(self.min_ohm_m * self.max_ohm_m), -1 if self.max_ohm_m >= 100 else 0) or self.min_ohm_m

    def record(self) -> dict:
        return {**asdict(self), "aliases": list(self.aliases), "typical_ohm_m": self.typical_ohm_m}


MATERIALS = (
    SoilMaterial("swamp", "Terreno pantanoso", "orgánico", 1, 30, IEC, ("pantano", "ciénaga", "humedal")),
    SoilMaterial("alluvial_silt", "Limo aluvial", "sedimentario", 20, 100, IEC, ("limo", "aluvión", "aluvial")),
    SoilMaterial("humus", "Humus, tierra vegetal", "orgánico", 10, 150, IEC, ("tierra vegetal", "capa vegetal", "mantillo")),
    SoilMaterial("peat", "Turba", "orgánico", 5, 100, IEC, ("turba",)),
    SoilMaterial("soft_clay", "Arcilla blanda", "arcilloso", 50, 50, IEC, ("arcilla", "arcilla plástica")),
    SoilMaterial("compact_clay", "Marga y arcilla compacta", "arcilloso", 100, 200, IEC, ("arcilla compacta", "marga")),
    SoilMaterial("jurassic_marl", "Marga del Jurásico", "arcilloso", 30, 40, IEC),
    SoilMaterial("clayey_sand", "Arena arcillosa", "arenoso", 50, 500, IEC, ("arena arcillosa",)),
    SoilMaterial("siliceous_sand", "Arena silícea", "arenoso", 200, 3000, IEC, ("arena", "arena seca")),
    SoilMaterial("stony_ground", "Terreno pedregoso desnudo", "pedregoso", 1500, 3000, IEC, ("pedregoso", "grava", "gravilla")),
    SoilMaterial("grassy_stony_subsoil", "Terreno pedregoso cubierto de césped", "pedregoso", 300, 500, IEC),
    SoilMaterial("chalk", "Terreno calizo blando (creta)", "calizo", 100, 300, IEC, ("creta",)),
    SoilMaterial("limestone", "Caliza", "roca", 1000, 5000, IEC, ("caliza", "piedra caliza")),
    SoilMaterial("fissured_limestone", "Caliza fisurada", "roca", 500, 1000, IEC),
    SoilMaterial("schist_shale", "Esquisto, pizarra", "roca", 50, 300, IEC, ("pizarra", "lutita", "esquisto")),
    SoilMaterial("mica_schist", "Micaesquisto", "roca", 800, 800, IEC),
    SoilMaterial("granite_sandstone", "Granito y arenisca", "roca", 1500, 10000, IEC, ("granito", "arenisca", "roca")),
    SoilMaterial("weathered_granite_sandstone", "Granito y arenisca alterados", "roca", 100, 600, IEC,
                 ("granito meteorizado", "roca meteorizada")),
    SoilMaterial("wet_organic", "Suelo orgánico húmedo", "general", 10, 10, IEEE80),
    SoilMaterial("moist_soil", "Suelo húmedo", "general", 100, 100, IEEE80, ("suelo húmedo", "tierra húmeda")),
    SoilMaterial("dry_soil", "Suelo seco", "general", 1000, 1000, IEEE80, ("suelo seco", "tierra seca")),
    SoilMaterial("bedrock", "Lecho rocoso", "general", 10000, 10000, IEEE80, ("lecho rocoso", "roca firme")),
)
BY_ID = {material.id: material for material in MATERIALS}


def _plain(text: str) -> str:
    return "".join(c for c in normalize("NFD", text.casefold()) if not combining(c)).strip()


def search(query: str | None = None, resistivity_ohm_m: float | None = None, limit: int = 8) -> list[dict]:
    """Materials matching a name, or whose range contains a resistivity (closest centre first)."""
    if query:
        needle = _plain(query)
        found = [m for m in MATERIALS
                 if needle in _plain(m.name) or any(needle in _plain(a) or _plain(a) in needle for a in m.aliases)
                 or needle == m.id]
    else:
        found = list(MATERIALS)
    if resistivity_ohm_m is not None:
        found = [m for m in found if m.min_ohm_m * 0.999 <= resistivity_ohm_m <= m.max_ohm_m * 1.001]
        found.sort(key=lambda m: abs(m.typical_ohm_m - resistivity_ohm_m) / m.typical_ohm_m)
    return [m.record() for m in found[:limit]]


def table() -> list[dict]:
    return [material.record() for material in MATERIALS]
