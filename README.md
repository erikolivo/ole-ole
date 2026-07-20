# Sistema de deteccion de favoritos y seguimiento en vivo (v3)

Version diaria (no semanal): se descubrio que el plan gratis de
API-Football NO permite consultar el calendario de dias futuros (solo
una ventana muy limitada, aparentemente hacia atras) -- por eso la
seleccion, confirmacion y validacion de mercado se fusionaron en un solo
script diario (seleccion_diaria.py), que corre una vez al dia antes de
que arranquen los partidos de HOY.

## Que cambio respecto a la v2

- selection.py y requests_scheduler.py se eliminaron y se fusionaron en
  seleccion_diaria.py -- ya no existe el reparto semanal de requests
  (no se puede planificar con anticipacion lo que la API no deja ver).
- Los workflows seleccion_semanal.yml y confirmacion_diaria.yml se
  reemplazaron por uno solo: seleccion_diaria.yml.
- Todo lo demas (Elo propio, LPI sin minuto fijo, momentum, 4 ventanas,
  Fase 2.5 con the-odds-api) sigue igual que en la v2, porque vive en la
  vigilancia en vivo, que no depende de ver el futuro.

## Configuracion

Secrets necesarios en GitHub (Settings -> Secrets and variables -> Actions):
- API_FOOTBALL_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- TELEGRAM_CHAT_ID_TECNICO (opcional)
- ODDS_API_KEY (opcional -- registro gratis en the-odds-api.com)

Y en Settings -> Actions -> General -> Workflow permissions: Read and write permissions.

## Ejecutar manualmente para probar

pip install -r requirements.txt

python seleccion_diaria.py     # Fase 1+2+2.5: seleccion, confirmacion y validacion de mercado, todo en uno
python -c "import live_monitor; live_monitor.correr_bloque(max_horas=0.1)"  # Fase 3/4, prueba corta

## Flujo automatico (GitHub Actions)

| Workflow | Cuando corre | Que hace |
|---|---|---|
| seleccion_diaria.yml | 1 vez/dia, antes de los partidos | Fase 1+2+2.5: Elo propio, filtro por umbral, confirmacion, validacion de mercado |
| vigilancia_bloque1.yml | 1 vez/dia, inicio de franja | Fase 3/4: loop interno, LPI con momentum y 4 ventanas |
| vigilancia_bloque2.yml | 1 vez/dia, tras bloque 1 | Retoma estado, cierra el dia, guarda historico |

## Archivos de datos generados

- data/elo_propio.json -- base de Elo propio, persistente, crece con el tiempo
- data/vigilancia_YYYY-MM-DD.json -- partidos confirmados a vigilar ese dia (ya con IS y validacion de mercado)
- data/estado_vivo_YYYY-MM-DD.json -- estado del loop en vivo (persiste entre bloques)
- data/historico.sqlite -- historico para calibrar pesos con el tiempo

## Pendiente / cosas a verificar

- Confirmar exactamente que ventana de fechas permite tu plan (se vio que
  hoy=19 solo dejaba ver 16-18 -- probar si "hoy" mismo y "manana" son
  accesibles, para saber si conviene ademas escanear 1 dia extra).
- Ajustar LIGAS_EXCLUIDAS_PALABRAS_CLAVE y los umbrales del LPI con datos reales.
- El modelo hibrido (Elo + localia + forma con regresion logistica) sigue
  pendiente como mejora futura, no implementada todavia.
