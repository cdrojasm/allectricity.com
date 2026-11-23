"""Normative profiles every account starts with: one per standard the safety check supports.

They are seeded by migration 0025 (and by later migrations through `ensure_default_profiles` when a definition
changes, which appends a version and never rewrites one a project pinned). They gate Matherra like any reviewed
profile: contact and step are mandatory and applicable to AC substations under both standards. The tolerable
limits themselves are computed by the safety check of the standard chosen in «Estándares a evaluar».

`STANDARD_PROFILES` maps each standard name the UI and the API use (safety_criteria.SUPPORTED_STANDARDS) to its
profile, so the app can suggest the profile of the standard the user already picked.
"""

from __future__ import annotations

from typing import Any

INSTALLATION = "AC substation"
_BASE_NOTE = ("Perfil base de Allectricity, preparado a partir del texto de la norma. No reemplaza la revisión del "
              "ingeniero que firma: confirma su alcance para tu proyecto o crea un perfil propio con tu criterio.")

IEEE80_SOURCE = {
    "document": "IEEE Std 80-2013, IEEE Guide for Safety in AC Substation Grounding",
    "edition": "2013",
    "clause": "Cláusula 8 — Criterios de tensión tolerable (contacto y paso)",
    "official_publisher": "IEEE",
}
RETIE_SOURCE = {
    "document": "Reglamento Técnico de Instalaciones Eléctricas (RETIE), Resolución 40284 de 2026, Libro 3",
    "edition": "2026-06-23",
    "clause": "Artículo 3.12.1 literal g, Tabla 3.12.1.a",
    "url": "https://www.minenergia.gov.co/documents/15921/Libro-3-Resolucion-40284-23-06-2026.pdf",
    "official_publisher": "Ministerio de Minas y Energía de Colombia",
}

IEEE80: dict[str, Any] = {
    "profile_id": "allectricity.ieee80-2013.substation-ac",
    "definition": {
        "title": "IEEE 80-2013 · subestaciones de corriente alterna",
        "jurisdiction": "global",
        "installation_type": INSTALLATION,
        "description": "Tensiones de contacto y de paso tolerables por el método del cuerpo humano de IEEE 80-2013. "
                       + _BASE_NOTE,
        "required_mandatory_criteria": ["touch", "step"],
        "rules": [
            {
                "id": "ieee80-2013-touch", "category": "mandatory", "criterion": "touch", "applicability": "applicable",
                "applicability_conditions": [
                    "Subestación de corriente alterna con personas que pueden tocar estructuras puestas a tierra durante una falla.",
                    "El límite depende del peso corporal (50 o 70 kg), el tiempo de despeje y la capa superficial.",
                ],
                "verification_method": "Comparar la tensión de contacto máxima calculada sobre la malla con la tensión de "
                                       "contacto tolerable de IEEE 80-2013 para el peso corporal, el tiempo de despeje y la capa superficial del proyecto.",
                "expression": "E_contacto ≤ E_contacto tolerable (método del cuerpo humano, IEEE 80-2013).",
                "source": IEEE80_SOURCE,
            },
            {
                "id": "ieee80-2013-step", "category": "mandatory", "criterion": "step", "applicability": "applicable",
                "applicability_conditions": [
                    "Subestación de corriente alterna con personas que pueden caminar sobre la malla o en su perímetro durante una falla.",
                    "El límite depende del peso corporal (50 o 70 kg), el tiempo de despeje y la capa superficial.",
                ],
                "verification_method": "Comparar la tensión de paso máxima calculada con la tensión de paso tolerable de "
                                       "IEEE 80-2013 para el peso corporal, el tiempo de despeje y la capa superficial del proyecto.",
                "expression": "E_paso ≤ E_paso tolerable (método del cuerpo humano, IEEE 80-2013).",
                "source": IEEE80_SOURCE,
            },
        ],
    },
}

