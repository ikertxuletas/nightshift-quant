"""Agentes Lector, Formalizador y Critico: leen, formalizan y auditan fichas."""
import json
import time

from quant import ficha as mficha
from quant.investigacion import catalogo, claude_cli, especialistas, local, skills
from quant.investigacion import salida as msalida

LIMITE_TEXTO = 40000

PLAZOS_VALIDOS = {"M5", "M15", "H1", "H4", "D1", "W1", ""}
MERCADOS_VALIDOS = {"indice", "forex", "materia", "accion", "cripto"}
TIPOS_VALIDOS = {"tendencia", "reversion", "ruptura", "carry", "estacionalidad",
                  "momentum_transversal", "pares", "volatilidad", "otro"}


class ErrorAgente(RuntimeError):
    pass


MARCA_DESBORDE = "exceeds the available context size"
MAX_MITADES = 3


def recorte(texto, limite=LIMITE_TEXTO):
    if len(texto) <= limite:
        return texto
    inicio = int(limite * 0.7)
    fin = limite - inicio
    return texto[:inicio] + "\n[...recortado...]\n" + texto[-fin:]


def vallar(texto):
    """El contenido externo nunca puede cerrar la valla: se rompen los delimitadores que traiga dentro."""
    dentro = str(texto).replace("<<<DOCUMENTO", "<<DOCUMENTO").replace("DOCUMENTO>>>", "DOCUMENTO>>")
    return f"<<<DOCUMENTO\n{dentro}\nDOCUMENTO>>>"


def prompt_documento(titulo, fuente, texto):
    return f"Titulo: {titulo}\nFuente: {fuente}\n{vallar(texto)}"


def _es_uno_de(valor, validos):
    """El modelo puede devolver una lista o un dict donde va una cadena: no son hashables contra un set."""
    return isinstance(valor, str) and valor in validos


