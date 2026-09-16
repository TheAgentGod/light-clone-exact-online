from __future__ import annotations

import asyncio
import os
import csv
import io
import shutil
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .files import ALLOWED_EXTS, MAX_FILE_BYTES, check_upload, sanitize_name
from .pipeline import load_once
from .selftest import run_selftest

BASE = Path(__file__).resolve().parents[1]
WORK = BASE / "work"
UPLOADS = WORK / "uploads"
OUTPUTS = WORK / "outputs"
FRONTEND_DIST = BASE.parent / "frontend" / "dist"

CONCURRENCY = int(os.environ.get("LIGHT_CLONE_CONCURRENCY", "1"))

STATE: dict[str, dict] = {}
SELFTEST: dict = {"ok": False, "checks": [], "ran": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (UPLOADS, OUTPUTS):
        d.mkdir(parents=True, exist_ok=True)
    load_once()
    result = run_selftest()
    SELFTEST.update(result)
    SELFTEST["ran"] = True
    status = "OK" if result["ok"] else "FALLO"
    print(f"[self-test] {status}")
    for check in result["checks"]:
        print(f"  [{'ok' if check['ok'] else 'FALLO'}] {check['check']} {check['detail']}")
    if not result["ok"]:
        print("[self-test] Procesamiento BLOQUEADO: los hashes no coinciden con verification.json")
    yield


app = FastAPI(title="Light Clone EXACT v1.1", lifespan=lifespan)


def require_selftest() -> None:
    if not SELFTEST.get("ok"):
        raise HTTPException(
            status_code=503,
            detail="Self-test fallido: el procesamiento esta bloqueado. Revisa la consola del backend.",
        )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "model_loaded": True,
        "max_file_bytes": MAX_FILE_BYTES,
        "allowed_extensions": sorted(ALLOWED_EXTS),
        "selftest": SELFTEST,
        "pipeline": "apply_light_clone_exact.py (Light Clone EXACT v1.1)",
    }


@app.get("/api/selftest")
def selftest():
    return SELFTEST


@app.post("/api/upload")
async def upload(files: list[UploadFile]):
    require_selftest()
    batch_id = uuid.uuid4().hex[:12]
    batch_dir = UPLOADS / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    rejected: list[dict] = []
    taken: set[str] = set()

    for index, upload_file in enumerate(files):
        data = await upload_file.read()
        problem = check_upload(upload_file.filename or "", upload_file.content_type, len(data))
        if problem:
            rejected.append({"input_file": upload_file.filename or "(sin nombre)", "reason": problem})
            continue
        item_id = f"{batch_id}-{index:03d}"
        stored = batch_dir / f"{item_id}{Path(upload_file.filename or '').suffix.lower()}"
        stored.write_bytes(data)
        items.append(
            {
                "id": item_id,
                "input_file": upload_file.filename or stored.name,
                "output_file": sanitize_name(upload_file.filename or stored.name, taken),
                "stored_path": str(stored),
                "status": "pendiente",
                "width": None,
                "height": None,
                "input_size_bytes": len(data),
                "output_size_bytes": None,
                "processing_time_seconds": None,
                "error_message": None,
            }
        )

    STATE[batch_id] = {"id": batch_id, "items": items, "rejected": rejected, "processing": False}
    return public_batch(batch_id)


def public_batch(batch_id: str) -> dict:
    batch = STATE.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote inexistente")
    items = [{k: v for k, v in item.items() if k != "stored_path"} for item in batch["items"]]
    done = sum(1 for i in items if i["status"] == "completada")
    failed = sum(1 for i in items if i["status"] == "error")
    return {
        "id": batch_id,
        "items": items,
        "rejected": batch["rejected"],
        "processing": batch["processing"],
        "completed": done,
        "failed": failed,
        "total": len(items),
    }


def process_one(item: dict, out_dir: Path) -> None:
    from .pipeline import apply_exact

    started = time.perf_counter()
    try:
        out_path = out_dir / item["output_file"]
        width, height = apply_exact(item["stored_path"], out_path)
        item.update(
            status="completada",
            width=width,
            height=height,
            output_size_bytes=out_path.stat().st_size,
            processing_time_seconds=round(time.perf_counter() - started, 3),
            error_message=None,
        )
    except Exception as error:  # el fallo queda aislado en su fila
        item.update(
            status="error",
            output_size_bytes=None,
            processing_time_seconds=round(time.perf_counter() - started, 3),
            error_message=f"{type(error).__name__}: {error}",
        )


@app.post("/api/batches/{batch_id}/process")
async def process_batch(batch_id: str):
    require_selftest()
    batch = STATE.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote inexistente")
    if batch["processing"]:
        return public_batch(batch_id)

    out_dir = OUTPUTS / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    batch["processing"] = True
    pending = [i for i in batch["items"] if i["status"] in ("pendiente", "error")]
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def run(item: dict) -> None:
        async with semaphore:
            item["status"] = "procesando"
            await asyncio.to_thread(process_one, item, out_dir)

    try:
        await asyncio.gather(*(run(item) for item in pending))
    finally:
        batch["processing"] = False
    return public_batch(batch_id)


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    return public_batch(batch_id)


@app.get("/api/batches/{batch_id}/files/{output_file}")
def get_output(batch_id: str, output_file: str):
    """Sirve los bytes tal cual los escribio apply_light_clone_exact.py."""
    if "/" in output_file or ".." in output_file:
        raise HTTPException(status_code=400, detail="Nombre invalido")
    path = OUTPUTS / batch_id / output_file
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archivo inexistente")
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=output_file,
        headers={"Cache-Control": "no-transform, no-store", "X-Light-Clone-Exact": "1"},
    )


def build_csv(batch: dict) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "input_file",
            "output_file",
            "status",
            "width",
            "height",
            "input_size_bytes",
            "output_size_bytes",
            "processing_time_seconds",
            "error_message",
        ]
    )
    for item in batch["items"]:
        writer.writerow(
            [
                item["input_file"],
                item["output_file"] if item["status"] == "completada" else "",
                item["status"],
                item["width"] or "",
                item["height"] or "",
                item["input_size_bytes"],
                item["output_size_bytes"] or 0,
                item["processing_time_seconds"] or "",
                item["error_message"] or "",
            ]
        )
    for rejected in batch["rejected"]:
        writer.writerow([rejected["input_file"], "", "rechazado", "", "", "", 0, "", rejected["reason"]])
    return buffer.getvalue()


@app.get("/api/download/{batch_id}")
def download_zip(batch_id: str):
    batch = STATE.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote inexistente")
    out_dir = OUTPUTS / batch_id
    buffer = io.BytesIO()
    # ZIP_STORED: los JPEG viajan sin recomprimir ni alterar un solo byte.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        for item in batch["items"]:
            if item["status"] != "completada":
                continue
            path = out_dir / item["output_file"]
            if path.exists():
                zf.writestr(item["output_file"], path.read_bytes())
        zf.writestr("results.csv", build_csv(batch))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="light_clone_exact_{batch_id}.zip"',
            "Cache-Control": "no-transform, no-store",
        },
    )


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str):
    STATE.pop(batch_id, None)
    shutil.rmtree(UPLOADS / batch_id, ignore_errors=True)
    shutil.rmtree(OUTPUTS / batch_id, ignore_errors=True)
    return {"ok": True}


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
