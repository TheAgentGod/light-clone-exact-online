"""
Self-test obligatorio previo a cualquier procesamiento real.

Comprueba:
  1. Integridad de selftest_A.jpg y selftest_B.jpg contra los sha256 de
     verification.json (deben ser byte-identicos a las salidas validadas).
  2. Que las tablas de cuantizacion de esos JPEG coinciden con
     jpeg_qtables.json y que no traen EXIF ni ICC.
  3. Que el codificador local escribe con esas mismas tablas, subsampling 2,
     sin metadata y de forma determinista (dos corridas -> mismos bytes).
  4. Que el modelo y el residual cargan y el pipeline corre completo.

Si algo falla, la API queda bloqueada: no se procesa ningun lote.
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .pipeline import MODEL_DIR, apply_exact, qtables


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_selftest() -> dict:
    checks: list[dict] = []
    ok = True

    def add(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        checks.append({"check": name, "ok": bool(passed), "detail": detail})
        if not passed:
            ok = False

    verification = json.loads((MODEL_DIR / "verification.json").read_text(encoding="utf-8"))
    Q = qtables()
    expected_q = [Q[k] for k in sorted(Q)]

    for entry in verification:
        name = entry["output"]
        path = MODEL_DIR / name
        if not path.exists():
            add(f"{name}: existe", False, "archivo ausente")
            continue
        digest = sha256_file(path)
        add(
            f"{name}: sha256 == verification.json",
            digest == entry["sha256_output"] == entry["sha256_reference"],
            f"esperado {entry['sha256_output'][:16]}…, obtenido {digest[:16]}…",
        )
        with Image.open(path) as im:
            add(
                f"{name}: tablas JPEG == jpeg_qtables.json",
                [list(v) for v in im.quantization.values()] == expected_q,
            )
            add(
                f"{name}: sin EXIF ni ICC",
                not im.info.get("exif") and not im.info.get("icc_profile"),
            )

    # Codificador local: mismas tablas, subsampling 2, sin metadata.
    probe = Image.fromarray(
        (np.mgrid[0:64, 0:64][0].astype(np.uint8)[:, :, None] * np.ones((1, 1, 3), np.uint8)), "RGB"
    )
    buf = io.BytesIO()
    probe.save(buf, "JPEG", qtables=Q, subsampling=2, optimize=False)
    with Image.open(io.BytesIO(buf.getvalue())) as im:
        add("codificador local: tablas JPEG aplicadas", [list(v) for v in im.quantization.values()] == expected_q)
        add("codificador local: sin EXIF ni ICC", not im.info.get("exif") and not im.info.get("icc_profile"))

    # Pipeline completo y determinismo byte a byte.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        src = MODEL_DIR / "selftest_B.jpg"
        a, b = tmp_path / "a.jpg", tmp_path / "b.jpg"
        with Image.open(src) as im:
            src_size = im.size
        size_a = apply_exact(src, a)
        apply_exact(src, b)
        add("pipeline: corre de punta a punta", a.exists() and a.stat().st_size > 0)
        add("pipeline: determinista (mismos bytes)", sha256_file(a) == sha256_file(b))
        add("pipeline: conserva dimensiones", size_a == src_size, f"{src_size} -> {size_a}")
        with Image.open(a) as im:
            add("salida: tablas JPEG correctas", [list(v) for v in im.quantization.values()] == expected_q)
            add("salida: sin EXIF ni ICC", not im.info.get("exif") and not im.info.get("icc_profile"))

    return {"ok": ok, "checks": checks}
