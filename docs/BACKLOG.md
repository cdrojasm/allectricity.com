# Backlog de entrega — Agente SPAT

## Objetivo y criterio de arquitectura

El producto mantiene un único núcleo Python y se despliega como imagen OCI. La
infraestructura concreta es un adaptador: Docker Compose en local y manifiestos
Kubernetes/Kustomize como base para OKD, EKS, AKS o GKE. Los secretos no van en
la imagen ni en los manifiestos base.

El cálculo actual es un **estimador de prefactibilidad**, deliberadamente
marcado como no certificable. Ninguna salida debe presentarse como memoria de
cálculo aprobada hasta completar la épica normativa y la revisión de un
ingeniero competente.

| Prioridad | Estado verificado | Épica / tarea | Entregable y criterio de aceptación | Dependencias |
|---|---|---|---|---|
| P0 | ⬜ Pendiente | Alinear alcance regulatorio | Matriz de versiones IEEE 80, RETIE, NTC 2050, IEC 62305 y jurisdicción; responsable técnico firma los supuestos. | Product owner + ingeniero electricista |
| P0 | ◐ Parcial | Contrato del artefacto vivo | JSON Schema versionado para diseño, geometría, capas, escenarios, resultados y diff; migraciones de schema. Hay modelos de dominio y schemas de API para el diseño, pero no JSON Schema versionado ni migraciones del artefacto. | Alcance |
| P0 | ◐ Parcial | Persistencia | Puerto `DesignRepository`, adaptador PostgreSQL y almacenamiento S3/MinIO para fuentes y artefactos; pruebas de integración. Existe el puerto y un adaptador en memoria; MinIO gestiona cargas. Los artefactos de diseño de tierras se versionan en PostgreSQL (`artefacto_diseno_tierras`), y sus cálculos de potencial con resultado y trace en `calculos_potencial_tierras` (migración 0008, con pruebas de integración en SQLite). Falta el repositorio PostgreSQL de diseños y probar la migración 0008 en PostgreSQL. | Contrato |
| P0 | ◐ Parcial | Motor IEEE 80 trazable | Implementar fórmulas, factores, conductor térmico, GPR, paso/contacto y casos de prueba validados contra ejemplos de referencia. Cada resultado registra versión normativa y entradas. El motor numérico (`services/potential_engine`, protocolo `SPAT-POTENTIAL-3`) calcula R, GPR, contacto y paso en suelo homogéneo, de dos capas o de 3–8 capas horizontales (kernel n capas, solver 3.2.0), validado contra IEEE 80-2013 Anexos B y H, con diagnóstico, incertidumbre y trace. El backend aplica D_f y S_f y los tolerables de IEEE 80-2013 con Cs, y registra norma y edición en cada cálculo. Faltan el conductor térmico, la firma del revisor (`services/potential_engine/validation/REVIEW.md`) y reemplazar el estimador preliminar del caso de uso `assess_grounding_design`. | Matriz normativa |
| P0 | ◐ Parcial | Seguridad de API | OIDC/JWT, RBAC por proyecto, límites de carga, CORS restringido, auditoría de cambios y gestión externa de secretos. Hay JWT HS256, permisos por endpoint, límites de carga, CORS local y auditoría de identidad; Google ID tokens está disponible, pero faltan roles por proyecto y gestión externa de secretos. | Persistencia |
| P0 | ◐ Parcial | Despliegue local | `.env` desde plantilla, `make local-up`, healthcheck y smoke test reproducible; no requiere credenciales cloud. Hay `make local-config`/`local-up`, healthchecks y `make smoke-auth`; falta un smoke test general de despliegue que verifique el criterio publicado. | Scaffold actual |
| P1 | ◐ Parcial | Ingesta geotécnica | Adaptador XLSX/CSV Wenner/Schlumberger con validación de unidades, errores de medición y trazabilidad de archivo. `calculations/soil_model.py` valida las mediciones (espaciamientos, arreglos y número mínimo de lecturas) y detecta lecturas atípicas. Faltan el adaptador XLSX/CSV, el endpoint y la trazabilidad del archivo. | Contrato |
| P1 | ◐ Parcial | Estratificación | Inversión de suelo 2 capas (rho1, rho2, h), intervalos de incertidumbre y gráfica de ajuste. Hecho en `calculations/soil_model.py`: inversión de dos capas por Levenberg-Marquardt, incertidumbre por parámetro, error RMS, residuos por lectura y salida en formato de artefacto, validado con sondeos sintéticos de los suelos del Anexo H de IEEE 80. De 3 a 8 capas: `calculations/n_layer_soil.py` (transformada de Koefoed con imágenes reales ajustadas, exclusión de atípicas por validación cruzada, incertidumbre por parámetro y límites del motor), contrastado con los sondeos publicados de 3 y 4 capas de los USGS OFR 80-190 y 81-160. Faltan la gráfica de ajuste y la vista de n capas en el frontend. | Ingesta geotécnica |
| P1 · Orden 3 | ◐ Hecho en backend y motor; falta revisión independiente y frontend | Suelo de más de dos capas | Motor 3.2.0: línea `n-layer` de 1–8 capas (protocolo `SPAT-POTENTIAL-3` extendido, compatible con homogéneo y dos capas); kernel por recursión de reflexión generalizada e imágenes exponenciales ajustadas con cota de error a posteriori; cortes en todas las interfaces; artefactos de 3–8 capas y ajuste Wenner/Schlumberger conectados de punta a punta. Validado contra una referencia independiente (integral de Hankel con sistema de contorno completo), la serie exacta de dos capas y los Grids 3/6 y Exhibit 1, con reciprocidad, continuidad, convergencia y límites de coste medidos. Detalle y brechas en `services/potential_engine/BACKLOG.md`. | Suelo de dos capas + coordinación con mallas grandes |
| P1 · Orden 4 | ⬜ Pendiente | Impedancia de conductor y escalera de cables de guarda | Modelar impedancia longitudinal, uniones y retorno distribuido por tramos/apoyos/tierras de torre, acoplado con la malla para obtener reparto de corriente y potenciales transferidos; validar y medir en mallas extensas. | Red nodal de conductores + rendimiento de mallas grandes + reparto de corriente |
| P1 | ◐ Parcial | Ingesta documental | Adaptadores PDF/DOCX/OCR, extracción con confianza y cola de confirmaciones humanas para Ik, ts y capa superficial. Se extrae texto de PDF, CSV, XLSX e imágenes vía OCR con indicador de confianza; faltan DOCX y confirmación técnica de parámetros. | Almacenamiento |
| P1 | ◐ Parcial | Pipeline documental en Celery | Tarea asíncrona por archivo con antivirus/MIME, OCR HTTP, extracción determinista, agentes configurables con prompts Langfuse, evidencia y persistencia en Neo4j. Falta idempotencia explícita y exponer/resolver preguntas desde la interfaz. | Almacenamiento + servicio OCR |
| P1 | ✅ Implementado (requiere configurar Langfuse y proveedor LLM) | Revisión con agente especialista | Agente ReAct limitado a búsqueda/lectura documental; genera propuestas con evidencia textual y solo admite citas presentes en la fuente. No aprueba parámetros. | Pipeline documental + prompts Langfuse |
| P1 | ✅ Implementado (requiere configurar Langfuse y proveedor LLM) | Consolidación de hallazgos | Consolida propuestas, marca casos para revisión y crea preguntas enlazadas al archivo y a sus hallazgos en Neo4j. | Revisión especialista + grafo |
| P1 | ⬜ Pendiente | Confirmación técnica de entradas | Añadir una bandeja de revisión para valores que afectan cálculos; validar tipos, unidades y rangos con reglas deterministas y exigir confirmación humana ante incertidumbre. | Consolidación + motor trazable |
| P1 | ⬜ Pendiente | ICR y extracción manuscrita multimodal | Evaluar ICR/proveedor multimodal detrás de un adaptador; enviar páginas o regiones ambiguas, pedir transcripción estructurada con evidencia, medir precisión y requerir confirmación para valores críticos. | Servicio OCR + revisión humana + proveedor aprobado |
| P1 | ◐ Parcial | Servicio OCR desacoplado | Operar OCR como servicio HTTP en contenedor local y definir un adaptador reemplazable por AWS Textract u otro proveedor; incluir autenticación interna, límites, timeout, salud y métricas. Hay servicio HTTP en contenedor, límite de tamaño, timeout de cliente y healthcheck; faltan autenticación interna, métricas y adaptador de proveedor administrado. | Pipeline documental |
| P1 | ◐ Parcial | CAD y canvas | DXF primero con `ezdxf`; extracción de capas/geometría, renderer SVG y comandos de selección/diff. DWG mediante conversor licenciado o servicio aprobado. El prototipo permite editar malla y varillas, versionar en sesión y exportar JSON; no hay importación DXF/DWG ni diff CAD. | Contrato |
| Por priorizar | ⬜ Pendiente | Editor de geometría en canvas con paleta | Canvas para dibujar geometrías irregulares con paleta de conductor, varilla, cerca y obstáculos constructivos que no se pueden atravesar; esquema de geometría v2 del artefacto, reglas geométricas en frontend y backend y conversión a segmentos del motor (que ya admite cualquier red de segmentos rectos). Estimación: MVP 2–3 semanas, versión sólida 6–8. Desglose y dudas abiertas (naturaleza de los obstáculos, cruces, curvas, profundidad, DXF, migración, coordinación con el frontend) en `services/potential_engine/BACKLOG.md`. | Esquema de geometría v2; CAD y canvas; coordinación con la tarea del frontend |
| P1 | ⬜ Pendiente | Bucle de optimización | Generar alternativas (retícula, jabalinas, gravilla) bajo restricciones de costo y reportar fronteras; nunca aplicar sin crear versión nueva. | Motor IEEE 80 + BOM |
| P1 | ⬜ Pendiente | BOM y reporte | Lista de materiales y memoria PDF/DOCX con ecuaciones, unidades, fuentes, versión de norma y firma/revisión. | Motor trazable |
| P1 | ⬜ Pendiente | RAG normativo | Corpus con licencias verificadas, citas por sección/página, control de versión y respuestas que distingan cita de inferencia. | Matriz normativa |
| P2 | ⬜ Pendiente | IEC 62305 | Evaluación de esfera rodante y ángulo de protección como caso de uso separado, con su propio set de pruebas. | Matriz normativa |
| P2 | ◐ Parcial | Simulación numérica | Puerto `FiniteElementSimulator`, jobs asíncronos y comparación contra el solver analítico. Existe un solver numérico por método de momentos (no elementos finitos) en jobs Celery (`spat.calculate_artifact_potential`), comparado contra fórmulas cerradas y resultados publicados. Faltan el puerto de dominio y un simulador FEM. | Persistencia + colas |
| P2 | ◐ Parcial | Voz e imágenes | STT y detección de marcas rojas con confirmación visual de la intención antes de modificar el artefacto. Hay entrada de voz mediante Speech Recognition del navegador; faltan detección de marcas y confirmación visual. | Canvas |
| P2 | ⬜ Pendiente | Observabilidad y operación | Trazas OTel, métricas de cálculo/colas, panel y runbook; SLOs definidos. | API + workers |
| P2 | ⬜ Pendiente | Mapa de potencial superficial U | Graficar U sobre la malla y los elementos físicos (varillas, cercas) con los puntos de contacto y paso peores. El motor ya calcula U en cualquier rejilla y el `trace` trae la geometría, pero el resultado del artefacto no guarda la rejilla y la gráfica del frontend es ilustrativa. Entregar rejilla persistida y expuesta por API/CSV, y vista de mapa de calor o isolíneas. Detalle en `services/potential_engine/BACKLOG.md`. | Motor de potencial; coordinación con la tarea del frontend |

