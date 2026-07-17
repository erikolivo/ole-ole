"""
Wrappers de acceso a ClubElo (gratis, sin límite) y API-Football (100 req/día).
Toda llamada HTTP pasa por aquí para poder cachear, loguear y contar requests
en un solo lugar.
"""
import os
import json
import csv
import io
import logging
from datetime import datetime, timedelta

import requests

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

os.makedirs(config.DATA_DIR, exist_ok=True)


def _ruta(nombre_archivo: str) -> str:
    return os.path.join(config.DATA_DIR, nombre_archivo)


def _guardar_json(nombre_archivo: str, data) -> None:
    with open(_ruta(nombre_archivo), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _leer_json(nombre_archivo: str, default=None):
    ruta = _ruta(nombre_archivo)
    if not os.path.exists(ruta):
        return default
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _contar_request(endpoint: str) -> None:
    """Lleva un contador simple de requests gastados hoy, para monitorear el límite de 100/día."""
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    contador = _leer_json(f"contador_requests_{hoy}.json", default={"total": 0, "detalle": {}})
    contador["total"] += 1
    contador["detalle"][endpoint] = contador["detalle"].get(endpoint, 0) + 1
    _guardar_json(f"contador_requests_{hoy}.json", contador)
    if contador["total"] > 90:
        log.warning("⚠️ Cuota de API-Football cerca del límite: %s requests hoy", contador["total"])


# ---------------------------------------------------------------------------
# ClubElo — gratis, sin límite, sin autenticación
# ---------------------------------------------------------------------------

def descargar_elo_del_dia(fecha: str, forzar: bool = False) -> dict:
    """
    fecha en formato YYYY-MM-DD.
    Devuelve dict {nombre_club: {"elo": float, "rank": int, "level": int, "country": str}}
    """
    nombre_archivo = f"elo_{fecha}.csv"
    ruta = _ruta(nombre_archivo)

    if os.path.exists(ruta) and not forzar:
        log.info("Elo del %s ya en caché, no se vuelve a descargar", fecha)
    else:
        url = f"{config.CLUBELO_BASE_URL}/{fecha}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(resp.text)
        log.info("Elo del %s descargado y cacheado (0 requests de API-Football)", fecha)

    elo_dict = {}
    with open(ruta, "r", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        for fila in lector:
            try:
                elo_dict[fila["Club"]] = {
                    "elo": float(fila["Elo"]),
                    "rank": int(fila["Rank"]) if fila["Rank"] else None,
                    "level": int(fila["Level"]) if fila["Level"] else None,
                    "country": fila["Country"],
                }
            except (ValueError, KeyError):
                continue
    return elo_dict


def descargar_probabilidades_fixtures(forzar: bool = False) -> list:
    """
    ClubElo /Fixtures: probabilidades ya calculadas para los próximos partidos.
    0 requests de tu cuota de API-Football.
    """
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    nombre_archivo = f"clubelo_fixtures_{hoy}.csv"
    ruta = _ruta(nombre_archivo)

    if not (os.path.exists(ruta) and not forzar):
        url = f"{config.CLUBELO_BASE_URL}/Fixtures"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(resp.text)

    filas = []
    with open(ruta, "r", encoding="utf-8") as f:
        lector = csv.DictReader(f)
        for fila in lector:
            filas.append(fila)
    return filas


# ---------------------------------------------------------------------------
# API-Football — 100 requests/día, cuenta cada llamada
# ---------------------------------------------------------------------------

def _headers_api_football() -> dict:
    return {
        "x-rapidapi-host": config.API_FOOTBALL_HOST,
        "x-rapidapi-key": config.API_FOOTBALL_KEY,
    }


def _get_api_football(endpoint: str, params: dict, timeout: int = 15) -> dict:
    """
    Llamada cruda a API-Football. Lanza excepción en fallo de red/HTTP;
    quien la use debe decidir cómo tolerar el fallo (ver live_monitor.py).
    """
    url = f"{config.API_FOOTBALL_BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=_headers_api_football(), params=params, timeout=timeout)
    resp.raise_for_status()
    _contar_request(endpoint)
    return resp.json()


def obtener_calendario(fecha: str, forzar: bool = False) -> dict:
    """1 request por día consultado (Fase 1, 7 veces por semana)."""
    nombre_archivo = f"fixtures_{fecha}.json"
    if os.path.exists(_ruta(nombre_archivo)) and not forzar:
        log.info("Calendario del %s ya en caché", fecha)
        return _leer_json(nombre_archivo)

    data = _get_api_football("fixtures", {"date": fecha})
    _guardar_json(nombre_archivo, data)
    return data


def obtener_predictions(fixture_id: int, forzar: bool = False) -> dict:
    """1 request por partido confirmado (Fase 2, repartido en la semana)."""
    nombre_archivo = f"predictions_{fixture_id}.json"
    if os.path.exists(_ruta(nombre_archivo)) and not forzar:
        return _leer_json(nombre_archivo)

    data = _get_api_football("predictions", {"fixture": fixture_id})
    _guardar_json(nombre_archivo, data)
    return data


def obtener_partidos_en_vivo() -> dict:
    """
    1 sola request que devuelve TODOS los partidos en vivo del mundo.
    No cachear: por definición cambia en cada sondeo.
    """
    return _get_api_football("fixtures", {"live": "all"})


def obtener_estadisticas_partido(fixture_id: int) -> dict:
    """1 request por partido caliente, por sondeo (Fase 4)."""
    return _get_api_football("fixtures/statistics", {"fixture": fixture_id})


def requests_gastados_hoy() -> int:
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    contador = _leer_json(f"contador_requests_{hoy}.json", default={"total": 0})
    return contador["total"]
