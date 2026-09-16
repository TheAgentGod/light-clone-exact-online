"""Self-test por linea de comandos. Sale con codigo 1 si algo no coincide."""

from __future__ import annotations

import sys

from .selftest import run_selftest

result = run_selftest()
for check in result["checks"]:
    mark = "ok  " if check["ok"] else "FALLO"
    detail = f" ({check['detail']})" if check["detail"] else ""
    print(f"[{mark}] {check['check']}{detail}")
print()
if result["ok"]:
    print("Self-test OK: los hashes coinciden con verification.json.")
    sys.exit(0)
print("Self-test FALLIDO: no se habilita el procesamiento.")
sys.exit(1)
