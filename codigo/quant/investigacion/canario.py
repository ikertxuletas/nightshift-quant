"""Canario: un documento fijo recorre lector, formalizador, critico y validacion; si falla, se ha roto algo nuestro."""
import json
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from quant import datos, familias, indicadores
from quant.demo import config as demo_config, diario, pasada, papel, seleccion
from quant.investigacion import agentes, claude_cli, investigar

PASOS = ("lector", "formalizador", "critico", "validacion", "papel")

_ARRIBA = {">", ">=", "cruza_arriba"}
_ABAJO = {"<", "<=", "cruza_abajo"}
_DIRECCION = {("entrada", "largo"): _ARRIBA, ("salida", "largo"): _ABAJO,
              ("entrada", "corto"): _ABAJO, ("salida", "corto"): _ARRIBA}
_INVERSA = {">": "<", "<": ">", ">=": "<=", "<=": ">=", "cruza_arriba": "cruza_abajo", "cruza_abajo": "cruza_arriba"}


class _Fallo(Exception):
    pass


def _exigir(condicion, motivo):
    if not condicion:
        raise _Fallo(motivo)


def _rama(ficha, ruta):
    nodo = ficha
    for clave in ruta.split("."):
        nodo = (nodo or {}).get(clave) if isinstance(nodo, dict) else None
    return nodo


def _hojas(cond):
    """Recorre y/o/no del arbol de condiciones hasta las comparaciones de hoja (op, [a, b])."""
    if not isinstance(cond, dict):
        return
    if "y" in cond or "o" in cond:
        for hijo in cond.get("y", cond.get("o")):
            yield from _hojas(hijo)
        return
    if "no" in cond:
        yield from _hojas(cond["no"])
        return
    for op, par in cond.items():
        if isinstance(par, (list, tuple)) and len(par) == 2:
            yield op, par


def _token(operando):
    """Compara indicadores por su forma analizada, no por texto: SMA(200) == SMA( 200 ) == SMA(200.0)."""
    if not isinstance(operando, str):
        return None
    try:
        return indicadores.analizar(operando)
    except indicadores.ErrorIndicador:
        return None


def _es_precio(operando):
    return isinstance(operando, str) and operando.strip().lower() == "close"


def _usa_indicador(cond, indicador_esperado, permitidos):
    """El indicador puede ir como primer operando: '{"<": [SMA(200), close]}' equivale a 'close > SMA(200)'.
    El otro operando tiene que ser el precio: comparar el indicador contra si mismo u otro indicador no cuenta."""
    esperado = _token(indicador_esperado)
    if esperado is None:
        return False
    for op, (a, b) in _hojas(cond):
        if _token(a) == esperado and _es_precio(b):
            op_efectivo = _INVERSA.get(op, op)
        elif _token(b) == esperado and _es_precio(a):
            op_efectivo = op
        else:
            continue
        if op_efectivo in permitidos:
            return True
    return False


def mercado_contiene(mercado, esperado):
    """esperado puede ser una cadena o una lista de cadenas; pasa si cualquiera esta en mercado."""
    valores = [esperado] if isinstance(esperado, str) else esperado
    mercado = mercado or []
    return any(valor in mercado for valor in valores)


def _comprobar_extracto(extracto, esperado):
    _exigir(extracto.get("operable") == esperado["operable"], f"operable={extracto.get('operable')!r}")
    _exigir(extracto.get("tipo") in esperado["tipo"], f"tipo={extracto.get('tipo')!r}")
    _exigir(mercado_contiene(extracto.get("mercado"), esperado["mercado_contiene"]),
            f"mercado={extracto.get('mercado')!r}")
    _exigir(extracto.get("plazo") == esperado["plazo"], f"plazo={extracto.get('plazo')!r}")


def _comprobar_ficha(ficha, esperado):
    _exigir(ficha.get("forma") == esperado["forma"], f"forma={ficha.get('forma')!r}")
    uni = ficha.get("universo") or {}
    _exigir(uni.get("instrumentos") == esperado["instrumentos"], f"instrumentos={uni.get('instrumentos')!r}")
    _exigir(uni.get("plazo") == esperado["plazo"], f"plazo={uni.get('plazo')!r}")
    for ruta in esperado["lados_con_indicador"]:
        seccion, lado = ruta.split(".")
        permitidos = _DIRECCION.get((seccion, lado))
        cond = _rama(ficha, ruta)
        _exigir(permitidos is not None and _usa_indicador(cond, esperado["indicador"], permitidos),
                f"{ruta} no usa {esperado['indicador']} en la direccion esperada")
    if esperado.get("sin_corto"):
        _exigir(not _rama(ficha, "entrada.corto"), "la ficha opera en corto")


def validar_real(ficha, raiz):
    """La misma validacion que hace investigar, en memoria y sin catalogo."""
    return investigar.validar_ficha(ficha, raiz)


