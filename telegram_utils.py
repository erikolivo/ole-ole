"""
Envio de mensajes a Telegram. Alertas de oportunidad separadas de avisos
tecnicos. El mensaje de alerta ahora distingue la ventana (temprana/normal/
gol inminente/ultima oportunidad), el marcador (empate/perdiendo/ganando)
y si fue validado o discrepa con el mercado (Fase 2.5).
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


_ETIQUETA_VENTANA = {
    "temprana": ("🔥", "Dominio sostenido del primer tiempo"),
    "normal": ("⚡", "Presion alta"),
    "gol_inminente": ("⏰", "Gol inminente"),
    "ultima_oportunidad": ("🚨", "Ultima oportunidad"),
}


def _etiqueta_marcador(goles_favorito: int, goles_rival: int) -> str:
    if goles_favorito == goles_rival:
        return "🔄 Posible remontada"
    elif goles_favorito < goles_rival:
        return "🆘 Puede empatar/voltear"
    else:
        return "📈 Puede ampliar la ventaja"


def enviar_alerta_oportunidad(fixture_id: str, info: dict, lpi: int, ventana: str) -> None:
    marcador = info.get("ultimo_marcador_visto", "0-0")
    minuto = info.get("ultimo_minuto_visto", 0)
    goles_favorito, goles_rival = (int(x) for x in marcador.split("-"))

    emoji_ventana, texto_ventana = _ETIQUETA_VENTANA[ventana]
    etiqueta_marcador = _etiqueta_marcador(goles_favorito, goles_rival)

    simbolo_mercado = ""
    if info.get("validado_mercado"):
        simbolo_mercado = " ⭐"
    elif info.get("discrepancia_mercado"):
        simbolo_mercado = " ⚠️"

    mensaje = (
        f"{emoji_ventana} {texto_ventana}{simbolo_mercado}\n"
        f"{info['favorito']} {marcador} {info['rival']}\n"
        f"Minuto: {minuto}'\n"
        f"{etiqueta_marcador}\n\n"
        f"📊 LPI: {lpi}/100\n"
        f"IS pre-partido: {info['indice_superioridad']}\n"
        f"(fixture_id {fixture_id})"
    )
    _enviar(config.TELEGRAM_CHAT_ID, mensaje)
    log.info("Alerta '%s' enviada para fixture %s (LPI %d)", ventana, fixture_id, lpi)
