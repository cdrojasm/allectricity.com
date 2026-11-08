# OPT-017 — Benchmark integral del optimizador

## Ejecución

Se compararon las ocho estrategias implementadas en cuatro escenarios y seis semillas por escenario, con un máximo de 150 llamadas al solver por corrida. Se usaron 15 workers, el máximo reportado por el host y Docker.

```sh
make optimizer-benchmark OPT_BENCH_OUT=services/potential_engine/validation/benchmark-topology-optimizer-full-macos-arm64.json ARGS='--workers 15 --markdown services/potential_engine/validation/benchmark-topology-optimizer-full-macos-arm64.md'
```

El paquete versionado contiene las 192 corridas y sus métricas; el Markdown contiene el resumen por estrategia y escenario. Las cuatro pruebas de factibilidad fueron exitosas en cada estrategia (24/24, intervalo Wilson 95%: 86.2–100%). Ninguna corrida excedió las 150 llamadas; el mínimo observado fue 60.

## Resultado

| Estrategia | Costo medio (COP) | Cambio pareado frente a ALNS | Lectura |
|---|---:|---:|---|
| ALNS | 5.802 M | Referencia | Menor costo medio; rango medio 2.79 |
| ALNS oportunista | 5.802 M | 0.0%, 24 iguales | No obtuvo presupuesto sobrante para refinar; en esta matriz replica ALNS |
| ALNS con punto de control | 5.884 M | +1.4%, IC bootstrap [+0.4%, +2.7%], p=0.3438 | No mostró mejora frente a ALNS |
| ALNS refinado | 5.965 M | +2.8%, IC bootstrap [+1.2%, +4.8%], p=0.0574 | El refinamiento no compensó el presupuesto que retiró a la búsqueda |
| Búsqueda oportunista | 6.156 M | — | Mejoró modestamente frente al descenso estricto |
| Búsqueda ascendente | 6.168 M | — | Mejoró modestamente frente al descenso estricto |
| Descenso estricto | 6.252 M | — | Referencia de búsqueda local |
| Adaptativa | 6.365 M | — | No superó a la referencia en costo medio |

ALNS promedió 5.6% menos costo que descenso estricto (IC bootstrap pareado 95%: −10.4% a −0.4%; prueba exacta de signos p=0.1338). El intervalo bootstrap es compatible con una mejora pequeña; la prueba de signos no alcanza el umbral convencional de 0.05. Se mantiene ALNS puro como política oficial.

## Alcance de la conclusión

Este benchmark cierra la matriz de estrategias, escenarios y semillas definida por el ejecutor actual. No prueba que la mejora se generalice a otros sitios, rangos de corriente, tarifas o semillas; seis semillas por escenario siguen siendo una muestra pequeña. Los resultados son diagnósticos de búsqueda y no certifican la seguridad eléctrica de un diseño.

El resultado confirma además que la línea de refinamiento paramétrico no debe activarse por defecto: refinamiento fijo y política con punto de control tuvieron mayor costo medio que ALNS puro; la política oportunista no refinó en ninguna ejecución porque no encontró presupuesto libre.
