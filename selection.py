"""
FASE 1 — Selección semanal de favoritos.
Escanea 7 días de calendario de una sola vez, cruza con Elo (gratis),
y filtra por UMBRAL de puntaje (no por top-N): si califican 40 partidos, entran los 40.
"""
import json
import logging
from datetime import datetime, timedelta

import config
import fetch_data
import telegram_utils

log = logging.getLogger(__name__)

with open("team_name_map.json", "r", encoding="utf-8") as f:
    _RAW_MAP = json.load(f)
TEAM_NAME_MAP = {k: v for k, v in _RAW_MAP.items() if not k.startswith("_")}


def _nombre_en_elo(nombre_api_football: str) -> str:
    return TEAM_NAME_MAP.get(nombre_api_football, nombre_api_football)


def _es_liga_excluida(nombre_liga: str) -> bool:
    nombre_liga_low = nombre_liga.lower()
    return any(palabra in nombre_liga_low for palabra in config.LIGAS_EXCLUIDAS_PALABRAS_CLAVE)


def _puntaje_elo(diferencia: float) -> float:
    """Escala lineal simple entre los puntos de referencia del diseño."""
    puntos_referencia = [(0, 0), (50, 20), (100, 30), (150, 35), (200, 40)]
    diferencia = max(0, diferencia)
    if diferencia >= 200:
        return config.PESO_ELO
    for (x0, y0), (x1, y1) in zip(puntos_referencia, puntos_referencia[1:]):
        if x0 <= diferencia <= x1:
            return y0 + (y1 - y0) * (diferencia - x0) / (x1 - x0)
    return 0


def _probabilidad_clubelo(fixtures_clubelo: list, local: str, visitante: str) -> float:
    """Busca la probabilidad de victoria del local en el CSV de ClubElo /Fixtures."""
    for fila in fixtures_clubelo:
        if fila.get("Home") == local and fila.get("Away") == visitante:
            try:
                return float(fila.get("HomeWinProbability", 0))
            except (ValueError, TypeError):
                return 0.0
    return 0.0


def escanear_semana(fecha_inicio: datetime = None) -> list:
    """
    Descarga Elo + calendario de 7 días, cruza nombres, aplica filtro duro,
    calcula el puntaje de selección y devuelve TODOS los partidos que superan
    el umbral (sin límite de cantidad).
    """
    if fecha_inicio is None:
        fecha_inicio = datetime.utcnow()

    fecha_elo_str = fecha_inicio.strftime("%Y-%m-%d")
    elo_dict = fetch_data.descargar_elo_del_dia(fecha_elo_str)
    fixtures_clubelo = fetch_data.descargar_probabilidades_fixtures()

    candidatos = []
    sin_cruce = []

    for offset in range(config.DIAS_A_ESCANEAR):
        fecha = (fecha_inicio + timedelta(days=offset)).strftime("%Y-%m-%d")
        calendario = fetch_data.obtener_calendario(fecha)
        partidos = calendario.get("response", [])

        for partido in partidos:
            liga = partido["league"]["name"]
            if _es_liga_excluida(liga):
                continue

            local = partido["teams"]["home"]["name"]
            visitante = partido["teams"]["away"]["name"]

            local_elo_nombre = _nombre_en_elo(local)
            visitante_elo_nombre = _nombre_en_elo(visitante)

            info_local = elo_dict.get(local_elo_nombre)
            info_visitante = elo_dict.get(visitante_elo_nombre)

            if info_local is None:
                sin_cruce.append({"equipo_api_football": local, "nombre_buscado_en_elo": local_elo_nombre, "fecha": fecha})
            if info_visitante is None:
                sin_cruce.append({"equipo_api_football": visitante, "nombre_buscado_en_elo": visitante_elo_nombre, "fecha": fecha})
            if info_local is None or info_visitante is None:
                continue  # falso negativo controlado: queda logueado, no silencioso

            diff_elo = info_local["elo"] - info_visitante["elo"]
            favorito, rival, es_local, diff_abs = (
                (local, visitante, True, diff_elo) if diff_elo >= 0
                else (visitante, local, False, -diff_elo)
            )

            if diff_abs < config.DIFERENCIA_ELO_MINIMA:
                continue

            prob_clubelo = _probabilidad_clubelo(fixtures_clubelo, local, visitante)
            prob_favorito = prob_clubelo if es_local else (1 - prob_clubelo)

            nivel_liga = info_local["level"] or info_visitante["level"] or 3
            puntos_liga = config.PESO_LIGA if nivel_liga == 1 else (8 if nivel_liga == 2 else 3)

            puntaje = (
                _puntaje_elo(diff_abs)
                + (config.PESO_LOCALIA if es_local == (favorito == local) else 5)
                + prob_favorito * config.PESO_PROB_CLUBELO
                + puntos_liga
            )

            if puntaje >= config.UMBRAL_PUNTAJE_SELECCION:
                candidatos.append({
                    "fixture_id": partido["fixture"]["id"],
                    "fecha": fecha,
                    "liga": liga,
                    "favorito": favorito,
                    "rival": rival,
                    "favorito_es_local": (favorito == local),
                    "elo_favorito": info_local["elo"] if favorito == local else info_visitante["elo"],
                    "elo_rival": info_visitante["elo"] if favorito == local else info_local["elo"],
                    "diferencia_elo": diff_abs,
                    "puntaje_seleccion": round(puntaje, 1),
                })

    _guardar_sin_cruce(sin_cruce, fecha_elo_str)
    candidatos.sort(key=lambda c: c["puntaje_seleccion"], reverse=True)

    with open(f"{config.DATA_DIR}/candidatos_semana.json", "w", encoding="utf-8") as f:
        json.dump(candidatos, f, ensure_ascii=False, indent=2)

    log.info("Selección semanal: %d partidos superaron el umbral (sin tope de cantidad)", len(candidatos))
    return candidatos


def _guardar_sin_cruce(sin_cruce: list, fecha: str) -> None:
    if not sin_cruce:
        return
    ruta = f"{config.DATA_DIR}/sin_cruce_{fecha}.json"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(sin_cruce, f, ensure_ascii=False, indent=2)

    equipos_unicos = sorted({e["equipo_api_football"] for e in sin_cruce})
    mensaje = f"🔧 Aviso técnico — equipos sin Elo esta semana ({len(equipos_unicos)})\n"
    mensaje += "\n".join(f"- {eq}" for eq in equipos_unicos[:30])
    if len(equipos_unicos) > 30:
        mensaje += f"\n... y {len(equipos_unicos) - 30} más (ver {ruta})"
    telegram_utils.enviar_aviso_tecnico(mensaje)


if __name__ == "__main__":
    escanear_semana()