**Leyenda:** ✅ completo según el criterio de aceptación; ◐ existe una parte, pero faltan criterios; ⬜ sin implementación verificable en este repositorio. Estados contrastados con el código y documentación presentes al 2026-10-04. Las filas actualizadas ese día (persistencia, motor IEEE 80, ingesta geotécnica, estratificación y simulación numérica) se verificaron con la suite completa: 143 pruebas en la imagen Docker de tests con SQLite.

## Plan de despliegue

1. Local: ejecutar `make local-config`, `make local-up` y `make create-admin`.
   Verificar `http://localhost:18000/ready`. Dependencias, migraciones y pruebas
   se ejecutan exclusivamente dentro de Docker; ver [AUTH.md](AUTH.md).
2. CI: ejecutar lint, unit tests, pruebas de contrato y construir/publicar una
   imagen OCI etiquetada con versión y SHA.
3. Cualquier clúster: adaptar el scaffold `deploy/kubernetes/base` para incluir
   migraciones, workers, scheduler y referencias a PostgreSQL/Redis/SMTP/secretos;
   reutilizar la misma imagen probada en Compose.
4. Producción: añadir HPA, ingress, política de red, backup/retención y una
   aprobación de ingeniería antes de habilitar exportaciones certificables.

## Avance de backend — 2026-10-02

