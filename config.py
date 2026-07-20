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

# ---------- Fase 1: Selección DIARIA (ya no semanal — ver seleccion_diaria.py) ----------
# El plan gratis de API-Football no permite consultar el calendario de días
# futuros, solo una ventana muy limitada — por eso la selección se hace
# el mismo día, no con una semana de anticipación.
UMBRAL_PUNTAJE_SELECCION = 55          # sobre 100, ver seleccion_diaria.py
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

# ---------- Elo propio (semilla ClubElo + reconstrucción para equipos ausentes) ----------
ELO_SEMILLA_NEUTRO = 1500
ELO_MIN_PARTIDOS_PARA_RECONSTRUIR = 3   # menos que esto = se usa semilla por liga, no reconstrucción
ELO_PARTIDOS_HISTORIAL_A_TRAER = 10     # /fixtures?team=X&last=10
ELO_K_FACTOR_PROVISIONAL = 40           # primeros partidos de un equipo nuevo en el sistema
ELO_K_FACTOR_NORMAL = 20                # una vez pasado el período provisional
ELO_PARTIDOS_PERIODO_PROVISIONAL = 10   # a partir de cuántos partidos propios pasa a K normal
ELO_VENTAJA_LOCAL = 60                  # puntos de Elo que se suman al local antes de calcular probabilidad

# ---------- Fase 2: Confirmación repartida ----------
UMBRAL_REVALIDACION_ELO = 15   # puntos de Elo que disparan una revalidación con /predictions

# Clasificación del Índice de Superioridad (IS)
IS_FAVORITO_MUY_CLARO = 25
IS_FAVORITO_FUERTE = 15
IS_FAVORITO_MODERADO = 8

# ---------- Fase 3: Vigilancia de marcador ----------
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

# ---------- Fase 4: LPI (rediseñado — sin minuto fijo, con momentum, sin xG) ----------
# Ya no hay MINUTO_MINIMO_PARA_CANDIDATO ni LPI_UMBRAL_ALERTA únicos.
# Ahora hay 4 ventanas, cada una con su propia lógica y umbral.

# Ventana temprana (primer tiempo): no depende de un minuto fijo, depende de
# que se repita presión sostenida en varios sondeos seguidos.
VENTANA_TEMPRANA_MINUTO_TOPE = 35          # techo: después de este minuto, ya no aplica esta ventana
MOMENTUM_SONDEOS_CONSECUTIVOS_REQUERIDOS = 2   # cuántos sondeos seguidos de presión alta hacen falta
MOMENTUM_UMBRAL_PRESION = 15               # umbral de "delta" de tiros+corners entre sondeos consecutivos
LPI_UMBRAL_VENTANA_TEMPRANA = 80           # más exigente, porque hay menos datos acumulados todavía

# Resto de ventanas, por minuto de partido
LPI_UMBRAL_NORMAL = 75          # minuto 35-75
LPI_UMBRAL_GOL_INMINENTE = 60   # minuto 75-85
LPI_UMBRAL_ULTIMA_OPORTUNIDAD = 50   # minuto 85+

LPI_UMBRAL_VIGILAR_CERCA = 45   # por debajo del umbral de la ventana, pero cerca — no alerta, solo prioriza sondeo

# Pesos base del LPI (sin xG — se reemplazó por momentum).
# Se normalizan dinámicamente si alguna variable no llega con dato ese sondeo.
PESOS_LPI = {
    "posesion": 10,
    "tiros_totales": 20,
    "tiros_puerta": 25,
    "corners": 15,
    "ataques_peligrosos": 10,
    "expulsion_rival": 10,
    "momentum": 10,   # nuevo: reemplaza el hueco que dejó xG
}

# ---------- Fase 2.5: Validación cruzada con el mercado (the-odds-api, gratis) ----------
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
ODDS_API_PRESUPUESTO_DIARIO = 15   # de los 500 créditos/mes (~16/día), con margen de seguridad
ODDS_API_DIFERENCIA_DISCREPANCIA = 0.15   # 15% de diferencia en probabilidad implícita = discrepancia
