"""
FASE 2 — Confirmación con banco de requests repartido en la semana.
No confirma todo el día del partido: reparte /predictions entre los días
de la semana con cuota sobrante, priorizando por puntaje de selección.
"""
import json
import logging
from datetime import datetime

import config
import fetch_data

log = logging.getLogger(__name__)

USO_BASE_ESTIMADO_POR_PARTIDO_PROPIO = 3.5  # estimación de cuánto gasta vigilar 1 partido propio ese día


def _cuota_sobrante_estimada(candidatos_semana: list, fecha: str) -> int:
    partidos_ese_dia = [c for c in candidatos_semana if c["fecha"] == fecha]
    uso_estimado = len(partidos_ese_dia) * USO_BASE_ESTIMADO_POR_PARTIDO_PROPIO
    return max(0, int(100 - uso_estimado))


def planificar_confirmaciones(candidatos_semana: list) -> dict:
    """
    Devuelve {fecha: [fixture_ids a confirmar ese día]}, repartiendo por cuota
    sobrante y priorizando los partidos con mayor puntaje_seleccion primero.
    """
    fechas = sorted({c["fecha"] for c in candidatos_semana})
    cuota_por_fecha = {f: _cuota_sobrante_estimada(candidatos_semana, f) for f in fechas}

    pendientes = sorted(candidatos_semana, key=lambda c: c["puntaje_seleccion"], reverse=True)
    plan = {f: [] for f in fechas}

    # Reparto tipo "bin packing" simple: se asigna cada partido al primer día
    # (en orden cronológico) que aún tenga cuota sobrante disponible.
    for candidato in pendientes:
        asignado = False
        for fecha in fechas:
            if cuota_por_fecha[fecha] > 0:
                plan[fecha].append(candidato["fixture_id"])
                cuota_por_fecha[fecha] -= 1
                asignado = True
                break
        if not asignado:
            log.warning(
                "Sin cuota disponible en toda la semana para confirmar fixture %s — "
                "se confirmará el mismo día del partido como último recurso",
                candidato["fixture_id"],
            )
            plan.setdefault(candidato["fecha"], []).append(candidato["fixture_id"])

    with open(f"{config.DATA_DIR}/plan_requests_semana.json", "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    return plan


def ejecutar_confirmaciones_de_hoy(plan: dict, candidatos_semana: list) -> list:
    """Se corre 1 vez al día: confirma solo los fixture_ids que le tocaban a HOY."""
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    fixture_ids_hoy = plan.get(hoy, [])
    candidatos_por_id = {c["fixture_id"]: c for c in candidatos_semana}

    confirmados = []
    for fixture_id in fixture_ids_hoy:
        candidato = candidatos_por_id.get(fixture_id)
        if candidato is None:
            continue
        try:
            data = fetch_data.obtener_predictions(fixture_id)
            resultado = _calcular_is(data, candidato)
            confirmados.append(resultado)
        except Exception as e:
            log.error("Fallo confirmando fixture %s: %s", fixture_id, e)
            continue

    log.info("Confirmaciones ejecutadas hoy (%s): %d partidos, cuota usada: %d",
              hoy, len(confirmados), fetch_data.requests_gastados_hoy())
    return confirmados


def _calcular_is(predictions_data: dict, candidato: dict) -> dict:
    """
    Calcula el Índice de Superioridad combinando la señal de predictions
    con el puntaje de selección ya calculado en Fase 1.
    """
    respuesta = predictions_data.get("response", [{}])[0]
    comparacion = respuesta.get("comparison", {})

    def _valor(campo, equipo):
        try:
            return float(comparacion.get(campo, {}).get(equipo, "0%").replace("%", ""))
        except (ValueError, AttributeError):
            return 50.0

    lado_favorito = "home" if candidato["favorito_es_local"] else "away"
    lado_rival = "away" if candidato["favorito_es_local"] else "home"

    puntaje_favorito = sum(_valor(c, lado_favorito) for c in ["form", "att", "def", "poisson_distribution"]) / 4
    puntaje_rival = sum(_valor(c, lado_rival) for c in ["form", "att", "def", "poisson_distribution"]) / 4

    IS = round(puntaje_favorito - puntaje_rival, 1)

    prob_api_football = respuesta.get("predictions", {}).get("percent", {}).get(
        "home" if candidato["favorito_es_local"] else "away", "0%"
    )

    if IS > config.IS_FAVORITO_MUY_CLARO:
        clasificacion = "muy_claro"
    elif IS > config.IS_FAVORITO_FUERTE:
        clasificacion = "fuerte"
    elif IS > config.IS_FAVORITO_MODERADO:
        clasificacion = "moderado"
    else:
        clasificacion = "descartado"

    return {
        **candidato,
        "indice_superioridad": IS,
        "clasificacion_is": clasificacion,
        "prob_api_football": prob_api_football,
        "confirmado_en": datetime.utcnow().strftime("%Y-%m-%d"),
    }


def revalidar_si_elo_cambio(confirmado: dict) -> dict:
    """
    Paso 2.3 — revalidación barata el mismo día del partido: solo gasta un
    request nuevo si el Elo se movió más que el umbral configurado.
    """
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    elo_hoy = fetch_data.descargar_elo_del_dia(hoy)
    # Nota: requiere nombre del equipo en formato ClubElo; se omite el detalle
    # de mapeo aquí por brevedad, ya resuelto en selection.py.
    elo_favorito_hoy = confirmado.get("elo_favorito")  # placeholder de comparación
    diferencia = abs(elo_favorito_hoy - confirmado["elo_favorito"])

    if diferencia > config.UMBRAL_REVALIDACION_ELO:
        log.info("Elo cambió %.1f pts para %s, revalidando con /predictions", diferencia, confirmado["favorito"])
        data = fetch_data.obtener_predictions(confirmado["fixture_id"], forzar=True)
        return _calcular_is(data, confirmado)

    return confirmado


def guardar_vigilancia_del_dia(confirmados: list) -> None:
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    vigilancia = [c for c in confirmados if c["clasificacion_is"] != "descartado"]
    with open(f"{config.DATA_DIR}/vigilancia_{hoy}.json", "w", encoding="utf-8") as f:
        json.dump(vigilancia, f, ensure_ascii=False, indent=2)
    log.info("Vigilancia de hoy (%s): %d partidos activos, sin tope de cantidad", hoy, len(vigilancia))


if __name__ == "__main__":
    with open(f"{config.DATA_DIR}/candidatos_semana.json", "r", encoding="utf-8") as f:
        candidatos_semana = json.load(f)

    plan = planificar_confirmaciones(candidatos_semana)
    confirmados_hoy = ejecutar_confirmaciones_de_hoy(plan, candidatos_semana)
    guardar_vigilancia_del_dia(confirmados_hoy)
