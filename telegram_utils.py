"""
Envío de mensajes a Telegram. Se separan las alertas de oportunidad (canal
principal) de los avisos técnicos (equipos sin cruce, fallos de API repetidos)
para no mezclarlos.
"""
import logging
import requests

import config

log = logging.getLogger(__name__)


def _enviar(chat_id: str, texto: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        log.warning("Telegram no configurado, mensaje no enviado:\n%s", texto)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": texto}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        log.error("Fallo enviando mensaje a Telegram: %s", e)


def enviar_aviso_tecnico(mensaje: str) -> None:
    _enviar(config.TELEGRAM_CHAT_ID_TECNICO, mensaje)


def enviar_alerta_oportunidad(fixture_id: str, info: dict, lpi: int, stats_data: dict) -> None:
    marcador = info.get("ultimo_marcador_visto", "0-0")
    minuto = info.get("ultimo_minuto_visto", 0)

    mensaje = (
        f"⚠️ Oportunidad detectada\n"
        f"{info['favorito']} {marcador} {info['rival']}\n"
        f"Minuto: {minuto}'\n\n"
        f"📊 Dominio (LPI): {lpi}/100\n"
        f"IS pre-partido: {info['indice_superioridad']}\n"
        f"(fixture_id {fixture_id})"
    )
    _enviar(config.TELEGRAM_CHAT_ID, mensaje)
    log.info("Alerta enviada para fixture %s (LPI %d)", fixture_id, lpi)
