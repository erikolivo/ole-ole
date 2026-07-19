"""
FASE 2.5 — Validación cruzada con el mercado (the-odds-api, gratis).
No decide favoritos, no cambia puntajes: solo marca "validado_mercado"
o "discrepancia_mercado" en los partidos ya confirmados, para dar
contexto extra en el mensaje de Telegram (Opción A, decidida en el diseño).

Presupuesto: 500 créditos/mes en the-odds-api ≈ 15/día, repartidos entre
TODOS los partidos confirmados del día (no solo los de IS alto), tomando
los de mayor IS primero hasta agotar el presupuesto diario.
"""
import logging
import requests

import config
import fetch_data

log = logging.getLogger(__name__)


def _buscar_cuotas_partido(favorito: str, rival: str) -> dict:
    """
    Busca en the-odds-api el partido por nombres de equipo (fuzzy simple).
    Devuelve {} si no lo encuentra o si hay error (no se detiene el flujo).
    """
    if not config.ODDS_API_KEY:
        log.warning("ODDS_API_KEY no configurada, se omite validación de mercado")
        return {}

    try:
        resp = requests.get(
            f"{config.ODDS_API_BASE_URL}/sports/soccer/odds",
            params={
                "apiKey": config.ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
            timeout=15,
        )
        resp.raise_for_status()
        eventos = resp.json()
    except Exception as e:
        log.warning("Fallo consultando the-odds-api: %s", e)
        return {}

    favorito_low, rival_low = favorito.lower(), rival.lower()
    for evento in eventos:
        equipos = [evento.get("home_team", "").lower(), evento.get("away_team", "").lower()]
        if any(favorito_low in eq or eq in favorito_low for eq in equipos) and \
           any(rival_low in eq or eq in rival_low for eq in equipos):
            return evento
    return {}


def _probabilidad_implicita_favorito(evento: dict, favorito: str) -> float:
    """Convierte la cuota decimal más común entre casas en probabilidad implícita."""
    if not evento or not evento.get("bookmakers"):
        return None

    cuotas_favorito = []
    for casa in evento["bookmakers"]:
        for mercado in casa.get("markets", []):
            if mercado["key"] != "h2h":
                continue
            for outcome in mercado["outcomes"]:
                if favorito.lower() in outcome["name"].lower() or outcome["name"].lower() in favorito.lower():
                    cuotas_favorito.append(outcome["price"])

    if not cuotas_favorito:
        return None

    cuota_promedio = sum(cuotas_favorito) / len(cuotas_favorito)
    return 1 / cuota_promedio   # probabilidad implícita


def validar_top_partidos_del_dia(vigilancia: list) -> list:
    """
    Toma los partidos de vigilancia_HOY.json, ordena por IS, valida contra
    el mercado hasta agotar el presupuesto diario, y devuelve la lista
    con los campos "validado_mercado" / "discrepancia_mercado" agregados.
    """
    ordenados = sorted(vigilancia, key=lambda p: p.get("indice_superioridad", 0), reverse=True)
    presupuesto_usado = 0

    for partido in ordenados:
        if presupuesto_usado >= config.ODDS_API_PRESUPUESTO_DIARIO:
            break

        evento = _buscar_cuotas_partido(partido["favorito"], partido["rival"])
        presupuesto_usado += 1  # se cuenta el intento, encuentre o no el partido

        if not evento:
            continue

        prob_implicita = _probabilidad_implicita_favorito(evento, partido["favorito"])
        if prob_implicita is None:
            continue

        # probabilidad "nuestra" aproximada a partir del IS (0-100 -> 0.5-1.0 aprox)
        prob_nuestra = 0.5 + min(partido.get("indice_superioridad", 0), 50) / 100

        diferencia = abs(prob_nuestra - prob_implicita)
        if diferencia <= config.ODDS_API_DIFERENCIA_DISCREPANCIA:
            partido["validado_mercado"] = True
        else:
            partido["discrepancia_mercado"] = True

        partido["prob_implicita_mercado"] = round(prob_implicita, 3)

    log.info("Fase 2.5: %d/%d créditos de the-odds-api usados hoy", presupuesto_usado, config.ODDS_API_PRESUPUESTO_DIARIO)
    return vigilancia
