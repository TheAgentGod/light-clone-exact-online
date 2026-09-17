/* Light Clone EXACT v1.1 — interfaz sin dependencias.
   El procesamiento corre en el servidor; aqui solo se consulta el estado.
   Ninguna imagen se abre, dibuja ni recodifica en el navegador. */

const $ = (id) => document.getElementById(id);
const state = { batch: null, blocked: true, polling: null, busy: false };

function fmtBytes(n) {
  if (!n) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(2) + " MB";
}

function showError(msg) {
  const panel = $("error-panel");
  if (!msg) {
    panel.hidden = true;
    panel.textContent = "";
    return;
  }
  panel.hidden = false;
  panel.textContent = msg;
}

async function jsonFetch(url, options, tries = 3) {
  let lastError;
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const res = await fetch(url, options);
      const text = await res.text();
      const data = text ? JSON.parse(text) : {};
      if (!res.ok) throw new Error(data.detail || "Error " + res.status);
      return data;
    } catch (error) {
      lastError = error;
      // Un corte de red puntual no debe romper el flujo: se reintenta.
      await new Promise((r) => setTimeout(r, 1200 * (attempt + 1)));
    }
  }
  throw lastError;
}

async function loadHealth() {
  try {
    // El servidor gratuito puede tardar en despertar: se reintenta varias veces.
    const health = await jsonFetch("/api/health", undefined, 6);
    state.blocked = !health.selftest || !health.selftest.ok;
    $("selftest-state").textContent = state.blocked
      ? "FALLO — procesamiento bloqueado"
      : "OK — hashes coinciden con verification.json";
    $("selftest-state").className = state.blocked ? "err" : "ok";
    $("selftest-checks").innerHTML = (health.selftest.checks || [])
      .map(
        (c) =>
          '<li class="' +
          (c.ok ? "ok" : "err") +
          '">' +
          (c.ok ? "ok" : "FALLO") +
          " — " +
          c.check +
          (c.detail ? " (" + c.detail + ")" : "") +
          "</li>",
      )
      .join("");
    $("pipeline-line").textContent = health.pipeline || "";
    if (!state.blocked) showError(null);
  } catch (error) {
    state.blocked = true;
    $("selftest-state").textContent = "esperando al servidor…";
    showError("El servidor esta despertando. Se vuelve a intentar automaticamente.");
    setTimeout(() => loadHealth().then(render), 5000);
  }
}

function render() {
  const batch = state.batch;
  const rows = $("rows");
  const items = batch ? batch.items : [];
  rows.innerHTML = items
    .map(
      (i) =>
        "<tr><td>" +
        i.input_file +
        "</td><td>" +
        (i.width ? i.width + "×" + i.height : "—") +
        "</td><td>" +
        fmtBytes(i.input_size_bytes) +
        "</td><td>" +
        fmtBytes(i.output_size_bytes) +
        '</td><td class="st-' +
        i.status.replace(/ /g, "-") +
        '">' +
        i.status +
        "</td><td>" +
        (i.processing_time_seconds ? i.processing_time_seconds + " s" : "—") +
        "</td><td>" +
        (i.status === "completada"
          ? '<a href="/api/batches/' +
            batch.id +
            "/files/" +
            encodeURIComponent(i.output_file) +
            '" download>' +
            i.output_file +
            "</a>"
          : "—") +
        "</td></tr>",
    )
    .join("");

  if (batch && batch.rejected && batch.rejected.length) {
    rows.innerHTML += batch.rejected
      .map(
        (r) =>
          '<tr><td>' +
          r.input_file +
          '</td><td colspan="5" class="st-error">rechazado: ' +
          r.reason +
          "</td><td>—</td></tr>",
      )
      .join("");
  }

  const done = batch ? batch.completed + batch.failed : 0;
  $("progress-line").textContent = batch
    ? done + "/" + batch.total + " · " + batch.completed + " completadas · " + batch.failed + " con error" +
      (batch.processing ? " · procesando…" : "")
    : "";

  const hasPending = items.some((i) => i.status === "pendiente" || i.status === "error");
  $("btn-process").disabled = state.blocked || state.busy || !batch || !hasPending || batch.processing;
  $("btn-zip").disabled = !batch || batch.completed === 0;
  $("btn-clear").disabled = !batch || batch.processing;
}

