"""Deterministic digest of a potential calculation for the agent and the user.

The verdict comes from the stored safety evaluation, never from the model.
"""


def _value(field):
    return field.get("value") if isinstance(field, dict) else field


def summarize(calculation: dict) -> dict:
    summary = {"calculation_id": calculation["id"], "status": calculation["status"],
               "artifact_version": calculation["artifact_version"], "error": calculation.get("error"),
               "parameters": {k: calculation["parameters"].get(k) for k in
                              ("safety_standards", "x_over_r", "system_frequency_hz", "fault_split", "discretization_m")}}
    result = calculation.get("result")
    if calculation["status"] != "completed" or not result:
        summary["verdict"] = "no_evaluado"
        return summary
    standards = []
    for evaluation in result.get("safety") or []:
        criteria = {c["criterion"]: {"actual_v": round(c["actual_v"], 1), "tolerable_v": round(c["tolerable_v"], 1),
                                     "margin_percent": round(100 * c["margin_rel"], 1), "status": c["status"]}
                    for c in evaluation.get("criteria", [])}
        standards.append({"standard": evaluation["standard"], "status": evaluation["status"], **criteria,
                          "reason": evaluation.get("reason"),
                          "gpr_below_tolerable_touch": evaluation.get("gpr_below_tolerable_touch")})
    statuses = {s["status"] for s in standards}
    thermal = result.get("conductor_thermal") or {}
    summary.update(
        verdict="no_cumple" if "no_cumple" in statuses or thermal.get("status") == "no_cumple"
        else "cumple" if statuses == {"cumple"} else "no_evaluable",
        grid_resistance_ohm=round(result["grid_resistance_ohm"], 3),
        gpr_v=round(result["gpr_v"], 1),
        injected_current_a=round(result["injected_current_a"], 1),
        max_touch_v=round(_value(result["max_touch_v"]), 1),
        max_step_v=round(_value(result["max_step_v"]), 1),
        standards=standards,
        conductor_thermal={k: thermal.get(k) for k in ("status", "minimum_section_mm2", "selected_section_mm2",
                                                       "material_name")} if thermal else None,
        warnings=[*(result.get("model_warnings") or []), *(result.get("engine_warnings") or [])],
        segment_count=result.get("segment_count"),
    )
    return summary
