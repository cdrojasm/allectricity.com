# Validación del dimensionamiento térmico por IEC 60364-5-54 y RETIE (A7/A8)

Contraste hecho el 2026-11-14 con IEC 60364-5-54:2011 (edición 3.0, copia licenciada) y con la Resolución Minenergía 40117 del
2 de abril de 2024 (Libro 3, 3.12.2.2). Las tablas y ecuaciones se verificaron en imagen. Código en
`backend/src/infrastructure/calculations/conductor_thermal_profiles.py`, datos en `backend/src/domain/spat/thermal_profiles/`
y pruebas en `tests/infrastructure/test_conductor_thermal_standards.py`.

**Estado:** contraste técnico del equipo de desarrollo; no sustituye la firma independiente (ver `BACKLOG.md`). Los perfiles
existen y se calculan, pero **aún no se eligen por proyecto**: eso depende de la «Matriz normativa».

## A7. IEC 60364-5-54:2011

- **Ecuación (543.1.2):** `S = I·√t / k`, con `I` en A y `t ≤ 5 s`. Para tiempos mayores el cálculo lo rechaza e indica IEC 60949.
- **k (Anexo A):** `k = sqrt( Qc·(β+20)/ρ20 · ln((β+θf)/(β+θi)) )`, con los parámetros de la Tabla A.54.1 (cobre, aluminio, acero).
- **Contraste:** el k calculado reproduce los 12 valores impresos de las Tablas A.54.3 y A.54.6 (cobre, aluminio y acero a 150, 200,
  220, 300 y 500 °C) con diferencia máxima de 0,5 unidades, y el término de la Tabla A.54.1 (226, 148, 78) con 0,5 %.
- **Límite:** la norma no trae un ejemplo numérico de dimensionamiento; el contraste es contra sus tablas de k. IEC 60949 (que
  añade el efecto no adiabático) no está disponible y no se necesita para t ≤ 5 s.

## A8. RETIE 2024 (Resolución 40117)

- **Alta, media y extra alta tensión (Ec. 4):** `A[mm²] = I[kA]·Kf·√tc / 1,9737`, con la Tabla 3.12.2.2.a tal como está impresa
  (14 filas). Reproduce el ejemplo B.2 de IEEE 80 (17,2 mm²) y el ejemplo de §11.3.1.3 para cobre blando (242,5 kcmil).
- **Baja tensión (Ec. 3):** la Ec. 3 usa `K` del Anexo A de IEC 60364-5-54, o la Tabla 250-66 de la NTC 2050. El cálculo con `K` de
  la IEC es A7; la tabla NTC 2050 no está cargada y no se calcula aquí.
- **Tipo de unión:** a diferencia de IEEE 80, RETIE sí da temperatura por unión para el cobre duro: soldadura exotérmica 1084 °C
  (Kf 7,06) y conector mecánico 250 °C (Kf 11,78).

### Observaciones sobre el texto del reglamento

1. **Fila de 30 %:** el alambre de acero cobreado 30 % trae Kf 14,64, que es el de la varilla; IEEE 80 da 12,06. Se usa el impreso
   (más conservador).
2. **Kf de la edición 2000:** acero 1020 (15,95), varilla cobreada 20 % (14,64) y varilla inox revestida (14,72). Frente a IEEE 80-2013
   (Tabla 1) el Kf de RETIE es menor en 13, 8 y 19 %. El resultado se calcula con el valor del reglamento y lleva una advertencia con
   la diferencia, sin corregirlo.
3. **Unidades de la Ec. 3:** el texto dice «I en kA», pero con `K` en A·√s/mm² la sección solo resulta en mm² si `I` está en A. El
   código toma A.
4. **Conductividad del zinc:** 8,5 % (IEEE 80 imprime 8,6 %); no afecta el cálculo.
5. **Alambre revestido de aluminio:** Kf 17,2 (IEEE 80, 17,26).

### Cita de la norma en el repositorio

`safety_criteria.py` cita la Tabla 3.12.1.a como «RETIE 2026 (Resolución 40284)». Los valores coinciden uno a uno con la Tabla
3.12.1.a de la Resolución **40117 de 2024**, pero la cita dice 40284. Hay que confirmar cuál es la resolución vigente y corregir la
etiqueta si corresponde. Además, la 40117 tiene régimen de transición (instalaciones cuya construcción inició bajo la Resolución
90708 de 2013 pueden certificarse con esa).

## Pendiente

- Elegir el perfil por proyecto (Matriz normativa) y mostrar la advertencia de RETIE en la traza y la interfaz.
- Tabla 250-66 de la NTC 2050 para el conductor al electrodo en baja tensión.
- IEC 60949, si se necesita el efecto no adiabático o tiempos mayores de 5 s.
