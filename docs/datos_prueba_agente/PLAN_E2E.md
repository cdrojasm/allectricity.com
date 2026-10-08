# Plan de prueba e2e — SE La Esperanza

Se ejecuta en el frontend local (`http://127.0.0.1:3000`), modo **asistido**, con los archivos de
esta carpeta. Cada paso registra: qué se hizo, qué respondió el agente, versión del artefacto y
desviaciones.

| # | Paso | Archivo / mensaje | Esperado |
|---|---|---|---|
| 1 | Crear proyecto «SE La Esperanza e2e» | — | Proyecto y conversación vacíos |
| 2 | Cargar documentos | 01, 05, 06, 07, 08, 03, 04 | Todos `available`; PDF/DOCX procesados al grafo |
| 3 | Importar CAD | 03 en «Plano de fondo y CAD» | Propuesta 40 × 30 m, 15 conductores, 16 varillas |
| 4 | Pedir malla por chat | «Diseña la malla del patio: 40 × 30 m, retícula 5 m en X y 6 m en Y, profundidad 0,5 m, varillas de 2,4 m en esquinas y cada 10 m en el perímetro.» | Versión nueva; tarjeta «Se editó el artefacto»; no pide nombre |
| 5 | Suelo desde archivo | «Usa el sondeo SEV-2 del CSV para el modelo de suelo.» | Convierte R→ρa; ≈ 410 Ω·m / 2,0 m sobre 120 Ω·m; reporta RMS |
| 6 | Pedir cálculo sin datos de falla | «Calcula la seguridad de la malla.» | No encola; lista Ik, t_s y capa superficial |
| 7 | Completar faltantes | «Según el estudio EC-02: falla monofásica 8,5 kA, despeje 0,5 s, gravilla 3000 Ω·m de 0,15 m.» | Ik = 8500 A (dice la conversión); capa 0,15 m |
| 8 | Calcular | «Calcula.» (y confirmar si pregunta) | `waiting_calculation` → reanuda; veredicto, R, GPR, contacto y paso con márgenes |
| 9 | Ajustar si no cumple | Seguir la recomendación del agente | Versión nueva y recálculo |
| 10 | Visualizar artefacto | Vista del artefacto / plano | Malla, varillas, suelo y resultados coherentes con el chat |
| 11 | Publicar estudio | «Compartir estudio» | Página del estudio con entradas, resultado y trazabilidad |
| 12 | Generar PDF | «Generar PDF» y descargar | PDF `ready` y descargable |
