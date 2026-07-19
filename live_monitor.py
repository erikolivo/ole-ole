"""
FASE 3 y 4 — Vigilancia en vivo, rediseñada.
Cambios respecto a la v1:
- Ya no hay minuto minimo fijo. La ventana temprana se dispara por
  presion sostenida en sondeos consecutivos, con techo en el minuto 35.
- 4 ventanas con distinto umbral segun el minuto del partido.
- El LPI incluye momentum y el multiplicador del IS pre-partido.
- Ya no hay restriccion de marcador: se vigila a TODOS los favoritos
  activos, y el mensaje de Telegram distingue la situacion.
"""
import json
import time
import logging
from datetime import datetime

import requests

import config
import fetch_data
import lpi_engine
import telegram_utils
import elo_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def _ruta_estado(fecha: str) -> str:
    return f"{config.DATA_DIR}/estado_vivo_{fecha}.json"


def cargar_estado(fecha: str) -> dict:
    try:
        with open(_ruta_estado(fecha), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def guardar_estado(fecha: str, estado: dict) -> None:
    with open(_ruta_estado(fecha), "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def inicializar_estado_desde_vigilancia(fecha: str) -> dict:
    estado = cargar_estado(fecha)
    if estado:
        return estado

    try:
        with open(f"{config.DATA_DIR}/vigilancia_{fecha}.json", "r", encoding="utf-8") as f:
            vigilancia = json.load(f)
    except FileNotFoundError:
        vigilancia = []

    estado = {}
    for partido in vigilancia:
        estado[str(partido["fixture_id"])] = {
            "favorito": partido["favorito"],
            "favorito_id": partido.get("favorito_id"),
            "rival": partido["rival"],
            "rival_id": partido.get("rival_id"),
            "favorito_es_local": partido["favorito_es_local"],
            "indice_superioridad": partido["indice_superioridad"],
            "validado_mercado": partido.get("validado_mercado"),
            "discrepancia_mercado": partido.get("discrepancia_mercado"),
            "estado": "vigilando",
            "ultimo_marcador_visto": None,
            "ultimo_minuto_visto": 0,
            "alertas_enviadas": [],   # lista de ventanas ya alertadas: ["temprana","normal","gol_inminente","ultima_oportunidad"]
            "stats_sondeo_anterior": {},
            "sondeos_presion_consecutivos": 0,
            "ultimo_sondeo_exitoso": None,
            "fallos_consecutivos": 0,
            "elo_actualizado": False,
        }
    guardar_estado(fecha, estado)
    return estado


def _sondear_marcadores(estado: dict) -> dict:
    try:
        data = fetch_data.obtener_partidos_en_vivo()
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
        log.error("Sondeo de marcador fallido: %s", e)
        for fixture_id in estado:
            estado[fixture_id]["fallos_consecutivos"] += 1
            if estado[fixture_id]["fallos_consecutivos"] >= config.FALLOS_CONSECUTIVOS_PARA_AVISAR:
                telegram_utils.enviar_aviso_tecnico(
                    f"{config.FALLOS_CONSECUTIVOS_PARA_AVISAR}+ sondeos fallidos seguidos "
                    f"para fixture {fixture_id} - revisar API o cuota"
                )
        return estado

    partidos_en_vivo = {str(p["fixture"]["id"]): p for p in data.get("response", [])}

    for fixture_id, info in estado.items():
        info["fallos_consecutivos"] = 0
        info["ultimo_sondeo_exitoso"] = datetime.utcnow().isoformat()

        partido_vivo = partidos_en_vivo.get(fixture_id)
        if partido_vivo is None:
            continue

        goles_local = partido_vivo["goals"]["home"] or 0
        goles_visitante = partido_vivo["goals"]["away"] or 0
        minuto = partido_vivo["fixture"]["status"]["elapsed"] or 0

        goles_favorito = goles_local if info["favorito_es_local"] else goles_visitante
        goles_rival = goles_visitante if info["favorito_es_local"] else goles_local

        info["ultimo_marcador_visto"] = f"{goles_favorito}-{goles_rival}"
        info["ultimo_minuto_visto"] = minuto

        if partido_vivo["fixture"]["status"]["short"] == "FT":
            info["estado"] = "finalizado"
            if not info.get("elo_actualizado") and info.get("favorito_id") and info.get("rival_id"):
                goles_local_final = goles_favorito if info["favorito_es_local"] else goles_rival
                goles_visitante_final = goles_rival if info["favorito_es_local"] else goles_favorito
                team_id_local = info["favorito_id"] if info["favorito_es_local"] else info["rival_id"]
                team_id_visitante = info["rival_id"] if info["favorito_es_local"] else info["favorito_id"]
                try:
                    elo_engine.actualizar_tras_resultado(
                        team_id_local, team_id_visitante, goles_local_final, goles_visitante_final
                    )
                    info["elo_actualizado"] = True
                except Exception as e:
                    log.warning("No se pudo actualizar Elo tras resultado de fixture %s: %s", fixture_id, e)
        else:
            info["estado"] = "vigilando"

    return estado


def _ventana_activa(minuto: int, sondeos_presion_consecutivos: int, alertas_enviadas: list) -> str:
    """
    Decide en que ventana esta el partido ahora mismo, segun el minuto Y
    la presion detectada (para la ventana temprana). Devuelve el nombre
    de la ventana o None si no corresponde evaluar ninguna todavia.
    """
    if minuto <= config.VENTANA_TEMPRANA_MINUTO_TOPE and "temprana" not in alertas_enviadas:
        if sondeos_presion_consecutivos >= config.MOMENTUM_SONDEOS_CONSECUTIVOS_REQUERIDOS:
            return "temprana"
        return None   # todavia no hay suficiente presion sostenida, no se evalua LPI todavia

    if minuto > config.VENTANA_TEMPRANA_MINUTO_TOPE and minuto <= 75 and "normal" not in alertas_enviadas:
        return "normal"
    if 75 < minuto <= 85 and "gol_inminente" not in alertas_enviadas:
        return "gol_inminente"
    if minuto > 85 and "ultima_oportunidad" not in alertas_enviadas:
        return "ultima_oportunidad"
    return None


_UMBRAL_POR_VENTANA = {
    "temprana": config.LPI_UMBRAL_VENTANA_TEMPRANA,
    "normal": config.LPI_UMBRAL_NORMAL,
    "gol_inminente": config.LPI_UMBRAL_GOL_INMINENTE,
    "ultima_oportunidad": config.LPI_UMBRAL_ULTIMA_OPORTUNIDAD,
}

_ETIQUETA_POR_VENTANA = {
    "temprana": ("🔥", "Dominio sostenido del primer tiempo"),
    "normal": ("⚡", "Presion alta"),
    "gol_inminente": ("⏰", "Gol inminente"),
    "ultima_oportunidad": ("🚨", "Ultima oportunidad"),
}


def _sondear_estadisticas_y_evaluar(estado: dict) -> dict:
    activos = {fid: info for fid, info in estado.items() if info["estado"] == "vigilando"}

    for fixture_id, info in activos.items():
        minuto = info["ultimo_minuto_visto"]
        ventana = _ventana_activa(minuto, info["sondeos_presion_consecutivos"], info["alertas_enviadas"])

        # Aunque no toque evaluar alerta todavia, seguimos midiendo presion
        # temprana para saber cuando se cumplen los sondeos consecutivos.
        necesita_stats = ventana is not None or minuto <= config.VENTANA_TEMPRANA_MINUTO_TOPE

        if not necesita_stats:
            continue

        try:
            stats_data = fetch_data.obtener_estadisticas_partido(int(fixture_id))
        except Exception as e:
            log.warning("Fallo estadisticas fixture %s: %s (se reintenta el proximo ciclo)", fixture_id, e)
            continue

        factor_is = info["indice_superioridad"] or 0
        resultado = lpi_engine.calcular_lpi(
            stats_data, info["favorito_es_local"],
            stats_sondeo_anterior=info["stats_sondeo_anterior"],
            factor_is=factor_is,
        )
        lpi = resultado["lpi"]
        momentum = resultado.get("momentum", 0)

        # actualizar contador de presion sostenida (para la ventana temprana)
        if momentum >= config.MOMENTUM_UMBRAL_PRESION:
            info["sondeos_presion_consecutivos"] += 1
        else:
            info["sondeos_presion_consecutivos"] = 0

        info["stats_sondeo_anterior"] = resultado["stats_actuales"]
        info["lpi_actual"] = lpi

        if ventana and lpi >= _UMBRAL_POR_VENTANA[ventana]:
            telegram_utils.enviar_alerta_oportunidad(fixture_id, info, lpi, ventana)
            info["alertas_enviadas"].append(ventana)

    return estado


def correr_bloque(fecha: str = None, max_horas: float = None) -> None:
    fecha = fecha or datetime.utcnow().strftime("%Y-%m-%d")
    max_horas = max_horas or config.MAX_HORAS_POR_BLOQUE

    estado = inicializar_estado_desde_vigilancia(fecha)
    inicio = time.time()
    limite_segundos = max_horas * 3600

    while time.time() - inicio < limite_segundos:
        activos = {k: v for k, v in estado.items() if v["estado"] != "finalizado"}
        if not activos:
            log.info("No quedan partidos activos hoy, terminando bloque antes de tiempo")
            break

        estado = _sondear_marcadores(estado)
        estado = _sondear_estadisticas_y_evaluar(estado)
        guardar_estado(fecha, estado)

        n_evaluando_stats = sum(
            1 for v in estado.values()
            if v["estado"] == "vigilando" and v["ultimo_minuto_visto"] <= 85
        )
        intervalo = config.intervalo_sondeo_segundos(n_evaluando_stats)
        log.info(
            "Ciclo completo. Activos: %d, requests hoy: %d, proximo sondeo en %ds",
            len(activos), fetch_data.requests_gastados_hoy(), intervalo,
        )
        time.sleep(intervalo)

    guardar_estado(fecha, estado)
    log.info("Bloque terminado (limite de %.1fh alcanzado o partidos finalizados)", max_horas)


if __name__ == "__main__":
    correr_bloque()
