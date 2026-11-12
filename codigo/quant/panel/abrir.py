import argparse
import webbrowser
from pathlib import Path

from quant import rutas
from quant.panel.servidor import PORT


def main(argv=None):
    p = argparse.ArgumentParser(description="Abre el panel de Quant en el navegador")
    p.add_argument("--raiz", default=str(rutas.RAIZ))
    p.add_argument("--port", type=int, default=PORT)
    a = p.parse_args(argv)
    key = (Path(a.raiz) / "registro" / "panel_clave").read_text(encoding="utf-8").strip()
    webbrowser.open(f"http://127.0.0.1:{a.port}/?key={key}")


if __name__ == "__main__":
    main()
