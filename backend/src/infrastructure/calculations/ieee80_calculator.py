"""Adaptador de cálculo preliminar. Debe validarse por ingeniero competente.

Las fórmulas completas y coeficientes IEEE 80 se incorporarán en el paquete
normativo versionado; este adaptador hace explícito el punto de extensión.
"""
from math import sqrt

from src.application.ports.grounding_calculator import GroundingCalculator
from src.domain.spat.models import FaultScenario, GridGeometry, SafetyAssessment, SoilLayer


class PreliminaryIEEE80Calculator(GroundingCalculator):
    """Estimador conservador para iteración temprana, no memoria certificable."""

    def assess(
        self, geometry: GridGeometry, soil_layers: list[SoilLayer], fault: FaultScenario
    ) -> SafetyAssessment:
        if not soil_layers:
            raise ValueError("Se requiere al menos una capa de suelo")
        if geometry.conductor_spacing_m <= 0 or geometry.length_m <= 0 or geometry.width_m <= 0:
            raise ValueError("La geometría de malla debe tener dimensiones positivas")
        if fault.clearing_time_s <= 0 or fault.current_a <= 0:
            raise ValueError("La corriente y el tiempo de despeje deben ser positivos")

        rho = soil_layers[0].resistivity_ohm_m
        area = geometry.length_m * geometry.width_m
        total_length = geometry.conductor_length_m + geometry.rods_count * geometry.rod_length_m
        # Aproximación de resistencia de malla para prefactibilidad; se reemplaza
        # por el solver IEEE 80 trazable antes de aprobar un diseño.
        resistance = rho * (1 / (4 * sqrt(area)) + 1 / total_length)
        gpr = fault.current_a * resistance
        surface_factor = max(1.0, 1 + fault.surface_thickness_m * fault.surface_resistivity_ohm_m / rho)
        # Límites de 50 kg derivados de la forma IEEE 80 (0.116/sqrt(ts)).
        body_current = 0.116 / sqrt(fault.clearing_time_s)
        touch_tolerable = body_current * (1000 + 1.5 * fault.surface_resistivity_ohm_m) * surface_factor
        step_tolerable = body_current * (1000 + 6 * fault.surface_resistivity_ohm_m) * surface_factor
        mesh_factor = 1 + geometry.conductor_spacing_m / max(sqrt(area), 1)
        touch_actual = gpr * mesh_factor * 0.7
        step_actual = gpr * mesh_factor * 0.35
        return SafetyAssessment(
            grid_resistance_ohm=round(resistance, 4),
            grid_potential_rise_v=round(gpr, 2),
            touch_actual_v=round(touch_actual, 2),
            touch_tolerable_v=round(touch_tolerable, 2),
            step_actual_v=round(step_actual, 2),
            step_tolerable_v=round(step_tolerable, 2),
        )
