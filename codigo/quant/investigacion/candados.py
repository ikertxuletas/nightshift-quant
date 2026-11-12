import os
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None

GPU = Path(os.environ.get("QUANT_GPU_LOCK", Path.home() / ".quant" / "gpu.lock"))
CLAUDE = Path(os.environ.get("QUANT_CLAUDE_LOCK", Path.home() / ".quant" / "claude_llm.lock"))
PASO = 5


@contextmanager
def turno(ruta, espera=900, dormir=time.sleep, reloj=time.monotonic):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fh = open(ruta, "a+b")
    tuvo = msvcrt is None
    limite = reloj() + espera
    try:
        while not tuvo:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                tuvo = True
            except OSError:
                if reloj() >= limite:
                    break
                dormir(PASO)
        yield tuvo
    finally:
        if tuvo and msvcrt is not None:
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        fh.close()
