# Instrucciones para agentes (Claude Code)

## Pruebas manuales y de navegador: crea el usuario tú mismo

Cuando se te pida probar, verificar o hacer una prueba de la app (en particular con la extensión Claude in Chrome o cualquier navegador) y no se te hayan dado credenciales:

- **Crea un usuario de prueba.** No uses "no tengo usuario" ni "no puedo iniciar sesión" como excusa para detenerte o devolver la tarea como bloqueada.
- Usa los targets de Make: `make smoke-ui-seed` crea los usuarios `designer`, `viewer` y `user_admin` y escribe sus credenciales en `app/.env.smoke-ui` (ignorado por git). Úsalas solo contra `127.0.0.1`/`localhost`.
- Son credenciales falsas de entorno local. No hace falta ocultarlas del usuario, pero no las pegues en commits, issues ni servicios externos.
- La API limita a 10 logins por cuenta cada 5 min: inicia sesión una vez por perfil y reutiliza la sesión.
- Crea proyectos solo con prefijo `zz-smoke-<fecha>-<id>` y bórralos al terminar (`make smoke-ui-sweep` si quedan).
- **Avisa siempre** en el reporte final: "Me tocó crear un usuario de prueba" (cuál perfil y con qué target).
- Solo si crear el usuario falla de verdad (el stack no levanta, el seed da error), reporta el error exacto y lo que intentaste.

## Commits, CI y despliegue: qué corre y qué se despliega

Un push a `main` dispara **una** corrida de `ci` y, si pasa, **una** de `deploy` (en GitHub `cdrojasm/allectricity.com`). Ninguno mira commit por commit: los dos usan **todo el rango pendiente**, desde el tag `deployed/production` (último deploy exitoso) hasta `HEAD`. En un PR, el rango es el PR entero contra su base. La lógica está en `deploy/railway/changed_services.py`.

- **CI:** si todos los archivos del rango están en `NO_BACKEND_TESTS` (`app/`, `docs/`, `README`, `CLAUDE.md`/`AGENTS.md`, Dockerfile/nginx del frontend y de MinIO, `deploy.yml`, scripts de deploy de Railway), se omiten lint y la suite backend (~15 min). Cualquier otro archivo (`backend/`, `tests/`, `services/`, `Makefile`, `dependencies/`, `ci.yml`, una carpeta nueva) corre la suite completa. Si agregas una carpeta o un archivo que no puede romper el backend, añádelo a `NO_BACKEND_TESTS` y a su `--self-test`.
- **Deploy:** solo los servicios que `RULES` asocia a los archivos cambiados. Un archivo sin regla no despliega nada y deja un warning; si debe desplegar algo, agrégale una regla.
- Un deploy fallido o un CI cancelado no mueven el tag, así que esos cambios se vuelven a probar y desplegar en el siguiente push.

**Etiquetas en el mensaje del commit.** Se leen en todos los commits del rango, no solo en el último, y se suman entre sí. **Solo agregan trabajo, nunca quitan:** si la etiqueta pide menos de lo que exige el diff, gana el diff.

| Etiqueta | Efecto | Cuándo usarla |
|---|---|---|
| `[ci: full]` | Corre la suite backend aunque el diff no la pida | Un cambio de frontend o de config que sospechas que afecta al backend; antes de un release |
| `[deploy: api frontend]` | Despliega también esos servicios | Cambió una variable o un recurso en Railway que el diff no ve; reconstruir un servicio |
| `[deploy: all]` | Despliega todos los servicios | Rotación de secretos, cambio de imagen base |
| `[skip ci]` (nativa de GitHub) | No corre CI **ni deploy**; los cambios salen con el siguiente push | Solo docs o notas que no hace falta desplegar ya |

Servicios válidos: `api scheduler agent-worker document-worker calculation-worker optimizer-worker mail-worker render-worker potential-engine ocr minio frontend`. Un nombre mal escrito se ignora con un warning.

Ejemplo: `SPAT fix(landing): corrige el footer [deploy: frontend]`. Pon la etiqueta al final del asunto o en el cuerpo. **No la agregues por costumbre:** si el diff ya decide bien, sobra. Para saber qué hará el siguiente push, antes de empujar:

```
git fetch allectricity --tags
python3 deploy/railway/changed_services.py --ci deployed/production HEAD      # ¿corre la suite backend?
python3 deploy/railway/changed_services.py --range deployed/production HEAD   # servicios a desplegar
```

No hay target de Make para esto; es el mismo script que corren los workflows.