Implementados: autenticación HS256, refresh/revocación, permisos por endpoint,
usuarios/roles/M2M, adaptador Google, presupuesto y ledger de tokens, outbox cifrado
para resets con Celery/SMTP, migraciones y Compose con PostgreSQL de pruebas aislado.
Pendientes del frente de identidad: UI de login/reset, Google Client ID del proyecto,
vinculación explícita de cuentas, roles por proyecto cuando exista esa entidad,
retención operativa y adaptación de manifiestos de clúster.

## Avance del motor de potencial — 2026-10-04

Rama `p1-motor-potencial`. Incluye:
- Corrección del error de factor 2 del motor v1: los resultados de `SPAT-POTENTIAL-1` no son válidos.
- Los P0 del motor: validación, convergencia, diagnóstico, trazabilidad y límites.
- Integración asíncrona con los artefactos.
- Suelo de dos capas, validado con los Grids 3–6 del Anexo H.
- Suelo de 3–8 capas (2026-10-05): kernel n capas del motor 3.2.0, artefactos y ajuste Wenner/Schlumberger de n capas.
- Modelo de suelo desde mediciones.
- Criterios tolerables de IEEE 80-2013 con capa superficial.
- Reparto de corriente de falla.
- Segmentación graduada con incertidumbre numérica.

El detalle y los pendientes están en [services/potential_engine/BACKLOG.md](../services/potential_engine/BACKLOG.md).

## Riesgos a cerrar antes de producción

- Confirmar derechos de uso y actualización de todas las normas y tablas.
- Definir responsabilidad profesional y flujo de aprobación: el agente asiste,
  no sustituye la firma de un ingeniero habilitado.
- Acordar el conversor DWG: `ezdxf` maneja DXF, no DWG nativo.
- Datos de validación independientes: el motor de potencial ya se valida contra fórmulas cerradas y los Anexos B y H de IEEE 80-2013. Faltan:
  - la firma del revisor;
  - el cotejo de los valores transcritos con una copia licenciada;
  - las tablas de EN 50522 y RETIE;
  - la comparación con mediciones de campo.
