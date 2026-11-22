"""Bill of materials of a design version (BL-21), shared by the workspace and the published study."""


def bill_of_materials(snapshot, origin, db, project_id) -> dict | None:
    """BL-21: quantities taken off the pinned version's geometry (conductor by material, rods by material and
    length, connections, trench). Geometric quantities only: no waste, slack or overlaps. The excavation volume
    needs a trench width, which only an optimizer run declares (with its source); the cost comes from the applied
    alternative when there is one, never recomputed here."""
    from src.domain.spat import grid_geometry
    from src.domain.spat.geometry_cost import takeoff
    from src.domain.spat.geometry_graph import DEFAULT_MATERIAL

    if snapshot.get("schema_version") == "2.0":
        geometries = [e["geometry"] for kind in ("networks", "electrodes") for e in snapshot.get(kind) or [] if e.get("geometry")]
    else:
        geometries = [snapshot["geometry"]] if snapshot.get("geometry") else []
    if not geometries:
        return None
    conductor: dict[str, float] = {}
    rods: dict[tuple[str, float], int] = {}
    connections, trench, excavation_m3, trench_width = 0, 0.0, 0.0, None
    joints = {"conductor_conductor": 0, "conductor_rod": 0}
    applied = (origin or {}).get("optimizer") or {}
    run = None
    if applied.get("run_id"):
        from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository
        run = OptimizerRunRepository(db.connection).get_run(project_id, applied["run_id"])
        trench_width = (((run or {}).get("request_snapshot") or {}).get("rate_card") or {}).get("assumptions", {}).get("trench_width_m")
    try:
        for geometry in geometries:
            quantities = takeoff(geometry, trench_width_m=trench_width)
            for material, length in quantities["conductor_length_m"].items():
                conductor[material] = conductor.get(material, 0.0) + length
            declared = geometry.get("rods") or []    # explicit rods may name a material; perimeter rods never do
            for index, (_, _, length) in enumerate(grid_geometry.rod_points(geometry)):
                material = (declared[index].get("material") if index < len(declared) else None) or DEFAULT_MATERIAL
                key = (material, round(float(length), 3))
                rods[key] = rods.get(key, 0) + 1
            connections += quantities["connections"]
            for kind, count in (quantities.get("connections_by_type") or {}).items():
                joints[kind] = joints.get(kind, 0) + count
            trench += quantities["trench_length_m"]
            excavation_m3 += quantities["excavation_m3"] or 0.0
    except (KeyError, TypeError, ValueError):
        return None
    section = snapshot.get("conductor") or {}
    cost = None
    if run and applied.get("alternative_id"):
        from src.infrastructure.persistence.optimizer_run_repository import OptimizerRunRepository
        alternative = next((a for a in OptimizerRunRepository(db.connection).list_alternatives(project_id, applied["run_id"])
                            if a["id"] == applied["alternative_id"]), None)
        evaluation = (alternative or {}).get("evaluation_snapshot") or {}
        if evaluation.get("cost") is not None:
            cost = {"currency": (run.get("result_summary") or {}).get("cost_currency"), "total": evaluation["cost"],
                    "by_group": (evaluation.get("cost_detail") or {}).get("by_group"),
                    "note": "Costo de la alternativa aplicada según la corrida del optimizador y las tarifas listadas abajo; no se recalcula aquí."}
    return {
        "conductor": [{"material": m, "length_m": round(v, 3), "cross_section_mm2": section.get("cross_section_mm2"),
                       "material_id": section.get("material_id")} for m, v in sorted(conductor.items())],
        "rods": [{"material": m, "length_m": length, "count": count} for (m, length), count in sorted(rods.items())],
        "rods_total": {"count": sum(rods.values()), "length_m": round(sum(length * count for (_, length), count in rods.items()), 3)},
        "connections": connections,
        "connections_by_type": joints,
        "trench": {"length_m": round(trench, 3), "width_m": trench_width, "depth_m": geometries[0].get("burial_depth_m"),
                   "excavation_m3": round(excavation_m3, 3) if trench_width is not None else None},
        "cost": cost,
        "notes": ["Cantidades geométricas de esta versión: sin desperdicio, traslapos ni holguras de instalación.",
                  *([] if trench_width is not None else ["El volumen de excavación requiere un ancho de zanja declarado con su fuente; esta versión no lo trae."])],
    }