def validar_extracto(datos):
    errores = []
    obligatorias = ("operable", "tipo", "mercado", "plazo", "extracto", "prometido", "alarmas")
    faltantes = [c for c in obligatorias if c not in datos]
    if faltantes:
        errores.append(f"faltan claves: {', '.join(faltantes)}")
    operable = datos.get("operable")
    if operable not in (None, "si", "no", "incompleta"):
        errores.append("operable debe ser si, no o incompleta")
    if "tipo" in datos and not _es_uno_de(datos["tipo"], TIPOS_VALIDOS):
        errores.append(f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
    if "plazo" in datos and not _es_uno_de(datos["plazo"], PLAZOS_VALIDOS):
        errores.append(f"plazo debe ser uno de {sorted(PLAZOS_VALIDOS)}")
    if "mercado" in datos:
        mercado = datos["mercado"]
        if not isinstance(mercado, list) or any(not _es_uno_de(m, MERCADOS_VALIDOS) for m in mercado):
            errores.append(f"mercado debe ser una lista de {sorted(MERCADOS_VALIDOS)}")
        elif operable == "si" and not mercado:
            errores.append("mercado no puede estar vacio cuando operable es si")
    if operable == "si" and len(datos.get("extracto") or "") < 40:
        errores.append("extracto debe tener al menos 40 caracteres cuando operable es si")
    return errores


TEMPERATURA_DEFECTO = 0.1
MODELO_DEFECTO = "sonnet"
FORMATO_DEFECTO = "json"


def ajustes(agente, config=None):
    try:
        configurados = especialistas.agentes(config) if config is not None else especialistas.agentes()
    except FileNotFoundError:
        configurados = {}
    datos = configurados.get(agente) or {}
    cfg_formato = datos.get("formato", FORMATO_DEFECTO)
    return {"modelo": datos.get("modelo", MODELO_DEFECTO),
            "formato": None if cfg_formato == "texto" else cfg_formato,
            "opciones": {"temperature": datos.get("temperatura", TEMPERATURA_DEFECTO)}}


_ajustes = ajustes


def _leer_respuesta(respuesta):
    try:
        bruto = local.json_de(respuesta)
    except local.ErrorModelo as e:
        return None, [str(e)]
    datos, avisos, errores_forma = msalida.limpiar("lector", bruto)
    errores = errores_forma + validar_extracto(datos)
    if avisos and not errores:
        datos["avisos_salida"] = avisos
    return datos, errores


def _anotar_recorte(datos, limite):
    if limite < LIMITE_TEXTO:
        datos["avisos_salida"] = (datos.get("avisos_salida") or []) + [f"recortado_a: {limite}"]
    return datos


def leer(titulo, fuente, texto, config=None, raiz_skills=None, llamar=claude_cli.chat, modelo=None):
    sistema = skills.system("lector", raiz=raiz_skills)
    ajuste = _ajustes("lector", config)
    modelo_usado = modelo or ajuste["modelo"]
    limite = LIMITE_TEXTO
    prompt = prompt_documento(titulo, fuente, recorte(texto, limite))

    for mitades in range(MAX_MITADES + 1):
        try:
            respuesta = llamar(modelo_usado, sistema, prompt, formato=ajuste["formato"],
                               opciones=ajuste["opciones"])
            break
        except local.ErrorModelo as e:
            if MARCA_DESBORDE not in str(e) or mitades == MAX_MITADES:
                raise
            limite = min(limite, len(texto)) // 2
            prompt = prompt_documento(titulo, fuente, recorte(texto, limite))
    datos, errores = _leer_respuesta(respuesta)

    if not errores:
        return _anotar_recorte(datos, limite)

    prompt_reintento = prompt + f"\nTu respuesta anterior no vale por: {'; '.join(errores)}. Responde solo con el JSON pedido."
    respuesta = llamar(modelo_usado, sistema, prompt_reintento, formato=ajuste["formato"],
                       opciones=ajuste["opciones"])
    datos, errores = _leer_respuesta(respuesta)

    if errores:
        raise ErrorAgente(f"extracto invalido tras reintento: {'; '.join(errores)}")
    return _anotar_recorte(datos, limite)


FALLOS = (ErrorAgente, local.ErrorModelo, OSError)


def _clasificar(e):
    """Contenido = el modelo dio algo invalido tras el reintento; el resto (modelo caido, disco, etc) es infra."""
    return "contenido" if isinstance(e, ErrorAgente) else "infra"


def _marcar_fallo(con, doc_id, etapa, mensaje, resumen, clasificacion):
    """Tras MAX_INTENTOS el documento se retira: nadie vuelve a intentarlo."""
    catalogo.marcar(con, doc_id, etapa, error=mensaje)
    resumen["errores"] += 1
    resumen[f"errores_{clasificacion}"] += 1
    intentos = con.execute("SELECT intentos FROM documentos WHERE id = ?", (doc_id,)).fetchone()["intentos"]
    if intentos >= catalogo.MAX_INTENTOS:
        catalogo.agotar(con, doc_id)
        resumen["agotados"] += 1


def procesar_lectura(con, raiz, limite=None, llamar=claude_cli.chat, reloj=time.monotonic, hasta=None, antes=None):
    resumen = {"leidos": 0, "descartados": 0, "errores": 0, "errores_contenido": 0, "errores_infra": 0,
               "omitidos": 0, "agotados": 0}
    documentos = catalogo.pendientes(con, "nuevo")
    for i, doc in enumerate(documentos):
        if (limite is not None and i >= limite) or (hasta is not None and reloj() >= hasta) or \
                (antes is not None and antes()):
            resumen["omitidos"] += len(documentos) - i
            break
        try:
            texto = catalogo.texto(con, doc["id"], raiz)
            datos = leer(doc["titulo"], doc["fuente"], texto, llamar=llamar)
        except Exception as e:
            # Cualquier rareza del modelo (no solo FALLOS) se queda en su documento: la etapa sigue.
            _marcar_fallo(con, doc["id"], "nuevo", f"{type(e).__name__}: {e}", resumen, _clasificar(e))
            continue
        catalogo.guardar_extracto(con, doc["id"], datos)
        # Una incompleta con reglas citadas pasa: el Formalizador aproxima lo que falta y lo anota en supuestos.
        if datos["operable"] == "si" or (datos["operable"] == "incompleta" and len(datos.get("extracto") or "") >= 40):
            catalogo.marcar(con, doc["id"], "leido")
            resumen["leidos"] += 1
        else:
            catalogo.marcar(con, doc["id"], "descartado", error=datos.get("motivo", ""))
            resumen["descartados"] += 1
    return resumen


def _modelo_defecto(agente, config):
    return _ajustes(agente, config)["modelo"]


AVISOS_INTERNOS = ("avisos_salida", "avisos_formalizador")


def _para_prompt(extracto):
    """El modelo no ve la fontaneria interna de la puerta de salida (avisos): se queda en el catalogo."""
    if not any(clave in extracto for clave in AVISOS_INTERNOS):
        return extracto
    return {k: v for k, v in extracto.items() if k not in AVISOS_INTERNOS}


def _prompt_formalizador(extracto, motivos):
    partes = [f"Extracto:\n{vallar(json.dumps(_para_prompt(extracto), ensure_ascii=False))}"]
    if motivos:
        partes.append("El critico ha devuelto la ficha por:\n" + "\n".join(motivos))
    return "\n\n".join(partes)


def _intentar_formalizar(modelo, sistema, prompt, llamar, fuente, ajuste):
    respuesta = llamar(modelo, sistema, prompt, formato=ajuste["formato"], opciones=ajuste["opciones"])
    try:
        bruto = local.json_de(respuesta)
    except local.ErrorModelo as e:
        raise ErrorAgente(f"formalizador: respuesta ilegible: {e}") from e
    datos, avisos, errores_forma = msalida.limpiar("formalizador", bruto)
    if errores_forma:
        return None, errores_forma
    if "expresable" not in datos:
        return None, ["falta la clave expresable"]
    # El esquema de la ficha no admite claves extra: los avisos viajan junto a la ficha, no dentro.
    extra = {"avisos_salida": avisos} if avisos else {}
    if not datos["expresable"]:
        return {"expresable": False, "motivo": datos.get("motivo", ""), "ficha": None, **extra}, []
    ficha_datos = dict(datos.get("ficha") or {})
    ficha_datos["fuente"] = fuente
    ficha_datos["estado"] = "borrador"
    try:
        errores_ficha = mficha.errores(ficha_datos)
    except Exception as e:
        errores_ficha = [f"ficha ilegible para el validador: {type(e).__name__}: {e}"]
    return {"expresable": True, "motivo": datos.get("motivo", ""), "ficha": ficha_datos, **extra}, errores_ficha


def formalizar(extracto, fuente, config=None, raiz_skills=None, llamar=claude_cli.chat, motivos=(), modelo=None):
    sistema = skills.system("formalizador", raiz=raiz_skills)
    ajuste = _ajustes("formalizador", config)
    modelo_usado = modelo or ajuste["modelo"]
    prompt = _prompt_formalizador(extracto, motivos)

    salida, errores = _intentar_formalizar(modelo_usado, sistema, prompt, llamar, fuente, ajuste)
    if not errores:
        return salida
    if salida is not None and not salida["expresable"]:
        return salida

    prompt_reintento = prompt + f"\nTu ficha anterior no vale por: {'; '.join(errores)}. Responde solo con el JSON pedido."
    salida, errores = _intentar_formalizar(modelo_usado, sistema, prompt_reintento, llamar, fuente, ajuste)
    if salida is not None and not salida["expresable"]:
        return salida
    if errores:
        raise ErrorAgente(f"ficha invalida tras reintento: {'; '.join(errores)}")
    return salida


def _intentar_criticar(modelo, sistema, prompt, llamar, ajuste):
    respuesta = llamar(modelo, sistema, prompt, formato=ajuste["formato"], opciones=ajuste["opciones"])
    try:
        bruto = local.json_de(respuesta)
    except local.ErrorModelo as e:
        return None, None, str(e)
    datos, _, errores_forma = msalida.limpiar("critico", bruto)
    if errores_forma:
        return None, None, "; ".join(errores_forma)
    return datos, datos.get("veredicto"), None


def criticar(ficha, extracto, config=None, raiz_skills=None, llamar=claude_cli.chat, modelo=None):
    sistema = skills.system("critico", raiz=raiz_skills)
    ajuste = _ajustes("critico", config)
    modelo_usado = modelo or ajuste["modelo"]
    prompt = (f"Ficha:\n{vallar(json.dumps(ficha, ensure_ascii=False))}\n\n"
              f"Extracto:\n{vallar(json.dumps(_para_prompt(extracto), ensure_ascii=False))}")

    datos, veredicto, error = _intentar_criticar(modelo_usado, sistema, prompt, llamar, ajuste)
    if veredicto not in ("aprobada", "devolver", "rechazada"):
        datos, veredicto, error = _intentar_criticar(modelo_usado, sistema, prompt, llamar, ajuste)
    if veredicto not in ("aprobada", "devolver", "rechazada"):
        detalle = error or f"veredicto invalido: {veredicto!r}"
        raise ErrorAgente(f"critico: {detalle}")
    return {"veredicto": veredicto, "motivos": datos.get("motivos", [])}


def _anotar_avisos(con, doc_id, resultado):
    avisos = resultado.get("avisos_salida")
    if not avisos:
        return
    guardado = catalogo.extracto(con, doc_id)
    guardado["avisos_formalizador"] = (guardado.get("avisos_formalizador") or []) + avisos
    catalogo.guardar_extracto(con, doc_id, guardado)


def procesar_fichas(con, limite=None, llamar=claude_cli.chat, vueltas=2, hasta=None, reloj=time.monotonic,
                    antes=None):
    resumen = {"aprobadas": 0, "rechazadas": 0, "no_expresables": 0, "errores": 0, "errores_contenido": 0,
              "errores_infra": 0, "omitidos": 0, "agotados": 0}
    documentos = catalogo.pendientes(con, "leido")
    for i, doc in enumerate(documentos):
        if (limite is not None and i >= limite) or (hasta is not None and reloj() >= hasta) or \
                (antes is not None and antes()):
            resumen["omitidos"] += len(documentos) - i
            break
        doc_id = doc["id"]
        extracto = catalogo.extracto(con, doc_id)
        fuente = {"url": doc["url"], "cita": doc["titulo"]}
        try:
            resultado = formalizar(extracto, fuente, llamar=llamar)
            _anotar_avisos(con, doc_id, resultado)
            if not resultado["expresable"]:
                catalogo.guardar_ficha(con, doc_id, {"expresable": False, "motivo": resultado["motivo"]},
                                       "no_expresable", motivo=resultado["motivo"])
                catalogo.marcar(con, doc_id, "no_expresable", error=resultado["motivo"])
                resumen["no_expresables"] += 1
                continue

            ficha_actual = resultado["ficha"]
            motivos, veredicto = [], "devolver"
            for vuelta in range(vueltas):
                critica = criticar(ficha_actual, extracto, llamar=llamar)
                veredicto, motivos = critica["veredicto"], critica["motivos"]
                if veredicto != "devolver" or vuelta == vueltas - 1:
                    break
                resultado = formalizar(extracto, fuente, llamar=llamar, motivos=motivos)
                _anotar_avisos(con, doc_id, resultado)
                if not resultado["expresable"]:
                    catalogo.guardar_ficha(con, doc_id, {"expresable": False, "motivo": resultado["motivo"]},
                                           "no_expresable", motivo=resultado["motivo"])
                    catalogo.marcar(con, doc_id, "no_expresable", error=resultado["motivo"])
                    resumen["no_expresables"] += 1
                    ficha_actual = None
                    break
                ficha_actual = resultado["ficha"]

            if ficha_actual is None:
                continue

            if veredicto == "aprobada":
                catalogo.guardar_ficha(con, doc_id, ficha_actual, "aprobada")
                catalogo.marcar(con, doc_id, "criticado")
                resumen["aprobadas"] += 1
            else:
                motivo_final = "; ".join(motivos)
                catalogo.guardar_ficha(con, doc_id, ficha_actual, "rechazada", motivo=motivo_final)
                catalogo.marcar(con, doc_id, "descartado", error=motivo_final)
                resumen["rechazadas"] += 1
        except Exception as e:
            # Cualquier rareza del modelo (no solo FALLOS) se queda en su documento: la etapa sigue.
            _marcar_fallo(con, doc_id, "leido", f"{type(e).__name__}: {e}", resumen, _clasificar(e))
    return resumen
