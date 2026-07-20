"""
FASE 1+2+2.5 FUSIONADAS — Seleccion diaria (reemplaza selection.py + el
reparto semanal de requests_scheduler.py).

Motivo del cambio: el plan gratis de API-Football NO permite consultar
el calendario de dias futuros (solo una ventana muy limitada, aparentemente
hacia atras) -- por eso ya no se puede escanear 7 dias de una sola vez.
Todo pasa ahora en un solo job, una vez al dia, antes de que arranquen
los partidos de HOY.

Flujo:
  1. Elo del dia (ClubElo, gratis) + Elo propio (elo_engine.py)
  2. Calendario de HOY (1 request)
  3. Filtro duro de liga + umbral de puntaje (sin tope de partidos)
  4. Confirmacion con /predictions para TODOS los que pasaron el umbral
     (ya no hay reparto entre dias, porque ya no se puede ver el futuro)
  5. Fase 2.5: validacion cruzada con the-odds-api (hasta 15/dia)
  6. Guarda vigilancia_HOY.json, listo para que live_monitor.py lo tome
"""
import json
import logging
from datetime import datetime

import config
import fetch_data
import elo_engine
import odds_validation
import telegram_utils

log = logging.getLogger(__name__)


def _es_liga_excluida(nombre_liga: str) -> bool:
    nombre_liga_low = nombre_liga.lower()
    return any(palabra in nombre_liga_low for palabra in config.LIGAS_EXCLUIDAS_PALABRAS_CLAVE)


def _nombre_clubelo_aproximado(nombre_api_football: str, elo_clubelo: dict) -> str:
    if nombre_api_football in elo_clubelo:
        return nombre_api_football
    nombre_low = nombre_api_football.lower()
    for nombre_elo in elo_clubelo:
        if nombre_low == nombre_elo.lower():
            return nombre_elo
    return None


def _puntaje_elo(diferencia: float) -> float:
    puntos_referencia = [(0, 0), (50, 20), (100, 30), (150, 35), (200, 40)]
    diferencia = max(0, diferencia)
    if diferencia >= 200:
        return config.PESO_ELO
    for (x0, y0), (x1, y1) in zip(puntos_referencia, puntos_referencia[1:]):
        if x0 <= diferencia <= x1:
            return y0 + (y1 - y0) * (diferencia - x0) / (x1 - x0)
    return 0


def _probabilidad_clubelo(fixtures_clubelo: list, local: str, visitante: str) -> float:
    for fila in fixtures_clubelo:
        if fila.get("Home") == local and fila.get("Away") == visitante:
            try:
                return float(fila.get("HomeWinProbability", 0))
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def _calcular_is(predictions_data: dict, candidato: dict) -> dict:
    respuesta = predictions_data.get("response", [{}])[0]
    comparacion = respuesta.get("comparison", {})

    def _valor(campo, equipo):
        try:
            return float(comparacion.get(campo, {}).get(equipo, "0%").replace("%", ""))
        except (ValueError, AttributeError):
            return 50.0

    lado_favorito = "home" if candidato["favorito_es_local"] else "away"
    lado_rival = "away" if candidato["favorito_es_local"] else "home"

    puntaje_favorito = sum(_valor(c, lado_favorito) for c in ["form", "att", "def"]) / 3
    puntaje_rival = sum(_valor(c, lado_rival) for c in ["form", "att", "def"]) / 3
    IS = round(puntaje_favorito - puntaje_rival, 1)

    if IS > config.IS_FAVORITO_MUY_CLARO:
        clasificacion = "muy_claro"
    elif IS > config.IS_FAVORITO_FUERTE:
        clasificacion = "fuerte"
    elif IS > config.IS_FAVORITO_MODERADO:
        clasificacion = "moderado"
    else:
        clasificacion = "descartado"

    return {**candidato, "indice_superioridad": IS, "clasificacion_is": clasificacion}


