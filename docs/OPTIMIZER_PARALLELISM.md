# Paralelismo dentro de una corrida del optimizador

El parámetro `parallel_workers` de `run_topology_optimizer` habilita concurrencia de las validaciones L3 de finalistas. Su valor predeterminado es `1` (ejecución secuencial).

Las propuestas y evaluaciones L1/L2+ de ALNS permanecen secuenciales porque el resultado de cada candidata actualiza el selector adaptativo y afecta qué operador propone después. Al final de la búsqueda, las validaciones L3 son independientes: se pueden ejecutar en paralelo y sus veredictos se incorporan en el orden determinista de los candidatos.

En modo de presupuesto por llamadas, las plazas disponibles se reservan antes de lanzar los workers. La concurrencia nunca puede superar el presupuesto restante, y las llamadas L3 siguen usando la reserva que el controlador aparta para los finalistas. Cada lote guarda todos sus veredictos en el checkpoint antes de avanzar. Al reanudar, las evaluaciones guardadas se reproducen sin llamar otra vez al solver.

El paralelismo de finalistas puede evaluar hasta `parallel_workers - 1` candidatos adicionales que luego no entren en la lista por diversidad o porque ya se llenaron los puestos. Estas llamadas quedan contabilizadas y dentro del límite global. Si se configura presupuesto por tiempo, se usa el recorrido secuencial: el cálculo de reserva temporal existente asume una llamada activa a la vez.

Ejemplo:

```python
run_topology_optimizer(..., max_solver_calls=150, parallel_workers=4)
```

`parallel_workers=1` conserva el comportamiento secuencial anterior. `parallel_workers` forma parte de la huella de la corrida y no puede cambiarse al reanudar un checkpoint existente.
