"""
FASE 4 — Indice de Presion en Vivo (LPI), rediseñado.
Cambios respecto a la v1:
- Sin xG (no es confiable en el plan gratis de API-Football).
- Con momentum: compara este sondeo contra el sondeo anterior, no solo
  el acumulado del partido.
- Pesos normalizados dinamicamente si alguna variable no trae dato.
- Multiplicador segun el Indice de Superioridad pre-partido (IS).
"""
import config


def _extraer_stat(stats_equipo: dict, tipo: str, default=None):
    for item in stats_equipo.get("statistics", []):
        if item["type"] == tipo:
            valor = item["value"]
            if valor is None:
                return default
            if isinstance(valor, str) and "%" in valor:
                return float(valor.replace("%", ""))
            try:
                return float(valor)
            except (ValueError, TypeError):
                return default
    return default


def _leer_stats_partido(stats_data: dict, favorito_es_local: bool) -> dict:
    respuesta = stats_data.get("response", [])
    if len(respuesta) < 2:
        return {}
    stats_local, stats_visitante = respuesta[0], respuesta[1]
    stats_favorito, stats_rival = (stats_local, stats_visitante) if favorito_es_local else (stats_visitante, stats_local)

    return {
        "posesion": _extraer_stat(stats_favorito, "Ball Possession"),
        "tiros_totales_favorito": _extraer_stat(stats_favorito, "Total Shots"),
        "tiros_totales_rival": _extraer_stat(stats_rival, "Total Shots"),
        "tiros_puerta_favorito": _extraer_stat(stats_favorito, "Shots on Goal"),
        "tiros_puerta_rival": _extraer_stat(stats_rival, "Shots on Goal"),
        "corners_favorito": _extraer_stat(stats_favorito, "Corner Kicks"),
        "corners_rival": _extraer_stat(stats_rival, "Corner Kicks"),
        "ataques_peligrosos_favorito": _extraer_stat(stats_favorito, "Dangerous Attacks"),
        "ataques_peligrosos_rival": _extraer_stat(stats_rival, "Dangerous Attacks"),
    }


def calcular_momentum(stats_actual: dict, stats_anterior: dict) -> float:
    """
    Diferencia de presion entre este sondeo y el anterior. Positivo = subiendo.
    Se basa en tiros + corners del favorito, comparado sondeo a sondeo.
    """
    if not stats_anterior:
        return 0.0

    actual = (stats_actual.get("tiros_totales_favorito") or 0) + (stats_actual.get("corners_favorito") or 0)
    anterior = (stats_anterior.get("tiros_totales_favorito") or 0) + (stats_anterior.get("corners_favorito") or 0)
    return actual - anterior


def calcular_lpi(stats_data: dict, favorito_es_local: bool, stats_sondeo_anterior: dict = None,
                  factor_is: float = 0.0) -> dict:
    """
    Devuelve {"lpi": int, "stats_actuales": dict} para que live_monitor.py
    guarde stats_actuales como "stats_sondeo_anterior" del proximo ciclo.
    """
    stats = _leer_stats_partido(stats_data, favorito_es_local)
    if not stats:
        return {"lpi": 0, "stats_actuales": {}}

    momentum = calcular_momentum(stats, stats_sondeo_anterior)

    # puntaje bruto por variable (antes de normalizar), None si falta el dato
    puntos_por_variable = {}

    if stats.get("posesion") is not None:
        pos = stats["posesion"]
        puntos_por_variable["posesion"] = config.PESOS_LPI["posesion"] if pos > 65 else (
            config.PESOS_LPI["posesion"] * 0.5 if pos > 55 else 0
        )

    if stats.get("tiros_totales_favorito") is not None and stats.get("tiros_totales_rival") is not None:
        diff = stats["tiros_totales_favorito"] - stats["tiros_totales_rival"]
        puntos_por_variable["tiros_totales"] = config.PESOS_LPI["tiros_totales"] if diff >= 10 else (
            config.PESOS_LPI["tiros_totales"] * 0.5 if diff >= 5 else 0
        )

    if stats.get("tiros_puerta_favorito") is not None and stats.get("tiros_puerta_rival") is not None:
        diff = stats["tiros_puerta_favorito"] - stats["tiros_puerta_rival"]
        puntos_por_variable["tiros_puerta"] = config.PESOS_LPI["tiros_puerta"] if diff >= 5 else (
            config.PESOS_LPI["tiros_puerta"] * 0.5 if diff >= 2 else 0
        )

    if stats.get("corners_favorito") is not None and stats.get("corners_rival") is not None:
        diff = stats["corners_favorito"] - stats["corners_rival"]
        puntos_por_variable["corners"] = config.PESOS_LPI["corners"] if diff >= 6 else (
            config.PESOS_LPI["corners"] * 0.5 if diff >= 3 else 0
        )

    if stats.get("ataques_peligrosos_favorito") is not None and stats.get("ataques_peligrosos_rival") is not None:
        diff = stats["ataques_peligrosos_favorito"] - stats["ataques_peligrosos_rival"]
        puntos_por_variable["ataques_peligrosos"] = config.PESOS_LPI["ataques_peligrosos"] if diff >= 15 else (
            config.PESOS_LPI["ataques_peligrosos"] * 0.5 if diff >= 8 else 0
        )

    # momentum: siempre disponible si hubo sondeo anterior
    if stats_sondeo_anterior:
        puntos_por_variable["momentum"] = config.PESOS_LPI["momentum"] if momentum >= 6 else (
            config.PESOS_LPI["momentum"] * 0.5 if momentum >= 3 else 0
        )

    # normalizacion dinamica: si faltan variables, el resto se reescala
    peso_maximo_disponible = sum(config.PESOS_LPI[v] for v in puntos_por_variable)
    peso_maximo_total = sum(config.PESOS_LPI.values())

    if peso_maximo_disponible == 0:
        lpi_bruto = 0
    else:
        suma_puntos = sum(puntos_por_variable.values())
        lpi_bruto = suma_puntos * (peso_maximo_total / peso_maximo_disponible)

    lpi_ajustado = lpi_bruto * (1 + factor_is / 100)

    return {
        "lpi": min(100, int(round(lpi_ajustado))),
        "momentum": momentum,
        "stats_actuales": stats,
    }