RETIE_2026: dict[str, Any] = {
    "profile_id": "allectricity.retie-2026.substation-ac",
    "definition": {
        "title": "RETIE 2026 · subestaciones de corriente alterna (Colombia)",
        "jurisdiction": "Colombia",
        "installation_type": INSTALLATION,
        "description": "Contacto con el límite de la Tabla 3.12.1.a del RETIE (Resolución 40284 de 2026) y paso por la "
                       "metodología IEEE 80, como exige el Art. 3.12.1 literal g. Las tensiones transferidas, la profundidad "
                       "de electrodos horizontales (NTC 2050) y la resistencia de referencia quedan como reglas por "
                       "confirmar en cada proyecto. " + _BASE_NOTE,
        "required_mandatory_criteria": ["touch", "step"],
        "rules": [
            {
                "id": "retie-2026-l3-3.12.1-g-touch", "category": "mandatory", "criterion": "touch", "applicability": "applicable",
                "applicability_conditions": [
                    "El artículo exige evaluar las tensiones de contacto según la metodología IEEE 80.",
                    "El límite se elige según exposición pública u ocupacional, tiempo de despeje y existencia de capa superficial.",
                    "La tabla RETIE se aplica cuando no hay capa superficial; la evaluación IEEE 80-2013 y la tabla RETIE se registran por separado.",
                ],
                "verification_method": "Comparar la tensión de contacto calculada con el límite RETIE aplicable al escenario: "
                                       "clase de exposición, tiempo de despeje, condición superficial y fila de la tabla.",
                "expression": "Tensión de contacto ≤ límite de la Tabla 3.12.1.a del RETIE para la exposición y el tiempo de despeje.",
                "source": RETIE_SOURCE,
            },
            {
                "id": "retie-2026-l3-3.12.1-g-step", "category": "mandatory", "criterion": "step", "applicability": "applicable",
                "applicability_conditions": [
                    "El artículo exige calcular las tensiones de paso con la metodología IEEE 80.",
                    "La Tabla 3.12.1.a contiene límites de contacto; no se reutiliza como límite de paso.",
                ],
                "verification_method": "Comparar la tensión de paso calculada con el límite de paso tolerable de IEEE 80 para "
                                       "el escenario; el límite RETIE de contacto no se usa para el paso.",
                "expression": "Tensión de paso ≤ tensión de paso tolerable por IEEE 80, como exige el Art. 3.12.1 literal g.",
                "source": RETIE_SOURCE,
            },
            {
                "id": "retie-2026-l3-ground-transfer", "category": "mandatory", "criterion": "transferred", "applicability": "unknown",
                "applicability_conditions": [
                    "El RETIE exige evitar tensiones transferidas peligrosas durante una falla.",
                    "Aplica cuando hay elementos metálicos que salen de la malla (cercas, rieles, tuberías, blindajes); "
                    "cada caso requiere identificar el elemento, el punto accesible y la clase de exposición.",
                ],
                "verification_method": "Para cada elemento transferido, comparar la tensión transferida con el límite de "
                                       "contacto aplicable a su exposición; confirmar el criterio por proyecto.",
                "expression": "Evitar tensiones transferidas peligrosas en elementos metálicos accesibles fuera de la malla.",
                "source": {**RETIE_SOURCE, "clause": "Artículo 3.12.1"},
            },
            {
                "id": "retie-2026-l3-reference-resistance-hv-substation", "category": "guidance",
                "target": "ground_resistance_ohm", "applicability": "unknown",
                "applicability_conditions": [
                    "La tabla de referencia indica 1 Ω para subestaciones de alta y extra alta tensión; confirma la clase de tensión del proyecto.",
                    "Alcanzar la resistencia de referencia no sustituye el control de las tensiones de paso, contacto y transferidas.",
                ],
                "verification_method": "Verificar la clase de tensión y reportar el valor solo como referencia.",
                "expression": "Valor de referencia de resistencia de puesta a tierra: 1 Ω para subestaciones de alta y extra alta tensión.",
                "source": {**RETIE_SOURCE, "clause": "Artículo 3.12.3, Tabla 3.12.3.a"},
            },
        ],
    },
}

DEFAULT_PROFILES = (IEEE80, RETIE_2026)
STANDARD_PROFILES = {
    "IEEE 80-2013": IEEE80["profile_id"],
    "RETIE 2026 (Resolución 40284)": RETIE_2026["profile_id"],
}
