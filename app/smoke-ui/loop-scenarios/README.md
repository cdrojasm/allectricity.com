# Escenarios forzados del agente (solo local)

Algunos casos del [plan de pruebas P0](../../../docs/PLAN_PRUEBAS_P0_FLUJOS.md) dependen de lo que proponga el
modelo: una propuesta sin cambio válido (P1-03), una iteración que empeora (P1-04) o una respuesta final que
contradice lo guardado (P4-02/P4-03). Para repetirlos sin azar, `llm_stub.py` es un LLM compatible con OpenAI que
responde con llamadas fijas; el solver, la API, el worker y la interfaz siguen siendo los reales.
`docker-compose.loop.yml` lo levanta y cambia **solo** el entorno del worker de agente.

Nunca usar contra un entorno remoto. Al terminar, volver al worker normal (paso 3).

## 1. Elegir el escenario y levantar el worker

```bash
# Límite de una iteración con el proveedor real (P1-02): sin LLM de prueba
SMOKE_DESIGN_MAX_ITERATIONS=1 docker compose --env-file .env -f deploy/local/docker/docker-compose.yml \
  -f app/smoke-ui/loop-scenarios/docker-compose.loop.yml up -d --no-deps --force-recreate agent-worker

# LLM de prueba: invalid (P1-03), worse (P1-04) o p4 (P4-02/P4-03 forzados)
export SMOKE_LOOP_SCENARIO=worse SMOKE_LLM_BASE_URL=http://grounding-design-ai-llm-stub:8099/v1
docker compose --env-file .env -f deploy/local/docker/docker-compose.yml \
  -f app/smoke-ui/loop-scenarios/docker-compose.loop.yml --profile loop-stub \
  up -d --no-deps --force-recreate llm-stub agent-worker
```

Para cambiar entre `invalid`, `worse` y `p4` basta con recrear `llm-stub` con el nuevo `SMOKE_LOOP_SCENARIO`.
`docker logs grounding-design-ai-llm-stub` muestra cada llamada que respondió.

## 2. Ejecutar la prueba del escenario

| Escenario | Variables | Comando |
|---|---|---|
| P1-02 límite 1 | `SMOKE_LOOP_SCENARIO=limit1` | `make smoke-ui ARGS='specs/08-p1-casos-forzados.spec.js'` |
| P1-03 sin cambio válido | `SMOKE_LOOP_SCENARIO=invalid` | `make smoke-ui ARGS='specs/08-p1-casos-forzados.spec.js'` |
| P1-04 iteración peor | `SMOKE_LOOP_SCENARIO=worse` | `make smoke-ui ARGS='specs/08-p1-casos-forzados.spec.js'` |
| P4-02/P4-03 forzados | `SMOKE_LOOP_SCENARIO=p4` | `make smoke-ui ARGS='specs/11-p4-respuesta-forzada.spec.js'` |

Cada prueba se omite si el escenario no coincide. Con el worker normal también corren
`specs/09-p2-catalogo-vacio.spec.js` (se omite si hay perfiles revisados) y
`specs/10-p4-respuesta-inducida.spec.js` (proveedor real; no garantiza que el modelo emita la frase falsa).

## 3. Volver al worker normal

```bash
docker compose --env-file .env -f deploy/local/docker/docker-compose.yml \
  -f app/smoke-ui/loop-scenarios/docker-compose.loop.yml --profile loop-stub rm -sf llm-stub
docker compose --env-file .env -f deploy/local/docker/docker-compose.yml up -d --no-deps --force-recreate agent-worker
```

`make local-up` también lo deja como estaba. Si quedan proyectos `zz-smoke-*`: `make smoke-ui-sweep`.
