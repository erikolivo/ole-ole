"""
Elo propio del sistema — nunca más depende de cruzar nombres con ClubElo
después del arranque inicial.

Filosofía (decidida en el diseño):
- ClubElo se usa SOLO como semilla inicial para equipos que sí tiene.
- Equipos que ClubElo no tiene: se reconstruye su Elo con sus últimos
  10 partidos reales (si tiene al menos 3), usando K-factor alto
  (período provisional). Si tiene menos de 3, se usa una semilla
  por promedio de liga.
- De ahí en adelante, el Elo se actualiza SOLO con resultados de
  api-football, con los mismos nombres/IDs de api-football — el
  problema del cruce de nombres desaparece para siempre después
  del primer día que se ve a un equipo.
"""
import json
import logging
import os
from datetime import datetime

import config
import fetch_data

log = logging.getLogger(__name__)

_RUTA_BASE_ELO = os.path.join(config.DATA_DIR, "elo_propio.json")


def _cargar_base_elo() -> dict:
    """
    Estructura: { "team_id (str)": {"elo": float, "partidos_jugados": int,
                                     "nombre": str, "liga_id": int} }
    """
    if not os.path.exists(_RUTA_BASE_ELO):
        return {}
    with open(_RUTA_BASE_ELO, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_base_elo(base: dict) -> None:
    with open(_RUTA_BASE_ELO, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)


def _probabilidad_esperada(elo_a: float, elo_b: float) -> float:
    """Fórmula clásica de Elo: probabilidad de que A le gane a B."""
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def _k_factor(partidos_jugados: int) -> float:
    if partidos_jugados < config.ELO_PARTIDOS_PERIODO_PROVISIONAL:
        return config.ELO_K_FACTOR_PROVISIONAL
    return config.ELO_K_FACTOR_NORMAL


def _semilla_por_liga(elo_clubelo: dict, liga_nombre_o_id) -> float:
    """Promedio de Elo (ClubElo) de la liga, si hay al menos un equipo de
    referencia; si no hay ninguno, semilla neutra."""
    valores = [info["elo"] for info in elo_clubelo.values()]
    if not valores:
        return config.ELO_SEMILLA_NEUTRO
    return sum(valores) / len(valores)


def _reconstruir_desde_historial(team_id: int, elo_clubelo_por_nombre: dict,
                                  base_elo: dict, elo_semilla_liga: float) -> tuple:
    """
    Trae los últimos N partidos del equipo y recalcula su Elo partido a
    partido, del más viejo al más nuevo, con K-factor alto (provisional).
    Devuelve (elo_final, partidos_procesados).
    """
    try:
        data = fetch_data._get_api_football(
            "fixtures", {"team": team_id, "last": config.ELO_PARTIDOS_HISTORIAL_A_TRAER}
        )
    except Exception as e:
        log.warning("No se pudo traer historial de team_id %s: %s", team_id, e)
        return elo_semilla_liga, 0

    partidos = data.get("response", [])
    if len(partidos) < config.ELO_MIN_PARTIDOS_PARA_RECONSTRUIR:
        return elo_semilla_liga, len(partidos)

    # Orden cronológico: del más antiguo al más reciente
    partidos.sort(key=lambda p: p["fixture"]["timestamp"])

    elo_actual = elo_semilla_liga
    for partido in partidos:
        es_local = partido["teams"]["home"]["id"] == team_id
        rival_id = partido["teams"]["away"]["id"] if es_local else partido["teams"]["home"]["id"]
        goles_propios = partido["goals"]["home"] if es_local else partido["goals"]["away"]
        goles_rival = partido["goals"]["away"] if es_local else partido["goals"]["home"]

        if goles_propios is None or goles_rival is None:
            continue  # partido sin resultado (suspendido, futuro, etc.)

        # Elo del rival: si ya está en nuestra base propia, úsalo; si no, semilla de liga
        elo_rival = base_elo.get(str(rival_id), {}).get("elo", elo_semilla_liga)

        elo_local_ajustado = elo_actual + (config.ELO_VENTAJA_LOCAL if es_local else 0)
        prob_esperada = _probabilidad_esperada(elo_local_ajustado, elo_rival)

        if goles_propios > goles_rival:
            resultado_real = 1.0
        elif goles_propios == goles_rival:
            resultado_real = 0.5
        else:
            resultado_real = 0.0

        elo_actual += config.ELO_K_FACTOR_PROVISIONAL * (resultado_real - prob_esperada)

    return elo_actual, len(partidos)


def obtener_o_crear_elo(team_id: int, nombre_equipo: str, liga_id: int,
                         elo_clubelo_por_nombre: dict, nombre_en_clubelo: str = None) -> float:
    """
    Punto de entrada principal. Devuelve el Elo actual del equipo:
    1. Si ya está en la base propia -> lo devuelve directo (0 requests).
    2. Si ClubElo lo tiene -> lo siembra desde ahí (0 requests).
    3. Si no está en ninguno -> reconstruye desde historial (1 request,
       solo la primera vez) o usa semilla de liga si tiene <3 partidos.
    """
    base_elo = _cargar_base_elo()
    clave = str(team_id)

    if clave in base_elo:
        return base_elo[clave]["elo"]

    # Paso 2: ¿ClubElo lo tiene?
    if nombre_en_clubelo and nombre_en_clubelo in elo_clubelo_por_nombre:
        elo_inicial = elo_clubelo_por_nombre[nombre_en_clubelo]["elo"]
        base_elo[clave] = {
            "elo": elo_inicial, "partidos_jugados": 0,
            "nombre": nombre_equipo, "liga_id": liga_id,
            "origen": "clubelo",
        }
        _guardar_base_elo(base_elo)
        log.info("Elo sembrado desde ClubElo para %s: %.1f", nombre_equipo, elo_inicial)
        return elo_inicial

    # Paso 3: reconstrucción o semilla de liga
    semilla_liga = _semilla_por_liga(elo_clubelo_por_nombre, liga_id)
    elo_final, n_partidos = _reconstruir_desde_historial(
        team_id, elo_clubelo_por_nombre, base_elo, semilla_liga
    )

    origen = "reconstruido" if n_partidos >= config.ELO_MIN_PARTIDOS_PARA_RECONSTRUIR else "semilla_liga"
    base_elo[clave] = {
        "elo": elo_final, "partidos_jugados": n_partidos,
        "nombre": nombre_equipo, "liga_id": liga_id,
        "origen": origen,
    }
    _guardar_base_elo(base_elo)
    log.info("Elo %s para %s: %.1f (%d partidos)", origen, nombre_equipo, elo_final, n_partidos)
    return elo_final


def actualizar_tras_resultado(team_id_local: int, team_id_visitante: int,
                               goles_local: int, goles_visitante: int) -> None:
    """
    Se llama una vez que un partido termina (FT), para que el Elo propio
    se mantenga vivo y actualizado sin depender nunca más de ClubElo.
    """
    base_elo = _cargar_base_elo()
    clave_local, clave_visitante = str(team_id_local), str(team_id_visitante)

    if clave_local not in base_elo or clave_visitante not in base_elo:
        log.warning("Actualización de Elo omitida: equipo sin Elo previo (%s o %s)",
                    clave_local, clave_visitante)
        return

    info_local = base_elo[clave_local]
    info_visitante = base_elo[clave_visitante]

    elo_local_ajustado = info_local["elo"] + config.ELO_VENTAJA_LOCAL
    prob_local = _probabilidad_esperada(elo_local_ajustado, info_visitante["elo"])

    if goles_local > goles_visitante:
        resultado_local, resultado_visitante = 1.0, 0.0
    elif goles_local == goles_visitante:
        resultado_local, resultado_visitante = 0.5, 0.5
    else:
        resultado_local, resultado_visitante = 0.0, 1.0

    k_local = _k_factor(info_local["partidos_jugados"])
    k_visitante = _k_factor(info_visitante["partidos_jugados"])

    info_local["elo"] += k_local * (resultado_local - prob_local)
    info_visitante["elo"] += k_visitante * (resultado_visitante - (1 - prob_local))
    info_local["partidos_jugados"] += 1
    info_visitante["partidos_jugados"] += 1

    _guardar_base_elo(base_elo)
