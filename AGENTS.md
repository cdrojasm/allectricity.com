# Instrucciones para agentes (Codex)

## Pruebas manuales y de navegador: crea el usuario tú mismo

Cuando se te pida probar, verificar o hacer una prueba de la app (en particular con la extensión Claude in Chrome o cualquier navegador) y no se te hayan dado credenciales:

- **Crea un usuario de prueba.** No uses "no tengo usuario" ni "no puedo iniciar sesión" como excusa para detenerte o devolver la tarea como bloqueada.
- Usa los targets de Make: `make smoke-ui-seed` crea los usuarios `designer`, `viewer` y `user_admin` y escribe sus credenciales en `app/.env.smoke-ui` (ignorado por git). Úsalas solo contra `127.0.0.1`/`localhost`.
- Son credenciales falsas de entorno local. No hace falta ocultarlas del usuario, pero no las pegues en commits, issues ni servicios externos.
- La API limita a 10 logins por cuenta cada 5 min: inicia sesión una vez por perfil y reutiliza la sesión.
- Crea proyectos solo con prefijo `zz-smoke-<fecha>-<id>` y bórralos al terminar (`make smoke-ui-sweep` si quedan).
- **Avisa siempre** en el reporte final: "Me tocó crear un usuario de prueba" (cuál perfil y con qué target).
- Solo si crear el usuario falla de verdad (el stack no levanta, el seed da error), reporta el error exacto y lo que intentaste.
