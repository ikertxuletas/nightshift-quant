"""Momento desde el que cuenta la noche, siempre en UTC."""
from datetime import datetime, timezone


def desde_utc(parte):
    """El parte trae 'desde' ya en UTC; los partes viejos solo tienen 'inicio', hora local sin zona."""
    desde = parte.get("desde")
    if desde:
        return desde
    inicio = parte.get("inicio")
    if not inicio:
        return None
    try:
        return datetime.fromisoformat(inicio).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return None


def ahora_utc():
    return datetime.now(timezone.utc)


def fecha_local(ahora=None):
    """Los ficheros de la noche se nombran con la fecha local; un datetime con zona se pasa antes a local."""
    ahora = ahora or datetime.now()
    if ahora.tzinfo is not None:
        ahora = ahora.astimezone()
    return ahora.strftime("%Y%m%d")
