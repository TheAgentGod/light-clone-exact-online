"""
Motor Light Clone EXACT v1.1.

El algoritmo es el de model/apply_light_clone_exact.py: mismas features, mismo
modelo, mismas tablas JPEG, mismo subsampling, mismas dimensiones. La unica
diferencia es de memoria: las features se construyen por bandas de filas con
margen suficiente (>= radio del kernel gaussiano mayor), de forma que cada
valor calculado es identico al de la version que trabaja con la imagen
completa. El JPEG que escribe esta funcion es el archivo final: nunca se
vuelve a codificar.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import cv2
import joblib
import numpy as np
from PIL import Image

from .config import MODEL_DIR, MODEL_FILE, QTABLES_FILE, RESIDUAL_FILE


SIGMAS = [0.8, 2.0, 6.0, 18.0]
# Radio del kernel de cv2.GaussianBlur para sigma=18 en float32: 4*sigma*2+1 = 145 -> radio 72.
BAND_MARGIN = 128
# Pixeles objetivo por banda (features float32 de 38 canales -> ~152 bytes/pixel).
BAND_TARGET_PIXELS = 250_000
MAX_PIXELS = 40_000_000

_model = None
_gray_res = None
_qtables: dict[int, list[int]] | None = None


def load_once() -> None:
    """Carga modelo, residual y tablas JPEG una sola vez por proceso."""
    global _model, _gray_res, _qtables
    if _model is not None:
        return
    _model = joblib.load(MODEL_DIR / MODEL_FILE)
    _gray_res = np.load(MODEL_DIR / RESIDUAL_FILE)
    with open(MODEL_DIR / QTABLES_FILE, "r", encoding="utf-8") as f:
        _qtables = {int(k): v for k, v in json.load(f).items()}


def qtables() -> dict[int, list[int]]:
    load_once()
    assert _qtables is not None
    return _qtables


def load_rgb(path: str | os.PathLike[str]) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB")).astype(np.float32) / 255.0


def make_features(img: np.ndarray) -> np.ndarray:
    """Version de referencia (imagen completa). Se conserva para el self-test."""
    load_once()
    h, w, _ = img.shape
    fs = [np.ones((h, w, 1), np.float32), img]
    for sigma in SIGMAS:
        b = np.stack(
            [cv2.GaussianBlur(img[:, :, c], (0, 0), sigmaX=sigma, sigmaY=sigma) for c in range(3)],
            axis=2,
        )
        fs += [b, img - b]
    lum = (0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]).astype(np.float32)
    gx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)
    gm = np.sqrt(gx * gx + gy * gy)
    fs += [lum[:, :, None], gm[:, :, None]]
    gr = cv2.resize(_gray_res, (w, h), interpolation=cv2.INTER_CUBIC)
    fs += [gr]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn = xx / (w - 1) - 0.5
    yn = yy / (h - 1) - 0.5
    fs += [np.stack([xn, yn, xn * xn, yn * yn, xn * yn], axis=2)]
    return np.concatenate(fs, axis=2)


def _band_features(rgb8: np.ndarray, gr: np.ndarray, y0: int, y1: int) -> np.ndarray:
    h, w, _ = rgb8.shape
    a = max(0, y0 - BAND_MARGIN)
    b = min(h, y1 + BAND_MARGIN)
    sub = rgb8[a:b].astype(np.float32) / 255.0
    lo, hi = y0 - a, y1 - a
    band = sub[lo:hi]
    bh = y1 - y0

    fs = [np.ones((bh, w, 1), np.float32), band]
    for sigma in SIGMAS:
        blur_full = np.stack(
            [cv2.GaussianBlur(sub[:, :, c], (0, 0), sigmaX=sigma, sigmaY=sigma) for c in range(3)],
            axis=2,
        )
        bl = np.ascontiguousarray(blur_full[lo:hi])
        del blur_full
        fs += [bl, band - bl]

    lum = (0.2126 * sub[:, :, 0] + 0.7152 * sub[:, :, 1] + 0.0722 * sub[:, :, 2]).astype(np.float32)
    gx = cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3)
    gm = np.sqrt(gx * gx + gy * gy)
    fs += [np.ascontiguousarray(lum[lo:hi])[:, :, None], np.ascontiguousarray(gm[lo:hi])[:, :, None]]
    del lum, gx, gy, gm

    fs += [np.ascontiguousarray(gr[y0:y1])]

    yy, xx = np.mgrid[y0:y1, 0:w].astype(np.float32)
    xn = xx / (w - 1) - 0.5
    yn = yy / (h - 1) - 0.5
    fs += [np.stack([xn, yn, xn * xn, yn * yn, xn * yn], axis=2)]
    return np.concatenate(fs, axis=2)


def apply_exact(inp: str | os.PathLike[str], out: str | os.PathLike[str]) -> tuple[int, int]:
    """Procesa una imagen y escribe el JPEG final. Devuelve (ancho, alto)."""
    load_once()
    rgb8 = np.array(Image.open(inp).convert("RGB"))
    h, w, _ = rgb8.shape
    if h * w > MAX_PIXELS:
        raise ValueError(f"imagen demasiado grande: {w}x{h} pixeles (maximo {MAX_PIXELS})")

    tmp_dir = tempfile.mkdtemp(prefix="lce_")
    gr_path = os.path.join(tmp_dir, "gray_res.f32")
    try:
        gr = np.memmap(gr_path, dtype=np.float32, mode="w+", shape=(h, w, 3))
        cv2.resize(_gray_res, (w, h), dst=gr, interpolation=cv2.INTER_CUBIC)

        outbuf = np.empty((h, w, 3), np.uint8)
        band_rows = max(1, min(h, BAND_TARGET_PIXELS // max(1, w)))
        for y0 in range(0, h, band_rows):
            y1 = min(h, y0 + band_rows)
            F = _band_features(rgb8, gr, y0, y1).reshape(-1, 38)
            pred = np.empty((F.shape[0], 3), np.float32)
            for s in range(0, F.shape[0], 50_000):
                pred[s : s + 50_000] = _model.predict(F[s : s + 50_000])
            del F
            pred = np.clip(pred, 0, 1).reshape(y1 - y0, w, 3)
            outbuf[y0:y1] = (pred * 255 + 0.5).astype(np.uint8)
            del pred

        del gr
        # IMPORTANTE: estos bytes son el archivo final. No re-codificar despues.
        Image.fromarray(outbuf, "RGB").save(out, "JPEG", qtables=qtables(), subsampling=2, optimize=False)
    finally:
        try:
            os.remove(gr_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
    return w, h
