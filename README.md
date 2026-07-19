# Sistema de deteccion de favoritos y seguimiento en vivo (v2)

Implementacion completa del diseno final: Elo propio (semilla ClubElo +
reconstruccion de historial), seleccion semanal sin tope de partidos,
banco de requests repartido, vigilancia en vivo con loop interno y LPI
sin minuto fijo (momentum + 4 ventanas), y validacion cruzada opcional
con el mercado (the-odds-api).

## Que cambio respecto a la v1

- Elo propio (elo_engine.py): ya no se depende de cruzar nombres con
  ClubElo cada dia. ClubElo se usa solo como semilla inicial; los equipos
  que no estan ahi se reconstruyen con sus ultimos 10 partidos (minimo 3)
  via api-football, y de ahi en adelante el Elo se actualiza solo.
- LPI sin minuto fijo (lpi_engine.py, live_monitor.py): la ventana
  temprana se dispara por presion sostenida en sondeos consecutivos, no
  por un minuto arbitrario. Hay 4 ventanas con distinto umbral (temprana,
  normal, gol inminente, ultima oportunidad). Se quito xG (no confiable
  en el plan gratis) y se agrego momentum (comparacion entre sondeos).
- Sin restriccion de marcador: se vigilan todos los favoritos activos,
  ganando, empatando o perdiendo -- el mensaje de Telegram distingue la
  situacion.
- Fase 2.5 -- validacion de mercado (odds_validation.py): usa
  the-odds-api (gratis, ~15 consultas/dia) para marcar (coincide con
  el mercado) o (discrepa) en el mensaje de alerta, sin tocar el
  puntaje ni el IS.

## Configuracion

Secrets necesarios en GitHub (Settings -> Secrets and variables -> Actions):
- API_FOOTBALL_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- TELEGRAM_CHAT_ID_TECNICO (opcional)
- ODDS_API_KEY (opcional -- si no se configura, la Fase 2.5 simplemente no marca nada)

Y en Settings -> Actions -> General -> Workflow permissions: Read and write permissions
(necesario para que los workflows puedan hacer commit de los datos generados).

## Ejecutar manualmente para probar

pip install -r requirements.txt

python selection.py            # Fase 1: seleccion semanal + Elo propio
python requests_scheduler.py   # Fase 2 + 2.5: confirmacion y validacion de mercado
python -c "import live_monitor; live_monitor.correr_bloque(max_horas=0.1)"  # Fase 3/4, prueba corta

## Flujo automatico (GitHub Actions)

| Workflow | Cuando corre | Que hace |
|---|---|---|
| seleccion_semanal.yml | 1 vez/semana | Fase 1: Elo propio + escaneo 7 dias, sin tope de partidos |
| confirmacion_diaria.yml | 1 vez/dia | Fase 2 + 2.5: confirma con /predictions, valida con el mercado |
| vigilancia_bloque1.yml | 1 vez/dia, inicio de franja | Fase 3/4: loop interno, LPI con momentum y 4 ventanas |
| vigilancia_bloque2.yml | 1 vez/dia, tras bloque 1 | Retoma estado, cierra el dia, guarda historico |

## Archivos de datos generados

- data/elo_propio.json -- base de Elo propio, persistente, crece con el tiempo
- data/candidatos_semana.json -- todos los partidos que pasaron el umbral esta semana
- data/plan_requests_semana.json -- reparto de confirmaciones por dia
- data/vigilancia_YYYY-MM-DD.json -- partidos confirmados a vigilar ese dia
- data/estado_vivo_YYYY-MM-DD.json -- estado del loop en vivo (persiste entre bloques)
- data/historico.sqlite -- historico para calibrar pesos con el tiempo

## Pendiente antes de produccion real

- Ajustar LIGAS_EXCLUIDAS_PALABRAS_CLAVE en config.py a tu criterio real.
- Los umbrales de las 4 ventanas del LPI (LPI_UMBRAL_* en config.py) son
  un punto de partida razonable, no definitivo -- se calibran con historico.sqlite.
- MOMENTUM_UMBRAL_PRESION y MOMENTUM_SONDEOS_CONSECUTIVOS_REQUERIDOS (ventana
  temprana) tambien deberian ajustarse una vez que tengas datos reales.
- El modelo hibrido (Elo + localia + forma con regresion logistica, inspirado en
  AdamJelley/football-predictions) quedo como mejora futura, no esta implementado
  todavia -- la seleccion actual sigue usando la formula de puntos fija.
