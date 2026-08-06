/* ReliefMD front-end: record → transcribe → note → review → copy. */
"use strict";

const $ = (id) => document.getElementById(id);
let mediaRecorder = null, chunks = [], timerInt = null, t0 = 0;
let currentVisit = null;

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
  return data;
}

function err(msg) {
  const box = $("errBox");
  if (!msg) { box.classList.add("hidden"); return; }
  box.textContent = msg; box.classList.remove("hidden");
}
function busy(msg) {
  const el = $("busy");
  if (!msg) { el.classList.add("hidden"); return; }
  $("busyText").textContent = msg; el.classList.remove("hidden");
}

/* ---------------- recording ---------------- */

$("btnRecord").onclick = async () => {
  err(null);
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    err("Microphone access denied — allow the mic, or upload/paste instead.");
    return;
  }
  chunks = [];
  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(timerInt);
    $("btnRecord").classList.remove("recording");
    $("recLabel").textContent = "Record visit";
    submitAudio(new Blob(chunks, { type: "audio/webm" }));
  };
  mediaRecorder.start(1000);
  t0 = Date.now();
  timerInt = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    $("recTimer").textContent =
      `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
  $("btnRecord").classList.add("recording");
  $("recLabel").textContent = "Stop & generate";
};

$("fileInput").onchange = () => {
  const f = $("fileInput").files[0];
  if (f) submitAudio(f);
};
document.querySelector(".filelab").onclick = () => $("fileInput").click();

$("btnPasteToggle").onclick = () => {
  $("pasteBox").classList.toggle("hidden");
  $("btnGenerate").classList.toggle("hidden");
};
$("btnGenerate").onclick = () => {
  const text = $("pasteBox").value.trim();
  if (!text) { err("Paste or type a transcript first."); return; }
  submit({ transcript_text: text });
};

async function submitAudio(blob) {
  await submit({ audio: blob });
}

async function submit(payload) {
  err(null);
  busy(payload.audio ? "Transcribing & writing your note…" : "Writing your note…");
  const fd = new FormData();
  if (payload.audio) fd.append("audio", payload.audio, "visit.webm");
  if (payload.transcript_text) fd.append("transcript_text", payload.transcript_text);
  fd.append("style", $("optStyle").value);
  fd.append("language", $("optLanguage").value);
  fd.append("patient_label", $("patientLabel").value);
  try {
    currentVisit = await api("/api/visits", { method: "POST", body: fd });
    renderVisit(currentVisit);
    loadHistory();
  } catch (e) {
    err(e.message);
  } finally {
    busy(null);
  }
}

/* ---------------- rendering ---------------- */

function renderVisit(v) {
  $("emptyState").classList.add("hidden");
  $("noteView").classList.remove("hidden");
  $("noteTitle").textContent = v.patient_label;
  $("noteMeta").textContent =
    `${new Date(v.created_at).toLocaleString()} · ${v.transcript.provider}`;
  document.querySelectorAll("[data-soap]").forEach((ta) => {
    ta.value = v.note.soap[ta.dataset.soap] || "";
    autosize(ta);
  });
  const codes = $("codes");
  codes.innerHTML = "";
  v.note.icd10.forEach((c) => {
    codes.insertAdjacentHTML("beforeend",
      `<span class="chip ${c.confidence === "low" ? "low" : ""}"><b>${c.code}</b> ${c.description} <small>${c.confidence}</small></span>`);
  });
  v.note.cpt.forEach((c) => {
    codes.insertAdjacentHTML("beforeend",
      `<span class="chip"><b>${c.code}</b> ${c.description} <small>CPT</small></span>`);
  });
  $("followups").innerHTML =
    v.note.followups.concat(v.note.red_flags.map((r) => `Safety-net: ${r}`))
      .map((f) => `<li>${f}</li>`).join("");
  $("gaps").innerHTML = (v.note.gaps || []).map((g) => `<li>${g}</li>`).join("");
  $("gapsWrap").style.display = (v.note.gaps || []).length ? "" : "none";
  $("handout").value = v.note.patient_handout;
  autosize($("handout"));
  $("transcriptText").textContent = v.transcript.text;
  $("letterOut").classList.add("hidden");
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight + 4, 420) + "px";
}
document.addEventListener("input", (e) => {
  if (e.target.tagName === "TEXTAREA") autosize(e.target);
});

/* ---------------- copy & edit ---------------- */

function flash(btn) {
  btn.classList.add("done");
  const t = btn.textContent;
  btn.textContent = "Copied";
  setTimeout(() => { btn.classList.remove("done"); btn.textContent = t; }, 1200);
}
document.querySelectorAll(".card[data-copy] .copy").forEach((btn) => {
  btn.onclick = () => {
    const ta = btn.closest(".card").querySelector("textarea");
    navigator.clipboard.writeText(ta.value).then(() => flash(btn));
  };
});
$("copyHandout").onclick = () =>
  navigator.clipboard.writeText($("handout").value).then(() => flash($("copyHandout")));
$("btnCopyAll").onclick = () => {
  const s = (k) => document.querySelector(`[data-soap="${k}"]`).value;
  const full = `SUBJECTIVE:\n${s("subjective")}\n\nOBJECTIVE:\n${s("objective")}\n\nASSESSMENT:\n${s("assessment")}\n\nPLAN:\n${s("plan")}`;
  navigator.clipboard.writeText(full).then(() => flash($("btnCopyAll")));
};
$("btnSaveEdits").onclick = async () => {
  if (!currentVisit) return;
  const soap = {};
  document.querySelectorAll("[data-soap]").forEach((ta) => { soap[ta.dataset.soap] = ta.value; });
  await api(`/api/visits/${currentVisit.id}/note`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ soap, patient_handout: $("handout").value }),
  });
  flash($("btnSaveEdits"));
};

/* ---------------- letters ---------------- */

const LETTER_NAMES = {
  referral: "Referral letter", sick_note: "Sick note",
  insurance: "Insurance letter", patient_followup: "Patient follow-up letter",
};
document.querySelectorAll("[data-letter]").forEach((btn) => {
  btn.onclick = async () => {
    if (!currentVisit) return;
    err(null);
    const kind = btn.dataset.letter;
    const old = btn.textContent;
    btn.textContent = "Writing…"; btn.disabled = true;
    try {
      const res = await api(`/api/visits/${currentVisit.id}/letter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: kind }),
      });
      $("letterTitle").textContent = LETTER_NAMES[kind];
      $("letterText").value = res.text;
      $("letterOut").classList.remove("hidden");
      autosize($("letterText"));
    } catch (e) {
      err(e.message);
    } finally {
      btn.textContent = old; btn.disabled = false;
    }
  };
});
$("copyLetter").onclick = () =>
  navigator.clipboard.writeText($("letterText").value).then(() => flash($("copyLetter")));

/* ---------------- history & status ---------------- */

async function loadHistory() {
  const list = await api("/api/visits");
  $("visitList").innerHTML = list.length ? "" : "<span class='fine'>No visits yet.</span>";
  list.slice(0, 20).forEach((v) => {
    const el = document.createElement("button");
    el.className = "visit-item";
    el.innerHTML = `<b>${v.patient_label}</b><small>${new Date(v.created_at).toLocaleString()} — ${v.assessment}</small>`;
    el.onclick = async () => { currentVisit = await api(`/api/visits/${v.id}`); renderVisit(currentVisit); };
    $("visitList").appendChild(el);
  });
}

async function boot() {
  try {
    const s = await api("/api/status");
    $("statusLine").textContent =
      `${s.model} · transcription: ${s.transcription} · v${s.version}`;
    if (s.transcription === "NOT CONFIGURED")
      err("No transcription provider configured — paste/type transcripts will still work. Set DEEPGRAM_API_KEY for premium medical transcription.");
  } catch { /* status is cosmetic */ }
  loadHistory();
}
boot();