function startPolling() {
  stopPolling();
  state.polling = setInterval(async () => {
    if (!state.batch) return;
    try {
      state.batch = await jsonFetch("/api/batches/" + state.batch.id, undefined, 5);
      render();
      if (!state.batch.processing) stopPolling();
    } catch (error) {
      // El servidor puede tardar en responder mientras procesa: seguimos intentando.
    }
  }, 2000);
}

function stopPolling() {
  if (state.polling) clearInterval(state.polling);
  state.polling = null;
}

async function upload(files) {
  if (!files.length || state.blocked) return;
  showError(null);
  state.busy = true;
  render();
  const selected = Array.from(files);
  const batchId = state.batch && !state.batch.processing
    ? state.batch.id
    : crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  const failed = [];

  for (let index = 0; index < selected.length; index++) {
    const file = selected[index];
    const form = new FormData();
    form.append("files", file);
    const uploadId = crypto.randomUUID();
    const url =
      "/api/upload?batch_id=" + encodeURIComponent(batchId) +
      "&upload_id=" + encodeURIComponent(uploadId);
    try {
      state.batch = await jsonFetch(url, { method: "POST", body: form }, 3);
      localStorage.setItem("lce_batch", state.batch.id);
      render();
    } catch (error) {
      failed.push(file.name + ": " + error.message);
    }
  }

  if (failed.length) {
    showError(
      failed.length === selected.length
        ? "No se pudieron subir las fotos: " + failed.join(" · ")
        : "Algunas fotos no se pudieron subir: " + failed.join(" · "),
    );
  }
  state.busy = false;
  render();
}

async function process() {
  if (!state.batch) return;
  showError(null);
  state.busy = true;
  render();
  try {
    state.batch = await jsonFetch("/api/batches/" + state.batch.id + "/process", { method: "POST" });
    startPolling();
  } catch (error) {
    showError("No se pudo iniciar el procesamiento: " + error.message);
  } finally {
    state.busy = false;
    render();
  }
}

async function clearBatch() {
  if (!state.batch) return;
  const id = state.batch.id;
  stopPolling();
  state.batch = null;
  localStorage.removeItem("lce_batch");
  render();
  try {
    await fetch("/api/batches/" + id, { method: "DELETE" });
  } catch (error) {
    /* el lote local ya quedo limpio */
  }
}

async function restore() {
  const id = localStorage.getItem("lce_batch");
  if (!id) return;
  try {
    state.batch = await jsonFetch("/api/batches/" + id, undefined, 1);
    render();
    if (state.batch.processing) startPolling();
  } catch (error) {
    localStorage.removeItem("lce_batch");
  }
}

$("drop").addEventListener("click", () => !state.blocked && $("file-input").click());
$("drop").addEventListener("dragover", (e) => {
  e.preventDefault();
  $("drop").classList.add("over");
});
$("drop").addEventListener("dragleave", () => $("drop").classList.remove("over"));
$("drop").addEventListener("drop", (e) => {
  e.preventDefault();
  $("drop").classList.remove("over");
  upload(e.dataTransfer.files);
});
$("file-input").addEventListener("change", (e) => {
  upload(e.target.files);
  e.target.value = "";
});
$("btn-process").addEventListener("click", process);
$("btn-zip").addEventListener("click", () => {
  if (state.batch) window.location.href = "/api/download/" + state.batch.id;
});
$("btn-clear").addEventListener("click", clearBatch);

loadHealth().then(() => {
  render();
  restore();
});
