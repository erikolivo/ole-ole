"""
FASE 3 y 4 — Vigilancia en vivo.
Un solo job se auto-vigila con sleep() interno (no depende de la frecuencia
real del cron de GitHub Actions, que no está garantizada). Tolera fallos de
red/API sin perder el estado, y persiste todo en disco para poder encadenar
bloques de hasta 6 horas.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def _ruta_estado(fecha: str) -> str:
    return f"{config.DATA_DIR}/estado_vivo_{fecha}.json"


def cargar_estado(fecha: str) -> dict:
    """Se lee SIEMPRE de disco al iniciar — nunca se asume memoria de un bloque anterior."""
    try:
        with open(_ruta_estado(fecha), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def guardar_estado(fecha: str, estado: dict) -> None:
    with open(_ruta_estado(fecha), "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def inicializar_estado_desde_vigilancia(fecha: str) -> dict:
    """La primera vez que corre el bloque del día, siembra el estado desde vigilancia_YYYY-MM-DD.json."""
    estado = cargar_estado(fecha)
    if estado:
        return estado  # ya existe, probablemente retomando de un bloque anterior

    try:
        with open(f"{config.DATA_DIR}/vigilancia_{fecha}.json", "r", encoding="utf-8") as f:
            vigilancia = json.load(f)
    except FileNotFoundError:
        vigilancia = []

    estado = {}
    for partido in vigilancia:
        estado[str(partido["fixture_id"])] = {
            "favorito": partido["favorito"],
            "rival": partido["rival"],
            "favorito_es_local": partido["favorito_es_local"],
            "indice_superioridad": partido["indice_superioridad"],
            "estado": "vigilando_marcador",
            "ultimo_marcador_visto": None,
            "ultimo_minuto_visto": 0,
            "alertado": False,
            "ultimo_sondeo_exitoso": None,
            "fallos_consecutivos": 0,
        }
    guardar_estado(fecha, estado)
    return estado


def _sondear_marcadores(estado: dict) -> dict:
    """1 sola llamada cubre todos los partidos en vivo del mundo (Fase 3)."""
    try:
        data = fetch_data.obtener_partidos_en_vivo()
    except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
        log.error("Sondeo de marcador fallido: %s", e)
        for fixture_id in estado:
            estado[fixture_id]["fallos_consecutivos"] += 1
            if estado[fixture_id]["fallos_consecutivos"] >= config.FALLOS_CONSECUTIVOS_PARA_AVISAR:
                telegram_utils.enviar_aviso_tecnico(
                    f"🔧 {config.FALLOS_CONSECUTIVOS_PARA_AVISAR}+ sondeos fallidos seguidos "
                    f"para fixture {fixture_id} — revisar API o cuota"
                )
        return estado  # estado previo se conserva intacto, no se pierde nada

    partidos_en_vivo = {str(p["fixture"]["id"]): p for p in data.get("response", [])}

    for fixture_id, info in estado.items():
        info["fallos_consecutivos"] = 0
        info["ultimo_sondeo_exitoso"] = datetime.utcnow().isoformat()

        partido_vivo = partidos_en_vivo.get(fixture_id)
        if partido_vivo is None:
            continue  # aún no empezó, ya terminó, o no está en vivo en este ciclo

        goles_local = partido_vivo["goals"]["home"] or 0
        goles_visitante = partido_vivo["goals"]["away"] or 0
        minuto = partido_vivo["fixture"]["status"]["elapsed"] or 0

        goles_favorito = goles_local if info["favorito_es_local"] else goles_visitante
        goles_rival = goles_visitante if info["favorito_es_local"] else goles_local

        info["ultimo_marcador_visto"] = f"{goles_favorito}-{goles_rival}"
        info["ultimo_minuto_visto"] = minuto

        empatando_o_perdiendo_por_uno = (goles_favorito == goles_rival) or (goles_favorito == goles_rival - 1)
        condicion_cumplida = (
            empatando_o_perdiendo_por_uno
            and minuto >= config.MINUTO_MINIMO_PARA_CANDIDATO
        )

        if goles_favorito >= goles_rival + 2 or goles_rival >= goles_favorito + 2 or partido_vivo["fixture"]["status"]["short"] == "FT":
            info["estado"] = "retirado"
        elif condicion_cumplida:
            info["estado"] = "candidato_caliente"
        else:
            info["estado"] = "vigilando_marcador"

    return estado


def _sondear_estadisticas_calientes(estado: dict) -> dict:
    """Fase 4: solo para los que están en candidato_caliente."""
    calientes = {fid: info for fid, info in estado.items() if info["estado"] == "candidato_caliente"}
    if not calientes:
        return estado

    for fixture_id, info in calientes.items():
        try:
            stats_data = fetch_data.obtener_estadisticas_partido(int(fixture_id))
        except Exception as e:
            log.warning("Fallo estadísticas fixture %s: %s (se reintenta el próximo ciclo)", fixture_id, e)
            continue  # no se descarta el partido, solo se pierde esta lectura puntual

        lpi = lpi_engine.calcular_lpi(stats_data, info["favorito_es_local"])
        info["lpi_actual"] = lpi

        if lpi >= config.LPI_UMBRAL_ALERTA and not info["alertado"]:
            telegram_utils.enviar_alerta_oportunidad(fixture_id, info, lpi, stats_data)
            info["alertado"] = True
        elif lpi >= config.LPI_UMBRAL_VIGILAR_CERCA:
            info["estado"] = "vigilar_de_cerca"

    return estado


def correr_bloque(fecha: str = None, max_horas: float = None) -> None:
    """
    Loop principal: se auto-vigila con sleep() interno en vez de depender del
    cron de GitHub Actions. Corre hasta max_horas o hasta que ya no queden
    partidos activos, lo que ocurra primero.
    """
    fecha = fecha or datetime.utcnow().strftime("%Y-%m-%d")
    max_horas = max_horas or config.MAX_HORAS_POR_BLOQUE

    estado = inicializar_estado_desde_vigilancia(fecha)
    inicio = time.time()
    limite_segundos = max_horas * 3600

    while time.time() - inicio < limite_segundos:
        activos = {k: v for k, v in estado.items() if v["estado"] != "retirado"}
        if not activos:
            log.info("No quedan partidos activos hoy, terminando bloque antes de tiempo")
            break

        estado = _sondear_marcadores(estado)
        estado = _sondear_estadisticas_calientes(estado)
        guardar_estado(fecha, estado)

        n_calientes = sum(1 for v in estado.values() if v["estado"] == "candidato_caliente")
        intervalo = config.intervalo_sondeo_segundos(n_calientes)
        log.info(
            "Ciclo completo. Activos: %d, calientes: %d, requests hoy: %d, próximo sondeo en %ds",
            len(activos), n_calientes, fetch_data.requests_gastados_hoy(), intervalo,
        )
        time.sleep(intervalo)

    guardar_estado(fecha, estado)
    log.info("Bloque terminado (límite de %.1fh alcanzado o partidos finalizados)", max_horas)


if __name__ == "__main__":
    correr_bloque()
