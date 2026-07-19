"""
FASE 1 — Selección semanal de favoritos.
Escanea 7 días de calendario de una sola vez. Usa el Elo PROPIO del sistema
(elo_engine.py), sembrado desde ClubElo cuando es posible, reconstruido
desde historial cuando no. Filtra por UMBRAL de puntaje (no por top-N).
"""
import json
import logging
from datetime import datetime, timedelta

import config
import fetch_data
import elo_engine
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


def escanear_semana(fecha_inicio: datetime = None) -> list:
    if fecha_inicio is None:
        fecha_inicio = datetime.utcnow()

    fecha_elo_str = fecha_inicio.strftime("%Y-%m-%d")
    elo_clubelo = fetch_data.descargar_elo_del_dia(fecha_elo_str)
    fixtures_clubelo = fetch_data.descargar_probabilidades_fixtures()

    candidatos = []
    equipos_reconstruidos = []

    for offset in range(config.DIAS_A_ESCANEAR):
        fecha = (fecha_inicio + timedelta(days=offset)).strftime("%Y-%m-%d")
        calendario = fetch_data.obtener_calendario(fecha)
        partidos = calendario.get("response", [])

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

            elo_local = elo_engine.obtener_o_crear_elo(
                local_id, local_nombre, liga_id, elo_clubelo, nombre_ce_local
            )
            elo_visitante = elo_engine.obtener_o_crear_elo(
                visitante_id, visitante_nombre, liga_id, elo_clubelo, nombre_ce_visitante
            )

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

            if puntaje >= config.UMBRAL_PUNTAJE_SELECCION:
                candidatos.append({
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
                })

    _avisar_reconstrucciones(equipos_reconstruidos, fecha_elo_str)
    candidatos.sort(key=lambda c: c["puntaje_seleccion"], reverse=True)

    with open(f"{config.DATA_DIR}/candidatos_semana.json", "w", encoding="utf-8") as f:
        json.dump(candidatos, f, ensure_ascii=False, indent=2)

    log.info("Selección semanal: %d partidos superaron el umbral (sin tope de cantidad)", len(candidatos))
    return candidatos


def _avisar_reconstrucciones(equipos: list, fecha: str) -> None:
    if not equipos:
        return
    equipos_unicos = sorted(set(equipos))
    mensaje = f"Aviso tecnico: esta semana se calculo Elo propio para {len(equipos_unicos)} equipos nuevos (no estaban en ClubElo)\n"
    mensaje += "\n".join(f"- {eq}" for eq in equipos_unicos[:30])
    if len(equipos_unicos) > 30:
        mensaje += f"\n... y {len(equipos_unicos) - 30} mas"
    telegram_utils.enviar_aviso_tecnico(mensaje)


if __name__ == "__main__":
    escanear_semana()
