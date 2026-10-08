# Datos de entrada — Subestación La Esperanza 34,5/13,8 kV

Archivos ficticios y coherentes entre sí para probar el agente desde el frontend: se suben al
proyecto con el clip del chat (o se pega el `.txt` en el mensaje).

| Archivo | Contenido | Datos clave |
|---|---|---|
| `01_plano_implantacion_…pdf` / `02_…png` | Plano civil sin malla: cerramiento, área de malla, T1, casa de control, pórticos, canaleta | Cotas 40,00 × 30,00 m para calibrar el fondo; barra de escala de 10 m |
| `03_malla_puesta_tierra_…dxf` | CAD limpio: capas `MALLA` y `VARILLAS` | 40 × 30 m, retícula 5 m en X y 6 m en Y, 16 varillas |
| `04_plano_general_multicapa_…dxf` | CAD real: misma malla + cerramiento, fundaciones, canaleta, textos y cotas, en coordenadas absolutas | Solo `MALLA_PT` y `VARILLAS_PT` son la malla |
| `05_estudio_cortocircuito_…pdf` | Estudio de cortocircuito | Ik monofásica 34,5 kV = 8,5 kA; t_s = 0,5 s; t_c = 1,0 s; X/R = 14; S_f = 0,62; 60 Hz; gravilla 3000 Ω·m y **0,15 m** |
| `06_informe_resistividad_SEV-2.docx` | Informe de laboratorio con tabla Wenner y estratigrafía | Mismas lecturas que el CSV 07 |
| `07_sondeo_wenner_SEV-2.csv` | Plantilla Wenner de Terra con solo R (Ω) | Ajuste esperado: 410 Ω·m / 2,0 m sobre 120 Ω·m |
| `08_sondeo_schlumberger_SEV-3_ampliacion.xlsx` | Zona de ampliación; encabezado en la fila 3, MN variable | 150 / 0,8 m · 600 / 4,0 m · 60 Ω·m; fila 10 atípica, fila 12 «sin lectura» |
| `09_sondeo_wenner_SEV-4_patio_alterno_rocoso.xlsx` | Patio alterno en roca | 2200 Ω·m / 3,0 m sobre 900 Ω·m (difícil de cumplir) |
| `10_lecturas_para_pegar_en_chat.txt` | Sondeo SEV-1 para pegar en el chat | 320 Ω·m / 1,5 m sobre 95 Ω·m |

Las resistividades de los sondeos se calcularon con el modelo de suelo del backend, así que el
ajuste del agente debe recuperar esos valores casi exactos.
