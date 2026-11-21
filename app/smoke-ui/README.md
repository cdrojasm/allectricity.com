# smoke-ui: prueba de humo por la interfaz gráfica

Se comporta como una persona: entra con un usuario por perfil y usa la interfaz. No usa `docker`, `oc`
ni acceso al backend, así que sirve igual en local, desarrollo (OKD) y producción.

## Variables de entorno

| Variable | Significado |
|---|---|
| `SMOKE_BASE_URL` | URL de la aplicación, p. ej. `https://allectricity.ejemplo.com` |
| `SMOKE_<ROL>_EMAIL` / `SMOKE_<ROL>_PASSWORD` | Un par por perfil. `<ROL>` ∈ `DESIGNER`, `VIEWER`, `USER_ADMIN`, `SUPER_ADMIN`. Se prueban los que estén definidos |
| `SMOKE_CONFIRM_REMOTE=yes` | Obligatoria si la URL no es local; es la confirmación explícita |
| `SMOKE_LIFECYCLE_ROLES` | Perfiles que ejecutan el ciclo crear/editar/borrar (por defecto `designer`) |
| `SMOKE_ISOLATION_OTHER` | Perfil que no debe ver los proyectos del `designer` (por defecto `viewer`) |

Local: `make smoke-ui-seed` crea usuarios de prueba en el stack Docker y los deja en `app/.env.smoke-ui`
(ignorado por git). En otros entornos, exporta las variables en tu shell; no las escribas en archivos versionados.

## Comandos

```bash
make smoke-ui          # corre la suite
make smoke-ui-sweep    # borra por la UI cualquier proyecto zz-smoke-* que haya quedado
make smoke-ui ARGS='01-solo-lectura'     # solo los checks de lectura (no crea nada)
```

## Qué prueba

1. **Solo lectura** (`01`): rutas privadas redirigen al login, credenciales inválidas no entran, y por perfil:
   dashboard, estado del sistema "Todo operativo", proyectos y catálogo. Además un login y cierre de sesión reales.
2. **Ciclo de proyecto** (`02`): crea `zz-smoke-<fecha>-<id>`, lo edita, comprueba que persiste tras recargar,
   abre su espacio, verifica que "Cancelar" no borra, lo borra y exige que el listado final sea idéntico al inicial.
3. **Aislamiento** (`03`): un proyecto del `designer` no aparece al `viewer`.
4. **Estudio público** (`04`): el estudio publicado concluye lo mismo que el panel Resultados.
5. **Optimizador de topologías** (`05`, solo local): siembra un perfil normativo de prueba `zz-smoke-*` (necesita `super_admin`; `make smoke-ui-seed` lo crea) y recorre precarga desde el artefacto, tarifas, corrida real, vista previa, aplicar versión e historial tras recargar. Retira el perfil al terminar.

## Seguridad en producción

- Solo crea objetos con prefijo `zz-smoke-` y solo borra los suyos; si falla a mitad, borra en `finally`.
- Si hay residuos de una corrida anterior, el ciclo se niega a empezar: corre `make smoke-ui-sweep`.
- Un worker, sin reintentos (un reintento podría duplicar objetos).
- **La API limita los logins a 10 por cuenta cada 5 minutos.** La suite hace un login por perfil al inicio
  (la sesión se reutiliza) y uno más para la prueba de cierre de sesión. No la lances en bucle.
- Deja rastro que no se puede ni se debe borrar: auditoría, IDs consumidos y cualquier
  notificación o métrica que el sistema genere (no lo he verificado). Avisa al equipo de operaciones antes de la primera corrida.
- Artefactos de fallo (captura, vídeo, traza) en `app/test-results/smoke-ui/`. Pueden contener datos de la pantalla.
