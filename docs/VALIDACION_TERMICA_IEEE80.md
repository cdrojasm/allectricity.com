# Validación del dimensionamiento térmico IEEE 80-2013 (A1/A2)

Contraste del módulo `conductor_thermal` con una copia licenciada de IEEE Std 80-2013 (con Corrigendum 1-2015),
revisada el 2026-11-11 página por página: §11.3.1 a §11.3.3, Tablas 1 y 2 y Anexo B. Las pruebas están en
`tests/infrastructure/test_conductor_thermal.py` y `tests/domain/test_thermal_profile.py`; las constantes viven en
`backend/src/domain/spat/thermal_profiles/ieee-80-2013.json`, cada fila con su fuente.

**Estado:** contraste técnico hecho por el equipo de desarrollo. No sustituye la firma independiente de un ingeniero
competente, que sigue postergada (ver `BACKLOG.md`).

## Correcciones hechas

| Material | Antes | Ahora (Tabla 1, 2013) | Efecto |
|---|---|---|---|
| Acero 1020 | α 0,0016, K0 605, TCAP 3,28 (edición 2000), Kf 15,95 | α 0,00377, K0 245, TCAP 3,8, Kf 18,39 | La sección mínima sube 15 %. Antes quedaba 13 % por debajo de la Tabla 2. |
| Varilla acero cobreado | 20 %, ρ 8,62 | 17 %, ρ 10,1 (id `copper_clad_rod_17`; `copper_clad_rod_20` queda como alias) | La sección mínima sube 8 %. |
| Varilla inox revestida | α 0,0016, K0 605, TCAP 4,44 | α 0,00377, K0 245, TCAP 4,4 | La sección mínima sube 24 %. |
| Acero revestido de aluminio | TCAP 3,58 | TCAP 3,561 | −0,3 % en Kf. |

## Inconsistencias de la propia norma

1. **Tabla 2 sin actualizar:** las filas de la varilla cobreada (14,64) y de la inox revestida (14,72) conservan el Kf de la
   edición 2000. La Tabla 1 de 2013 cambia sus constantes (y deriva ρ = 10,1 en la misma página). Se sigue la Tabla 1; su Kf es
   mayor (15,84 y 18,26), es decir, conservador.
2. **Ejemplo (c) de §11.3.1.3:** usa Kf = 15,95 para acero (552,5 kcmil), valor de la edición 2000. La Tabla 1 y la Tabla 2 de
   2013 coinciden en 18,39 (637,0 kcmil).
3. **Anexo B, ejemplo B.3:** imprime 59,81 kcmil para acero cobreado 30 %, 0,5 s, 700 °C y 6,814 kA. La Ec. (46) con las
   entradas impresas en la misma línea da 65,88 kcmil. Posible errata; no se usa como valor de referencia.

## Casos que reproducen la norma (≤ 0,1 %)

Kf de la Tabla 2 para las 9 filas coherentes, incluido cobre duro a 250 °C (11,78); ejemplo de §11.3.1.2 (12,06 kcmil);
ejemplos de §11.3.1.3 para cobre recocido (242,5) y acero cobreado 40 % (362,0); Anexo B.2 (34,02 kcmil, 17,2 mm²); y una
reimplementación independiente de la Ec. (46) en unidades inglesas para cada material.

## TCAP

Table 1 imprime TCAP con un decimal (3,4 / 3,8 / 4,4 / 3,9 / 4,0). Para cobre, cobre cobreado, zinc y 304 se usa el valor sin
redondear (3,42 / 3,85 / 3,93 / 4,03), el que reproduce la Tabla 2 y los ejemplos de la propia norma (el ejemplo de §11.3.1.2
usa 3,85). El perfil guarda ambos valores y rechaza diferencias mayores que el redondeo.

## Temperatura por tipo de unión

IEEE 80-2013 **no** da una tabla de temperatura máxima por tipo de unión. §11.3.3 solo recomienda no superar 250 °C en cobre
duro (para evitar el recocido) y remite a IEEE 837 y al fabricante. Por eso `maximum_temperature_c` sigue siendo una entrada
explícita, con la fusión del material (Tabla 1) como tope; el tipo de unión se registra, pero no fija la temperatura.
Pendiente: IEEE 837 o datos del fabricante si se quiere sugerir valores por unión.

## Pendiente

- Revisión de A2 contra Tabla 1 y 2 de la edición vigente cuando haya una nueva edición o fe de erratas.
- Aclarar con el comité o con IEEE si las inconsistencias 1 a 3 tienen corrección publicada.