def _paso_papel(raiz, papel_inyectado):
    raiz = Path(raiz)
    barras = (papel_inyectado or {}).get("barras") or (lambda inst, tf: datos.cargar(inst, tf, raiz / "datos"))
    costes = (papel_inyectado or {}).get("costes") or pasada._default_costes_of(raiz)
    cfg = demo_config.cargar_de(raiz)
    ahora = datetime.now(timezone.utc)
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        diario.ensure_schema(con)
        ficha = familias.to_ficha(familias.Combo(seleccion.CONTROL, {}, ("US500",), "D1", "sin_filtro", "control"))
        con.execute("INSERT INTO demo_strategies(ficha_json,instrument,timeframe,broker,label,status,capital,added)"
                    " VALUES(?,?,?,?,?,'active',?,?)",
                    (json.dumps(ficha), "US500", "D1", "papel", "control", cfg["capital"], ahora.isoformat()))
        broker = papel.PaperBroker(con, costes, lambda inst: barras(inst, "H1"))
        with tempfile.TemporaryDirectory() as sin_parar:
            salida = pasada.run_pass(con, sin_parar, broker, ahora, cfg, bars_of=barras, costes_of=costes,
                                     update=lambda insts: None)
        _exigir(salida["opened"] == 1 and not salida["skipped"],
                f"sin objetivo calculado: abiertas={salida['opened']} omitidas={salida['skipped']}")
    finally:
        con.close()


class _SinTiempo(Exception):
    pass


def _operaciones(detalle):
    metricas = detalle.get("metricas")
    total = metricas.get("total") if isinstance(metricas, dict) else None
    return total.get("operaciones") if isinstance(total, dict) else None


def ejecutar(raiz, llamar=claude_cli.chat, validar=None, carpeta=None, raiz_skills=None, config=None, hasta=None,
             reloj=time.monotonic, papel=None):
    inicio = time.monotonic()
    pasos = {p: "no ejecutado" for p in PASOS}
    paso = "lector"

    def _hay_tiempo():
        if hasta is not None and reloj() >= hasta:
            raise _SinTiempo()

    try:
        _hay_tiempo()
        carpeta = Path(carpeta or Path(raiz) / "canario")
        esperado = json.loads((carpeta / "esperado.json").read_text(encoding="utf-8"))
        texto = (carpeta / "documento.md").read_text(encoding="utf-8")

        extracto = agentes.leer(esperado["titulo"], esperado["fuente"], texto, config=config,
                                raiz_skills=raiz_skills, llamar=llamar)
        _comprobar_extracto(extracto, esperado["extracto"])
        pasos[paso] = "ok"

        paso = "formalizador"
        _hay_tiempo()
        fuente = {"url": esperado["url"], "cita": esperado["titulo"]}
        formal = agentes.formalizar(extracto, fuente, config=config, raiz_skills=raiz_skills, llamar=llamar)
        _exigir(formal.get("expresable"), f"no expresable: {formal.get('motivo')}")
        _comprobar_ficha(formal["ficha"], esperado["ficha"])
        pasos[paso] = "ok"

        paso = "critico"
        _hay_tiempo()
        critica = agentes.criticar(formal["ficha"], extracto, config=config, raiz_skills=raiz_skills, llamar=llamar)
        _exigir(critica["veredicto"] in esperado["critico"]["veredictos_aceptados"],
                f"veredicto={critica['veredicto']!r}: {'; '.join(map(str, critica.get('motivos') or []))[:200]}")
        pasos[paso] = "ok"

        paso = "validacion"
        _hay_tiempo()
        resultado = (validar or validar_real)(formal["ficha"], raiz)
        _exigir(resultado, "la validacion no devolvio nada")
        for instrumento, detalle in resultado.items():
            _exigir(detalle.get("veredicto") in esperado["validacion"]["veredictos_aceptados"],
                    f"{instrumento}: {detalle.get('veredicto')!r} {str(detalle.get('motivo', ''))[:120]}")
            operaciones = _operaciones(detalle)
            _exigir(isinstance(operaciones, int) and operaciones > 0, f"{instrumento}: sin operaciones")
        pasos[paso] = "ok"

        paso = "papel"
        _hay_tiempo()
        _paso_papel(raiz, papel)
        pasos[paso] = "ok"
    except _SinTiempo:
        return {"omitido": "sin tiempo", "pasos": pasos, "segundos": round(time.monotonic() - inicio, 1)}
    except Exception as e:
        motivo = str(e) if isinstance(e, _Fallo) else f"{type(e).__name__}: {e}"
        pasos[paso] = motivo
        return {"ok": False, "pasos": pasos, "segundos": round(time.monotonic() - inicio, 1),
                "fallo": f"canario: {paso}: {motivo}"}
    return {"ok": True, "pasos": pasos, "segundos": round(time.monotonic() - inicio, 1)}
