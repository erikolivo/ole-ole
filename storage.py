"""
Histórico en SQLite: cada partido vigilado queda registrado, se haya
alertado o no, para poder recalibrar pesos del IS y del LPI con datos reales.
"""
import sqlite3
import os
from datetime import datetime

import config

DB_PATH = os.path.join(config.DATA_DIR, "historico.sqlite")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS partidos (
    fixture_id INTEGER PRIMARY KEY,
    fecha TEXT,
    favorito TEXT,
    rival TEXT,
    elo_diff REAL,
    indice_superioridad REAL,
    lpi_max INTEGER,
    minuto_lpi_max INTEGER,
    alertado INTEGER,
    favorito_marco_15min_despues INTEGER,
    resultado_final TEXT,
    fallos_api_registrados INTEGER DEFAULT 0
);
"""


def _conectar():
    con = sqlite3.connect(DB_PATH)
    con.execute(_ESQUEMA)
    return con


def guardar_partido(registro: dict) -> None:
    con = _conectar()
    con.execute(
        """
        INSERT OR REPLACE INTO partidos
        (fixture_id, fecha, favorito, rival, elo_diff, indice_superioridad,
         lpi_max, minuto_lpi_max, alertado, favorito_marco_15min_despues,
         resultado_final, fallos_api_registrados)
        VALUES (:fixture_id, :fecha, :favorito, :rival, :elo_diff, :indice_superioridad,
                :lpi_max, :minuto_lpi_max, :alertado, :favorito_marco_15min_despues,
                :resultado_final, :fallos_api_registrados)
        """,
        registro,
    )
    con.commit()
    con.close()


def cerrar_dia(fecha: str, estado_vivo: dict) -> None:
    """Se corre al final del bloque del día: vuelca estado_vivo al histórico permanente."""
    con = _conectar()
    for fixture_id, info in estado_vivo.items():
        con.execute(
            """
            INSERT OR REPLACE INTO partidos
            (fixture_id, fecha, favorito, rival, indice_superioridad, lpi_max,
             minuto_lpi_max, alertado, fallos_api_registrados)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(fixture_id), fecha, info.get("favorito"), info.get("rival"),
                info.get("indice_superioridad"), info.get("lpi_actual", 0),
                info.get("ultimo_minuto_visto", 0), int(info.get("alertado", False)),
                info.get("fallos_consecutivos", 0),
            ),
        )
    con.commit()
    con.close()
