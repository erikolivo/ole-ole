# Sistema de detección de favoritos y seguimiento en vivo

Implementación del diseño discutido: selección semanal sin tope de partidos,
banco de requests repartido, y vigilancia en vivo con loop interno (no
depende de la frecuencia real del cron de GitHub Actions).

## Configuración

1. Crea estos **Secrets** en GitHub (Settings → Secrets and variables → Actions):
   - `API_FOOTBALL_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `TELEGRAM_CHAT_ID_TECNICO` (opcional, si no lo pones usa el mismo canal)

2. Instala dependencias localmente para probar:
   ```
   pip install -r requirements.txt
   ```

3. Ejecuta manualmente para probar cada fase:
   ```
   python selection.py            # Fase 1
   python requests_scheduler.py   # Fase 2
   python -c "import live_monitor; live_monitor.correr_bloque(max_horas=0.1)"  # Fase 3/4, prueba corta
   ```

## Flujo automático (GitHub Actions)

| Workflow | Cuándo corre | Qué hace |
|---|---|---|
| `seleccion_semanal.yml` | 1 vez/semana | Fase 1: escanea 7 días, filtra por umbral, sin tope de partidos |
| `confirmacion_diaria.yml` | 1 vez/día | Fase 2: confirma con `/predictions` solo lo que le toca hoy según el reparto |
| `vigilancia_bloque1.yml` | 1 vez/día, inicio de franja | Fase 3/4: loop interno con sleep adaptativo, hasta 5.5h |
| `vigilancia_bloque2.yml` | 1 vez/día, tras bloque 1 | Retoma el estado guardado, cierra el día y guarda histórico |

## Pendiente antes de producción real

- **Ajustar `LIGAS_EXCLUIDAS_PALABRAS_CLAVE`** en `config.py` a tu criterio real de qué ligas descartar.
- **Revisar `data/sin_cruce_*.json`** cada 2-3 días y completar `team_name_map.json` con los equipos que falten.
- **Ajustar `UMBRAL_PUNTAJE_SELECCION`** después de ver un par de semanas reales de datos — 55 es un punto de partida razonable, no un valor definitivo.
- Los pesos de `lpi_engine.py` y el umbral `LPI_UMBRAL_ALERTA` deben recalibrarse con los datos que se acumulen en `historico.sqlite`.
