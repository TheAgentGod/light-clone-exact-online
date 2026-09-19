"""Configuracion de modelo.

Punto unico donde se declara que artefactos usa el pipeline. Para pasar a v2
basta con dejar los archivos nuevos en la carpeta del modelo (o apuntar a otra
carpeta) y ajustar estas variables de entorno: no se toca ni el codigo del
pipeline, ni la interfaz, ni el flujo de lotes.

Variables de entorno:
  IMAGE_MODEL_VERSION            etiqueta visible de la version (por defecto v1)
  LIGHT_CLONE_MODEL_DIR          carpeta con los artefactos
  LIGHT_CLONE_MODEL_FILE         archivo del modelo (.joblib)
  LIGHT_CLONE_RESIDUAL_FILE      mapa de residuo (.npy)
  LIGHT_CLONE_QTABLES_FILE       tablas de cuantizacion JPEG (.json)
  LIGHT_CLONE_VERIFICATION_FILE  referencia del self-test (.json)
"""

from __future__ import annotations

import os
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# Version del modelo de imagen en uso. Cambiar a "v2" al sustituir artefactos.
IMAGE_MODEL_VERSION = os.environ.get("IMAGE_MODEL_VERSION", "v1")

MODEL_DIR = Path(os.environ.get("LIGHT_CLONE_MODEL_DIR", BASE / "model"))
MODEL_FILE = os.environ.get("LIGHT_CLONE_MODEL_FILE", "light_clone_v1.joblib")
RESIDUAL_FILE = os.environ.get("LIGHT_CLONE_RESIDUAL_FILE", "gray_residual.npy")
QTABLES_FILE = os.environ.get("LIGHT_CLONE_QTABLES_FILE", "jpeg_qtables.json")
VERIFICATION_FILE = os.environ.get("LIGHT_CLONE_VERIFICATION_FILE", "verification.json")


def model_info() -> dict:
    return {
        "image_model_version": IMAGE_MODEL_VERSION,
        "model_dir": str(MODEL_DIR),
        "model_file": MODEL_FILE,
        "residual_file": RESIDUAL_FILE,
        "qtables_file": QTABLES_FILE,
        "verification_file": VERIFICATION_FILE,
    }
