"""
Configuración central del sistema de detección de favoritos.
Todos los valores ajustables del diseño viven aquí, no repartidos en el código.
"""
import os

# ---------- Credenciales (se leen de variables de entorno / GitHub Secrets) ----------
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "")
API_FOOTBALL_HOST = "v3.football.api-sports.io"
API_FOOTBALL_BASE_URL = f"https://{API_FOOTBALL_HOST}"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# Canal/thread separado para avisos técnicos (equipos sin cruce, fallos de API).
# Si no tienes uno separado, usa el mismo TELEGRAM_CHAT_ID.
TELEGRAM_CHAT_ID_TECNICO = os.environ.get("TELEGRAM_CHAT_ID_TECNICO", TELEGRAM_CHAT_ID)

CLUBELO_BASE_URL = "http://api.clubelo.com"

# ---------- Rutas de datos ----------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ---------- Fase 1: Selección semanal ----------
DIAS_A_ESCANEAR = 7
UMBRAL_PUNTAJE_SELECCION = 55          # sobre 100, ver selection.py
DIFERENCIA_ELO_MINIMA = 50
LIGAS_EXCLUIDAS_PALABRAS_CLAVE = [
    "friendlies", "amistoso", "u17", "u18", "u19", "u20", "u21", "u23",
    "reserve", "reserves", "youth", "women",  # ajusta según tu criterio
]

# Pesos del puntaje de selección (Paso 1.5)
PESO_ELO = 40
PESO_LOCALIA = 15
PESO_PROB_CLUBELO = 30
PESO_LIGA = 15

# ---------- Fase 2: Confirmación repartida ----------
UMBRAL_REVALIDACION_ELO = 15   # puntos de Elo que disparan una revalidación con /predictions

# Clasificación del Índice de Superioridad (IS)
IS_FAVORITO_MUY_CLARO = 25
IS_FAVORITO_FUERTE = 15
IS_FAVORITO_MODERADO = 8

# ---------- Fase 3: Vigilancia de marcador ----------
MINUTO_MINIMO_PARA_CANDIDATO = 25
MAX_HORAS_POR_BLOQUE = 5.5   # dejamos margen bajo el límite real de 6h de GitHub Actions

# Intervalo adaptativo de sondeo de ESTADÍSTICAS (Fase 4), en segundos
def intervalo_sondeo_segundos(n_candidatos_calientes: int) -> int:
    if n_candidatos_calientes <= 8:
        return 5 * 60
    elif n_candidatos_calientes <= 20:
        return 10 * 60
    else:
        return 15 * 60

# Intervalo del loop de MARCADOR (live=all), independiente del de estadísticas
INTERVALO_SONDEO_MARCADOR_SEGUNDOS = 6 * 60

FALLOS_CONSECUTIVOS_PARA_AVISAR = 3

# ---------- Fase 4: LPI ----------
LPI_UMBRAL_ALERTA = 75
LPI_UMBRAL_VIGILAR_CERCA = 60