def ejecutar_seleccion_del_dia(fecha: str = None) -> list:
    fecha = fecha or datetime.utcnow().strftime("%Y-%m-%d")

    elo_clubelo = fetch_data.descargar_elo_del_dia(fecha)   # solo como semilla, 0 requests
    fixtures_clubelo = fetch_data.descargar_probabilidades_fixtures()
    calendario = fetch_data.obtener_calendario(fecha)        # 1 request
    partidos = calendario.get("response", [])

    candidatos = []
    equipos_reconstruidos = []

    for partido in partidos:
        liga = partido["league"]["name"]
        if _es_liga_excluida(liga):
            continue

        local_id = partido["teams"]["home"]["id"]
        visitante_id = partido["teams"]["away"]["id"]
        local_nombre = partido["teams"]["home"]["name"]
        visitante_nombre = partido["teams"]["away"]["name"]
        liga_id = partido["league"]["id"]

        nombre_ce_local = _nombre_clubelo_aproximado(local_nombre, elo_clubelo)
        nombre_ce_visitante = _nombre_clubelo_aproximado(visitante_nombre, elo_clubelo)

        elo_local = elo_engine.obtener_o_crear_elo(local_id, local_nombre, liga_id, elo_clubelo, nombre_ce_local)
        elo_visitante = elo_engine.obtener_o_crear_elo(visitante_id, visitante_nombre, liga_id, elo_clubelo, nombre_ce_visitante)

        if nombre_ce_local is None:
            equipos_reconstruidos.append(local_nombre)
        if nombre_ce_visitante is None:
            equipos_reconstruidos.append(visitante_nombre)

        diff_elo = elo_local - elo_visitante
        favorito, rival, favorito_es_local, diff_abs = (
            (local_nombre, visitante_nombre, True, diff_elo) if diff_elo >= 0
            else (visitante_nombre, local_nombre, False, -diff_elo)
        )

        if diff_abs < config.DIFERENCIA_ELO_MINIMA:
            continue

        prob_clubelo = 0.0
        if nombre_ce_local and nombre_ce_visitante:
            prob_clubelo = _probabilidad_clubelo(fixtures_clubelo, nombre_ce_local, nombre_ce_visitante)
        prob_favorito = prob_clubelo if favorito_es_local else (1 - prob_clubelo) if prob_clubelo else 0.5

        puntos_liga = config.PESO_LIGA if (nombre_ce_local or nombre_ce_visitante) else 8

        puntaje = (
            _puntaje_elo(diff_abs)
            + (config.PESO_LOCALIA if favorito_es_local else 5)
            + prob_favorito * config.PESO_PROB_CLUBELO
            + puntos_liga
        )

        if puntaje < config.UMBRAL_PUNTAJE_SELECCION:
            continue

        candidato = {
            "fixture_id": partido["fixture"]["id"],
            "fecha": fecha,
            "liga": liga,
            "favorito": favorito,
            "favorito_id": local_id if favorito_es_local else visitante_id,
            "rival": rival,
            "rival_id": visitante_id if favorito_es_local else local_id,
            "favorito_es_local": favorito_es_local,
            "elo_favorito": elo_local if favorito_es_local else elo_visitante,
            "elo_rival": elo_visitante if favorito_es_local else elo_local,
            "diferencia_elo": diff_abs,
            "puntaje_seleccion": round(puntaje, 1),
        }

        # Confirmacion inmediata con /predictions (ya no se reparte entre dias)
        try:
            predictions_data = fetch_data.obtener_predictions(candidato["fixture_id"])
            candidato = _calcular_is(predictions_data, candidato)
        except Exception as e:
            log.error("Fallo confirmando fixture %s: %s", candidato["fixture_id"], e)
            continue

        if candidato["clasificacion_is"] != "descartado":
            candidatos.append(candidato)

    _avisar_reconstrucciones(equipos_reconstruidos)
    candidatos.sort(key=lambda c: c["puntaje_seleccion"], reverse=True)

    candidatos = odds_validation.validar_top_partidos_del_dia(candidatos)   # Fase 2.5

    with open(f"{config.DATA_DIR}/vigilancia_{fecha}.json", "w", encoding="utf-8") as f:
        json.dump(candidatos, f, ensure_ascii=False, indent=2)

    log.info("Seleccion del %s: %d partidos confirmados a vigilar (sin tope de cantidad, requests hoy: %d)",
              fecha, len(candidatos), fetch_data.requests_gastados_hoy())
    return candidatos


def _avisar_reconstrucciones(equipos: list) -> None:
    if not equipos:
        return
    equipos_unicos = sorted(set(equipos))
    mensaje = f"Info: hoy se calculo Elo propio para {len(equipos_unicos)} equipos nuevos (no estaban en ClubElo)\n"
    mensaje += "\n".join(f"- {eq}" for eq in equipos_unicos[:30])
    if len(equipos_unicos) > 30:
        mensaje += f"\n... y {len(equipos_unicos) - 30} mas"
    telegram_utils.enviar_aviso_tecnico(mensaje)


if __name__ == "__main__":
    ejecutar_seleccion_del_dia()
