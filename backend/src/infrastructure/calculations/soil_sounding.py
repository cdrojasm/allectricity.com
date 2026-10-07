"""Fit a Wenner/Schlumberger sounding to the artifact's layered soil model (API and agent)."""

from src.infrastructure.calculations.n_layer_soil import fit_n_layer, soil_layers_record
from src.infrastructure.calculations.soil_model import ResistivityMeasurement, fit_two_layer, to_soil_layers


def fit_sounding(measurements: list[dict], array: str, layer_count: int, outlier_threshold: float = 0.15) -> dict:
    """2 layers by image series, 3-8 layers by the n-layer kernel; raises ValueError/ArithmeticError.

    The returned `soil_layers` use the artifact format (`depth_m` = layer thickness, null for the
    bottom half-space) and stay within the potential engine's limits.
    """
    # Extra keys such as the source `locator` are provenance, not inputs of the fit.
    readings = [ResistivityMeasurement(spacing_m=item["spacing_m"],
                                       apparent_resistivity_ohm_m=item["apparent_resistivity_ohm_m"],
                                       potential_spacing_m=item.get("potential_spacing_m"))
                for item in measurements]
    if layer_count == 2:
        fit = fit_two_layer(readings, array, outlier_threshold=outlier_threshold)
        model_record = {"upper_resistivity_ohm_m": fit.model.rho1_ohm_m,
                        "lower_resistivity_ohm_m": fit.model.rho2_ohm_m,
                        "upper_thickness_m": fit.model.h_m}
        layer_records = to_soil_layers(fit)
        forward_model = "two-layer-image-series"
    else:
        fit = fit_n_layer(readings, layer_count, array, outlier_threshold=outlier_threshold)
        layer_records = soil_layers_record(fit.model)
        model_record = {"model": "n-layer", "layers": layer_records}
        forward_model = fit.forward_model
    return {"model": model_record, "layer_count": layer_count,
            "soil_layers": layer_records, "array": fit.array,
            "rms_error_percent": fit.rms_error_percent,
            "uniform_resistivity_ohm_m": fit.uniform_resistivity_ohm_m,
            "uniform_rms_error_percent": fit.uniform_rms_error_percent,
            "relative_uncertainty_percent": fit.relative_uncertainty_percent, "forward_model": forward_model,
            "residuals_percent": fit.residuals_percent, "excluded": fit.excluded,
            "warnings": fit.warnings}
