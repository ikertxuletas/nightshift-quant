import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from quant import rutas

ETAPAS = ("nuevo", "leido", "formalizado", "criticado", "validado", "no_expresable", "descartado", "error")
MAX_INTENTOS = 3

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
  id INTEGER PRIMARY KEY, fuente TEXT, url TEXT UNIQUE, titulo TEXT, fecha TEXT,
  hash TEXT UNIQUE, etapa TEXT, intentos INTEGER DEFAULT 0, error TEXT, creado TEXT, actualizado TEXT);
CREATE TABLE IF NOT EXISTS extractos (doc_id INTEGER PRIMARY KEY, json TEXT);
CREATE TABLE IF NOT EXISTS fichas (
  id INTEGER PRIMARY KEY, doc_id INTEGER, json TEXT, estado TEXT, motivo TEXT, creado TEXT);
CREATE TABLE IF NOT EXISTS resultados (
  id INTEGER PRIMARY KEY, ficha_id INTEGER, instrumento TEXT, veredicto TEXT, json TEXT, creado TEXT);
CREATE TABLE IF NOT EXISTS skills_cambios (
  id INTEGER PRIMARY KEY, agente TEXT, motivo TEXT, nota_antes REAL, nota_despues REAL,
  aceptado INTEGER, creado TEXT, origen TEXT);
CREATE TABLE IF NOT EXISTS relatos (resultado_id INTEGER PRIMARY KEY, texto TEXT, creado TEXT);
"""


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def abrir(ruta=None):
    ruta = Path(ruta or rutas.RAIZ / "catalogo.db")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_ESQUEMA)
    columnas = {fila[1] for fila in con.execute("PRAGMA table_info(skills_cambios)")}
    if "origen" not in columnas:
        try:
            con.execute("ALTER TABLE skills_cambios ADD COLUMN origen TEXT")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
    con.commit()
    return con


def anadir_documento(con, fuente, url, titulo, fecha, texto, raiz_textos):
    huella = hashlib.sha1(texto.encode("utf-8")).hexdigest()
    destino = Path(raiz_textos) / f"{huella}.txt"
    try:
        try:
            cursor = con.execute(
                "INSERT INTO documentos (fuente, url, titulo, fecha, hash, etapa, creado, actualizado)"
                " VALUES (?, ?, ?, ?, ?, 'nuevo', ?, ?)",
                (fuente, url, titulo, fecha, huella, _ahora(), _ahora()))
        except sqlite3.IntegrityError:
            con.rollback()
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return cursor.lastrowid


def texto(con, doc_id, raiz_textos):
    huella = con.execute("SELECT hash FROM documentos WHERE id = ?", (doc_id,)).fetchone()["hash"]
    return (Path(raiz_textos) / f"{huella}.txt").read_text(encoding="utf-8")


def pendientes(con, etapa, limite=None):
    sql = "SELECT * FROM documentos WHERE etapa = ? AND intentos < ? ORDER BY id"
    parametros = [etapa, MAX_INTENTOS]
    if limite is not None:
        sql += " LIMIT ?"
        parametros.append(limite)
    return con.execute(sql, parametros).fetchall()


def marcar(con, doc_id, etapa, error=None):
    if error:
        con.execute("UPDATE documentos SET etapa = ?, error = ?, intentos = intentos + 1, actualizado = ?"
                    " WHERE id = ?", (etapa, error, _ahora(), doc_id))
    else:
        con.execute("UPDATE documentos SET etapa = ?, error = NULL, actualizado = ? WHERE id = ?",
                    (etapa, _ahora(), doc_id))
    con.commit()


def agotar(con, doc_id):
    """Retira el documento sin tocar intentos ni error: ya ha gastado todos los intentos."""
    con.execute("UPDATE documentos SET etapa = 'error', actualizado = ? WHERE id = ?", (_ahora(), doc_id))
    con.commit()


def guardar_extracto(con, doc_id, extracto):
    con.execute("INSERT OR REPLACE INTO extractos (doc_id, json) VALUES (?, ?)",
                (doc_id, json.dumps(extracto, ensure_ascii=False)))
    con.commit()


def extracto(con, doc_id):
    fila = con.execute("SELECT json FROM extractos WHERE doc_id = ?", (doc_id,)).fetchone()
    return json.loads(fila["json"]) if fila else None


def guardar_ficha(con, doc_id, ficha, estado, motivo=""):
    cursor = con.execute("INSERT INTO fichas (doc_id, json, estado, motivo, creado) VALUES (?, ?, ?, ?, ?)",
                         (doc_id, json.dumps(ficha, ensure_ascii=False), estado, motivo, _ahora()))
    con.commit()
    return cursor.lastrowid


def fichas(con, estado=None):
    if estado:
        return con.execute("SELECT * FROM fichas WHERE estado = ? ORDER BY id", (estado,)).fetchall()
    return con.execute("SELECT * FROM fichas ORDER BY id").fetchall()


def guardar_resultado(con, ficha_id, instrumento, veredicto, detalle):
    con.execute("INSERT INTO resultados (ficha_id, instrumento, veredicto, json, creado) VALUES (?, ?, ?, ?, ?)",
                (ficha_id, instrumento, veredicto, json.dumps(detalle, ensure_ascii=False), _ahora()))
    con.commit()


def guardar_relato(con, resultado_id, texto):
    con.execute("INSERT OR REPLACE INTO relatos (resultado_id, texto, creado) VALUES (?, ?, ?)",
                (resultado_id, texto, _ahora()))
    con.commit()


def relato(con, resultado_id):
    fila = con.execute("SELECT texto FROM relatos WHERE resultado_id = ?", (resultado_id,)).fetchone()
    return fila["texto"] if fila else None


def resultados_sin_relato(con, veredictos=("pasa", "dudosa")):
    marcas = ",".join("?" * len(veredictos))
    return con.execute(
        f"SELECT r.id AS id, r.ficha_id AS ficha_id, r.instrumento AS instrumento, r.veredicto AS veredicto,"
        f" r.json AS json, f.json AS ficha_json FROM resultados r JOIN fichas f ON f.id = r.ficha_id"
        f" LEFT JOIN relatos l ON l.resultado_id = r.id WHERE l.resultado_id IS NULL AND r.veredicto IN ({marcas})"
        f" ORDER BY r.id", tuple(veredictos)).fetchall()


def registrar_cambio_skill(con, agente, motivo, nota_antes, nota_despues, aceptado, origen="mentor"):
    con.execute("INSERT INTO skills_cambios (agente, motivo, nota_antes, nota_despues, aceptado, creado, origen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (agente, motivo, nota_antes, nota_despues, int(aceptado), _ahora(), origen))
    con.commit()


def _cuenta(con, tabla, columna):
    return {f[columna]: f["n"] for f in con.execute(f"SELECT {columna}, COUNT(*) n FROM {tabla} GROUP BY {columna}")}


def resumen(con):
    return {"documentos": _cuenta(con, "documentos", "etapa"),
            "fichas": _cuenta(con, "fichas", "estado"),
            "resultados": _cuenta(con, "resultados", "veredicto")}
