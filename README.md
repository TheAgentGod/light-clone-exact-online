---
title: Light Clone EXACT v1.1
emoji: 🖼️
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Light Clone EXACT v1.1 — procesamiento por lotes

Herramienta interna de procesamiento de imagenes con el pipeline exacto
`apply_light_clone_exact.py`.

## Reglas no negociables

- Motor unico: `apply_light_clone_exact.py`. No hay otra implementacion.
- El JPEG que escribe Python es el archivo final. **Nunca** se recodifica con
  Sharp, Canvas, ImageMagick, APIs del navegador, optimizadores de imagen ni
  transformaciones de CDN.
- Guardado con las tablas de `jpeg_qtables.json`, `subsampling=2`,
  `optimize=False`. No se usa `quality=95`.
- Sin perfil ICC, sin EXIF, sin metadata añadida.
- Dimensiones originales intactas.
- Descarga individual servida desde disco con `Cache-Control: no-transform, no-store`.
- ZIP en modo almacenado (`ZIP_STORED`): los JPEG salen byte a byte iguales.

## Self-test obligatorio

Al arrancar se verifican los sha256 de `selftest_A.jpg` y `selftest_B.jpg`
contra `verification.json`, las tablas JPEG, la ausencia de EXIF/ICC, el
determinismo byte a byte y la conservacion de dimensiones. Si algo falla, la API
responde 503 y no procesa ningun lote.

## Limites

PNG / JPG / JPEG / WEBP, maximo 25 MB por archivo, dos imagenes en paralelo,
errores aislados por archivo, descarga en ZIP con `results.csv`.

## Notas de despliegue

- Space de tipo Docker, puerto 7860.
- Poner el Space en **privado** si el procesamiento no debe ser publico.
- El almacenamiento es efimero: los resultados se descargan, no se archivan.

## Version del modelo de imagen

La version en uso se declara en `backend/app/config.py`:

```
image_model_version = v1   (variable de entorno IMAGE_MODEL_VERSION)
```

Se expone en `GET /api/health` (`image_model_version`) y en `GET /api/model`, y
se muestra en la pagina.

### Pasar a v2 sin tocar la aplicacion

1. Dejar en `backend/model/` los artefactos nuevos: modelo `.joblib`, mapa de
   residuo `.npy`, `jpeg_qtables.json` y `verification.json` con sus hashes de
   referencia y las imagenes de self-test.
2. Definir las variables de entorno:

```
IMAGE_MODEL_VERSION=v2
LIGHT_CLONE_MODEL_FILE=light_clone_v2.joblib
LIGHT_CLONE_RESIDUAL_FILE=gray_residual_v2.npy
# opcionales: LIGHT_CLONE_MODEL_DIR, LIGHT_CLONE_QTABLES_FILE, LIGHT_CLONE_VERIFICATION_FILE
```

3. Reiniciar el servicio. El self-test se ejecuta contra el `verification.json`
   del modelo nuevo y bloquea el procesamiento si no coincide.

No se modifica ni el pipeline, ni la interfaz, ni el flujo de lotes. El JPEG que
escribe el motor sigue siendo el archivo final: no se recodifica ni se le añade
metadata.
