"""
Motor Light Clone EXACT v1.1.

Este modulo es una copia literal del cuerpo de apply_light_clone_exact.py
(model/apply_light_clone_exact.py). No se modifica el algoritmo, ni las tablas
JPEG, ni el subsampling, ni las dimensiones. El JPEG que escribe esta funcion
es el archivo final: nunca se vuelve a codificar.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import joblib
import numpy as np
from PIL import Image

MODEL_DIR = Path(os.environ.get("LIGHT_CLONE_MODEL_DIR", Path(__file__).resolve().parents[1] / "model"))

_model = None
_gray_res = None
_qtables: dict[int, list[int]] | None = None


def load_once() -> None:
    """Carga modelo, residual y tablas JPEG una sola vez por proceso."""
    global _model, _gray_res, _qtables
    if _model is not None:
        return
    _model = joblib.load(MODEL_DIR / "light_clone_v1.joblib")
    _gray_res = np.load(MODEL_DIR / "gray_residual.npy")
    with open(MODEL_DIR / "jpeg_qtables.json", "r", encoding="utf-8") as f:
        _qtables = {int(k): v for k, v in json.load(f).items()}


def qtables() -> dict[int, list[int]]:
    load_once()
    assert _qtables is not None
    return _qtables


def load_rgb(path: str | os.PathLike[str]) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB")).astype(np.float32) / 255.0


def make_features(img: np.ndarray) -> np.ndarray:
    load_once()
    h, w, _ = img.shape
    fs = [np.ones((h, w, 1), np.float32), img]
    for sigma in [0.8, 2.0, 6.0, 18.0]:
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


def apply_exact(inp: str | os.PathLike[str], out: str | os.PathLike[str]) -> tuple[int, int]:
    """Procesa una imagen y escribe el JPEG final. Devuelve (ancho, alto)."""
    load_once()
    img = load_rgb(inp)
    F = make_features(img).reshape(-1, 38)
    pred = np.empty((F.shape[0], 3), np.float32)
    for s in range(0, F.shape[0], 200000):
        pred[s : s + 200000] = _model.predict(F[s : s + 200000])
    pred = np.clip(pred, 0, 1).reshape(img.shape)

    # IMPORTANTE: estos bytes son el archivo final. No re-codificar despues.
    Image.fromarray((pred * 255 + 0.5).astype(np.uint8), "RGB").save(
        out, "JPEG", qtables=qtables(), subsampling=2, optimize=False
    )
    h, w, _ = img.shape
    return w, h
