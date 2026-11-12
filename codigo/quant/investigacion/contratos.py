"""Formato declarado del parte de la noche y de la revision del supervisor; unico lector de esos ficheros."""
import json
import re
from datetime import datetime
from pathlib import Path

ETAPAS = ("precios", "investigar", "canario", "demo", "relator", "mentor", "copia", "laboratorio")
ESTADOS_REVISION = ("ok", "aviso", "parada", "sin revision")
LIMITE_REVISION_HORAS = 2
LIMITE_NOCHE = (4, 30)
MARGEN_EXAMEN_MINUTOS = 25
HORA_VIGILANTE = (7, 30)

_FECHA = re.compile(r"^\d{8}$")
_RUTA_USUARIO = re.compile(r"[A-Za-z]:\\Users\\[^\\\"/]+")
MAX_TEXTO_REAL = 80
FECHA_SEMILLAS = "20260917"


def hay_fallo(resultado):
    """Una etapa puede fallar por dentro y devolver el fallo en vez de lanzarlo; 'omitido' no es fallo."""
    if not isinstance(resultado, dict):
        return None
    detalle = resultado.get("error") or resultado.get("fallo")
    if detalle:
        return str(detalle)
    codigo = resultado.get("codigo")
    if codigo not in (0, None):
        return f"codigo {codigo}"
    return None


def _es(valor, tipo):
    if tipo is int:
        return isinstance(valor, int) and not isinstance(valor, bool)
    return isinstance(valor, tipo)


def _exige(datos, clave, tipo, errores, ruta="", nulo=False):
    nombre = f"{ruta}{clave}"
    if clave not in datos:
        errores.append(f"{nombre}: falta")
        return None
    valor = datos[clave]
    if valor is None and nulo:
        return None
    if not _es(valor, tipo):
        errores.append(f"{nombre}: se esperaba {tipo.__name__}, llego {type(valor).__name__}")
        return None
    return valor


def _con_zona(texto):
    try:
        return datetime.fromisoformat(texto).tzinfo is not None
    except ValueError:
        return False


def validar_parte(datos):
    if not isinstance(datos, dict):
        return ["parte: no es un objeto"]
    errores = []
    fecha = _exige(datos, "fecha", str, errores)
    if fecha is not None and not _FECHA.match(fecha):
        errores.append("fecha: debe ser AAAAMMDD")
    _exige(datos, "inicio", str, errores)
    desde = _exige(datos, "desde", str, errores)
    if desde is not None and not _con_zona(desde):
        errores.append("desde: debe ser una fecha ISO con zona (UTC)")
    _exige(datos, "fin_previsto", str, errores)
    _exige(datos, "fin_real", str, errores, nulo=True)
    _exige(datos, "equipo", str, errores)
    _exige(datos, "corte", bool, errores)
    n = _exige(datos, "errores", int, errores)
    if n is not None and n < 0:
        errores.append("errores: no puede ser negativo")
    _exige(datos, "catalogo", dict, errores)
    if "memoria" in datos and not isinstance(datos["memoria"], list):
        errores.append(f"memoria: se esperaba list, llego {type(datos['memoria']).__name__}")
    etapas = _exige(datos, "etapas", dict, errores)
    for nombre, entrada in (etapas or {}).items():
        ruta = f"etapas.{nombre}"
        if nombre not in ETAPAS:
            errores.append(f"{ruta}: etapa desconocida")
            continue
        if not isinstance(entrada, dict):
            errores.append(f"{ruta}: no es un objeto")
            continue
        _exige(entrada, "inicio", int, errores, ruta + ".")
        _exige(entrada, "segundos", int, errores, ruta + ".")
        _exige(entrada, "resultado", dict, errores, ruta + ".")
        if "ocupado" in entrada and not isinstance(entrada["ocupado"], str):
            errores.append(f"{ruta}.ocupado: se esperaba str")
    return errores


def validar_revision(datos):
    if not isinstance(datos, dict):
        return ["revision: no es un objeto"]
    errores = []
    _exige(datos, "fecha", str, errores)
    estado = _exige(datos, "estado", str, errores)
    if estado is not None and estado not in ESTADOS_REVISION:
        errores.append(f"estado: debe ser uno de {list(ESTADOS_REVISION)}")
    for clave in ("resumen", "correo", "criterios", "error"):
        _exige(datos, clave, str, errores)
    _exige(datos, "paquete_bytes", int, errores)
    notas = _exige(datos, "notas", dict, errores)
    for agente, nota in (notas or {}).items():
        if not isinstance(nota, dict):
            errores.append(f"notas.{agente}: no es un objeto")
    acciones = _exige(datos, "acciones", list, errores)
    for i, accion in enumerate(acciones or []):
        if not isinstance(accion, dict):
            errores.append(f"acciones[{i}]: no es un objeto")
    return errores


def _leer(ruta, nombre, validar):
    ruta = Path(ruta)
    if not ruta.exists():
        return None, [f"{nombre}: no existe {ruta.name}"]
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"{nombre}: no se puede leer: {type(e).__name__}: {e}"]
    if not isinstance(datos, dict):
        return None, [f"{nombre}: no es un objeto"]
    return datos, validar(datos)


def leer_parte(raiz, fecha):
    return _leer(Path(raiz) / "informes" / f"parte_{fecha}.json", "parte", validar_parte)


def leer_revision(raiz, fecha):
    return _leer(Path(raiz) / "supervisor" / f"revision_{fecha}.json", "revision", validar_revision)


def existe_parte(raiz, fecha):
    return (Path(raiz) / "informes" / f"parte_{fecha}.json").exists()


def sanear(datos):
    """Copia para git: sin textos largos de documentos ni rutas con el nombre de usuario."""
    if isinstance(datos, dict):
        return {clave: sanear(valor) for clave, valor in datos.items()}
    if isinstance(datos, list):
        return [sanear(valor) for valor in datos]
    if isinstance(datos, str):
        texto = _RUTA_USUARIO.sub("~", datos)
        return texto if len(texto) <= MAX_TEXTO_REAL else texto[:MAX_TEXTO_REAL] + "…"
    return datos


def _protegida(ruta):
    """Las semillas (20260917) y las copias migradas a mano no se podan: son la base de la suite."""
    if ruta.stem.endswith(f"_{FECHA_SEMILLAS}"):
        return True
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(datos, dict) and datos.get("migrado") is True


def guardar_real(raiz, tipo, datos, conservar=10):
    if tipo not in ("parte", "revision"):
        return None
    fecha = datos.get("fecha") if isinstance(datos, dict) else None
    if not isinstance(fecha, str) or not _FECHA.match(fecha):
        return None
    try:
        carpeta = Path(raiz) / "codigo" / "tests" / "reales"
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"{tipo}_{fecha}.json"
        destino.write_text(json.dumps(sanear(datos), indent=1, ensure_ascii=False), encoding="utf-8")
        podables = [p for p in sorted(carpeta.glob(f"{tipo}_*.json")) if not _protegida(p)]
        for viejo in podables[:-conservar]:
            viejo.unlink()
        return destino
    except Exception:
        return None
