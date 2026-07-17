"""
FASE 4 — Índice de Presión en Vivo (LPI).
Traduce las estadísticas de /fixtures/statistics en un puntaje 0-100
que mide qué tan cerca está el favorito de marcar.
"""


def _extraer_stat(stats_equipo: dict, tipo: str, default=0):
    for item in stats_equipo.get("statistics", []):
        if item["type"] == tipo:
            valor = item["value"]
            if valor is None:
                return default
            if isinstance(valor, str) and "%" in valor:
                return float(valor.replace("%", ""))
            return float(valor)
    return default


def calcular_lpi(stats_data: dict, favorito_es_local: bool) -> int:
    respuesta = stats_data.get("response", [])
    if len(respuesta) < 2:
        return 0

    stats_local = respuesta[0]
    stats_visitante = respuesta[1]
    stats_favorito, stats_rival = (stats_local, stats_visitante) if favorito_es_local else (stats_visitante, stats_local)

    posesion_favorito = _extraer_stat(stats_favorito, "Ball Possession", 50)
    tiros_favorito = _extraer_stat(stats_favorito, "Total Shots")
    tiros_rival = _extraer_stat(stats_rival, "Total Shots")
    tiros_puerta_favorito = _extraer_stat(stats_favorito, "Shots on Goal")
    tiros_puerta_rival = _extraer_stat(stats_rival, "Shots on Goal")
    corners_favorito = _extraer_stat(stats_favorito, "Corner Kicks")
    corners_rival = _extraer_stat(stats_rival, "Corner Kicks")
    xg_favorito = _extraer_stat(stats_favorito, "expected_goals", None)
    xg_rival = _extraer_stat(stats_rival, "expected_goals", None)

    puntos = 0

    if posesion_favorito > 65:
        puntos += 10
    elif posesion_favorito > 55:
        puntos += 5

    diff_tiros = tiros_favorito - tiros_rival
    if diff_tiros >= 10:
        puntos += 20
    elif diff_tiros >= 5:
        puntos += 10

    diff_tiros_puerta = tiros_puerta_favorito - tiros_puerta_rival
    if diff_tiros_puerta >= 5:
        puntos += 20
    elif diff_tiros_puerta >= 2:
        puntos += 10

    if xg_favorito is not None and xg_rival is not None:
        diff_xg = xg_favorito - xg_rival
        if diff_xg > 1.5:
            puntos += 20
        elif diff_xg > 0.7:
            puntos += 10

    diff_corners = corners_favorito - corners_rival
    if diff_corners >= 6:
        puntos += 10
    elif diff_corners >= 3:
        puntos += 5

    return min(100, int(puntos))
