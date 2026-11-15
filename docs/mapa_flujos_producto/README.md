# Mapa de flujos de producto

Recorrido de la app como lo haría un usuario nuevo: pantallazos de cada paso, flechas de qué control lleva a qué pantalla, estado de cada tramo (fluye / con fricción / se rompe) y hallazgos priorizados.

## Verlo

Abre `index.html` en el navegador (doble clic, no necesita servidor). Las imágenes están en `img/`.

## Actualizarlo

Todo el contenido está en tres listas al final de `index.html`:

- `STEPS`: los pasos del recorrido (intención, lo que pasa, pantallazos, hallazgos).
- `MAIN` y `BR`: las pantallas del tablero conectado. Cada una lleva la coordenada del control pulsado, medida sobre un pantallazo de 1456 × 830.
- `PRIO`: la tabla de hallazgos priorizados; el último elemento de cada fila es su estado `[severidad, etiqueta, nota]`.
- `STRAT`: la estrategia propuesta para cada hallazgo (propuesta, sin implementar).

Para rehacer el recorrido tras un cambio grande: `make local-up`, `make smoke-ui-seed`, recorrer la app con el perfil `designer` en `127.0.0.1:3001` usando un proyecto `zz-smoke-<fecha>-<id>`, reemplazar los pantallazos en `img/` y ajustar las listas. Borra el proyecto al terminar (`make smoke-ui-sweep`). Cambia también la fecha del encabezado.

Última corrida: 2026-11-14, rama `p1-motor-potencial`. Estado de resolución actualizado el 2026-11-15 contra el código (sin recorrido nuevo): columna «Estado» de `PRIO` y sección «Estado de resolución».
