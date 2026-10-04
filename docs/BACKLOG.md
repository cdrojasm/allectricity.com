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
| P0 | ◐ Parcial | Persistencia | Puerto `DesignRepository`, adaptador PostgreSQL y almacenamiento S3/MinIO para fuentes y artefactos; pruebas de integración. Existe el puerto y un adaptador en memoria; MinIO gestiona cargas, pero no hay repositorio PostgreSQL de diseños ni persistencia de artefactos. | Contrato |
| P0 | ⬜ Pendiente | Motor IEEE 80 trazable | Implementar fórmulas, factores, conductor térmico, GPR, paso/contacto y casos de prueba validados contra ejemplos de referencia. Cada resultado registra versión normativa y entradas. El cálculo actual está documentado como estimador no certificable. | Matriz normativa |
| P0 | ◐ Parcial | Seguridad de API | OIDC/JWT, RBAC por proyecto, límites de carga, CORS restringido, auditoría de cambios y gestión externa de secretos. Hay JWT HS256, permisos por endpoint, límites de carga, CORS local y auditoría de identidad; Google ID tokens está disponible, pero faltan roles por proyecto y gestión externa de secretos. | Persistencia |
| P0 | ◐ Parcial | Despliegue local | `.env` desde plantilla, `make local-up`, healthcheck y smoke test reproducible; no requiere credenciales cloud. Hay `make local-config`/`local-up`, healthchecks y `make smoke-auth`; falta un smoke test general de despliegue que verifique el criterio publicado. | Scaffold actual |
| P1 | ⬜ Pendiente | Ingesta geotécnica | Adaptador XLSX/CSV Wenner/Schlumberger con validación de unidades, errores de medición y trazabilidad de archivo. | Contrato |
| P1 | ⬜ Pendiente | Estratificación | Inversión de suelo 2 capas (rho1, rho2, h), intervalos de incertidumbre y gráfica de ajuste. | Ingesta geotécnica |
| P1 | ◐ Parcial | Ingesta documental | Adaptadores PDF/DOCX/OCR, extracción con confianza y cola de confirmaciones humanas para Ik, ts y capa superficial. Se extrae texto de PDF, CSV, XLSX e imágenes vía OCR con indicador de confianza; faltan DOCX y confirmación técnica de parámetros. | Almacenamiento |
| P1 | ◐ Parcial | Pipeline documental en Celery | Tarea asíncrona por archivo con antivirus/MIME, OCR HTTP, extracción determinista, agentes configurables con prompts Langfuse, evidencia y persistencia en Neo4j. Falta idempotencia explícita y exponer/resolver preguntas desde la interfaz. | Almacenamiento + servicio OCR |
| P1 | ✅ Implementado (requiere configurar Langfuse y proveedor LLM) | Revisión con agente especialista | Agente ReAct limitado a búsqueda/lectura documental; genera propuestas con evidencia textual y solo admite citas presentes en la fuente. No aprueba parámetros. | Pipeline documental + prompts Langfuse |
| P1 | ✅ Implementado (requiere configurar Langfuse y proveedor LLM) | Consolidación de hallazgos | Consolida propuestas, marca casos para revisión y crea preguntas enlazadas al archivo y a sus hallazgos en Neo4j. | Revisión especialista + grafo |
| P1 | ⬜ Pendiente | Confirmación técnica de entradas | Añadir una bandeja de revisión para valores que afectan cálculos; validar tipos, unidades y rangos con reglas deterministas y exigir confirmación humana ante incertidumbre. | Consolidación + motor trazable |
| P1 | ⬜ Pendiente | ICR y extracción manuscrita multimodal | Evaluar ICR/proveedor multimodal detrás de un adaptador; enviar páginas o regiones ambiguas, pedir transcripción estructurada con evidencia, medir precisión y requerir confirmación para valores críticos. | Servicio OCR + revisión humana + proveedor aprobado |
| P1 | ◐ Parcial | Servicio OCR desacoplado | Operar OCR como servicio HTTP en contenedor local y definir un adaptador reemplazable por AWS Textract u otro proveedor; incluir autenticación interna, límites, timeout, salud y métricas. Hay servicio HTTP en contenedor, límite de tamaño, timeout de cliente y healthcheck; faltan autenticación interna, métricas y adaptador de proveedor administrado. | Pipeline documental |
| P1 | ◐ Parcial | CAD y canvas | DXF primero con `ezdxf`; extracción de capas/geometría, renderer SVG y comandos de selección/diff. DWG mediante conversor licenciado o servicio aprobado. El prototipo permite editar malla y varillas, versionar en sesión y exportar JSON; no hay importación DXF/DWG ni diff CAD. | Contrato |
| P1 | ⬜ Pendiente | Bucle de optimización | Generar alternativas (retícula, jabalinas, gravilla) bajo restricciones de costo y reportar fronteras; nunca aplicar sin crear versión nueva. | Motor IEEE 80 + BOM |
| P1 | ⬜ Pendiente | BOM y reporte | Lista de materiales y memoria PDF/DOCX con ecuaciones, unidades, fuentes, versión de norma y firma/revisión. | Motor trazable |
| P1 | ⬜ Pendiente | RAG normativo | Corpus con licencias verificadas, citas por sección/página, control de versión y respuestas que distingan cita de inferencia. | Matriz normativa |
| P2 | ⬜ Pendiente | IEC 62305 | Evaluación de esfera rodante y ángulo de protección como caso de uso separado, con su propio set de pruebas. | Matriz normativa |
| P2 | ⬜ Pendiente | Simulación numérica | Puerto `FiniteElementSimulator`, jobs asíncronos y comparación contra el solver analítico. | Persistencia + colas |
| P2 | ◐ Parcial | Voz e imágenes | STT y detección de marcas rojas con confirmación visual de la intención antes de modificar el artefacto. Hay entrada de voz mediante Speech Recognition del navegador; faltan detección de marcas y confirmación visual. | Canvas |
| P2 | ⬜ Pendiente | Observabilidad y operación | Trazas OTel, métricas de cálculo/colas, panel y runbook; SLOs definidos. | API + workers |

**Leyenda:** ✅ completo según el criterio de aceptación; ◐ existe una parte, pero faltan criterios; ⬜ sin implementación verificable en este repositorio. Estados contrastados con el código y documentación presentes al 2026-10-04; las pruebas automatizadas no se ejecutaron durante esta revisión.

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

## Riesgos a cerrar antes de producción

- Confirmar derechos de uso y actualización de todas las normas y tablas.
- Definir responsabilidad profesional y flujo de aprobación: el agente asiste,
  no sustituye la firma de un ingeniero habilitado.
- Acordar el conversor DWG: `ezdxf` maneja DXF, no DWG nativo.
- Establecer datos de validación independientes para modelos de suelo y cálculo.
