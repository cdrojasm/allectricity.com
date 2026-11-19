# Descubrimiento web de materiales (OP-03)

`POST /api/v1/material-catalog/discover` encola una búsqueda de páginas públicas y devuelve
`{ "job_id": "...", "status": "queued", "poll_after_ms": 1200 }`. El worker Celery ejecuta
la búsqueda fuera de la petición HTTP. Consulta `GET /api/v1/material-catalog/discover/{job_id}`
con la misma sesión para obtener `queued`, `running`, `completed` o `failed`; al completar,
`result` contiene resultados y metadata, y ante un fallo `error` contiene el mensaje. Cada
trabajo solo puede consultarlo su creador. Requiere sesión autenticada.
Prioriza Tavily cuando existe `TAVILY_API_KEY`; si no, usa OpenRouter con su herramienta
`openrouter:web_search` a través de la unidad de trabajo `spat-material-search`, y Tavily extrae los
campos con `spat-material-extractor`. Las instrucciones, el modelo y la temperatura de ambas se editan
en sus prompts de Phoenix (sin modelo en el prompt se usa `OPENROUTER_MODEL`). El uso de tokens se
descuenta de la bolsa del creador del trabajo; sin tokens, el trabajo termina en `failed` con el motivo.
Si no hay proveedor elegible, devuelve HTTP 503; nunca simula resultados.

Solicitud:

```json
{
  "geography": {"country": "Colombia", "city": "Bogotá", "radius_km": 100, "currency": "COP"},
  "category": "Varilla",
  "query": "varilla copper clad 5/8 x 2.4 m",
  "max_results": 8
}
```

`max_results` acepta entre 1 y 10 (por defecto 8). La búsqueda y la verificación de páginas
respetan ese máximo; los proveedores pueden devolver menos coincidencias útiles.

La conversación del agente se guarda automáticamente por proyecto en la base de datos y se
respalda localmente en el navegador, incluido el borrador de texto aún no enviado. Si no hay
proyecto seleccionado, el historial queda disponible localmente en ese navegador.

Al terminar, `result` tiene `{ "results": [...], "metadata": {...} }`; metadata indica proveedor,
consulta, filtros geográficos, resultados y páginas consultadas. Se consultan hasta 8
resultados y se descargan como máximo 5 páginas HTML públicas (350 KB y 8 segundos por
pagina; si falta correo o teléfono, se puede visitar un enlace de contacto del mismo
dominio para extraerlos. Se incluyen `contact_email`, `contact_phone`,
`contact_whatsapp_url` y `contact_url` cuando aparecen públicamente. Direcciones no
públicas y puertos distintos de 80/443 se omiten. La extracción LLM (si está configurada)
recibe únicamente estas páginas y sus URLs. Cada URL propuesta
debe corresponder a un resultado/cita de búsqueda y cada campo extraído se contrasta con
el texto visible descargado; los campos sin evidencia quedan vacíos. `notes` conserva el
fragmento de fuente. `price` permanece `null` salvo que importe y código ISO de moneda
aparezcan literalmente juntos en el texto. El usuario debe revisar la fuente y registrar
una cotización verificable antes de usarla como costo.

Para OpenRouter se reutilizan `OPENROUTER_API_KEY` y `OPENROUTER_MODEL`, los mismos del
agente; para Tavily configura `TAVILY_API_KEY`. `MATERIAL_CATALOG_SEARCH_URL` permite
usar un endpoint compatible con Tavily.
