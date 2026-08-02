/* PromptCut UI — a thin editor over project.json (the same file Claude edits). */
"use strict";

let proj = null;
let meta = { looks: [], transitions: [], caption_styles: [] };
let sel = null; // {kind: 'clip'|'text'|'music', index}

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

async function boot() {
  meta = await api("/api/looks");
  proj = await api("/api/project");
  renderAll();
  tryLoadPreview();
}

function clipDur(c) {
  if (c.ramp) return c.ramp.reduce((s, r) => s + (r.to - r.from) / r.speed, 0);
  return (c.out - c.in) / (c.speed || 1);
}
function totalDur() {
  const clips = proj.timeline.video;
  let t = 0;
  clips.forEach((c, i) => {
    t += clipDur(c);
    if (i < clips.length - 1 && c.transition_out) t -= (c.transition_out.duration || 0.5);
  });
  return Math.max(t, 0);
}

/* ---------------- rendering ---------------- */

function renderAll() {
  $("projName").textContent = proj.name;
  $("projDur").textContent = totalDur().toFixed(1) + "s";
  renderTracks();
  renderAssets();
  renderInspector();
}

function renderTracks() {
  const tv = $("trackVideo");
  tv.innerHTML = "";
  const total = Math.max(totalDur(), 0.001);
  proj.timeline.video.forEach((c, i) => {
    const el = document.createElement("div");
    el.className = "clip" + (sel && sel.kind === "clip" && sel.index === i ? " sel" : "");
    el.style.width = Math.max((clipDur(c) / total) * 100, 4) + "%";
    el.innerHTML = `<b>${c.id}</b> · ${c.asset}<span class="sub">${c.in}s→${c.out}s` +
      (c.speed && c.speed !== 1 ? ` ×${c.speed}` : "") +
      (c.transition_out ? ` · ${c.transition_out.type}` : "") + "</span>";
    el.onclick = () => { sel = { kind: "clip", index: i }; renderAll(); };
    tv.appendChild(el);
  });

  const tt = $("trackText");
  tt.innerHTML = "";
  proj.timeline.texts.forEach((t, i) => {
    const el = document.createElement("div");
    el.className = "clip textclip" + (sel && sel.kind === "text" && sel.index === i ? " sel" : "");
    el.style.width = Math.max(((t.end - t.start) / Math.max(totalDur(), 1)) * 100, 6) + "%";
    el.textContent = "T: " + t.text.slice(0, 18);
    el.onclick = () => { sel = { kind: "text", index: i }; renderAll(); };
    tt.appendChild(el);
  });
  const addT = document.createElement("div");
  addT.className = "clip textclip";
  addT.style.width = "auto";
  addT.textContent = "+ text";
  addT.onclick = () => {
    proj.timeline.texts.push({
      id: "t" + Date.now(), text: "TITLE", start: 0.5, end: 3,
      style: { size: 72, color: "white", y: 0.5, border: 6 }, fade: 0.3 });
    sel = { kind: "text", index: proj.timeline.texts.length - 1 };
    renderAll();
  };
  tt.appendChild(addT);

  const tm = $("trackMusic");
  tm.innerHTML = "";
  proj.timeline.music.forEach((m, i) => {
    const el = document.createElement("div");
    el.className = "clip musicclip" + (sel && sel.kind === "music" && sel.index === i ? " sel" : "");
    el.style.width = "auto";
    el.textContent = "♪ " + m.asset + (m.duck ? " (duck)" : "");
    el.onclick = () => { sel = { kind: "music", index: i }; renderAll(); };
    tm.appendChild(el);
  });
}

function renderAssets() {
  const box = $("assetList");
  box.innerHTML = "";
  Object.entries(proj.assets).forEach(([id, a]) => {
    const el = document.createElement("div");
    el.className = "asset";
    el.innerHTML = `<b>${id}</b> — ${a.path}`;
    box.appendChild(el);
  });
}

/* ---------------- inspector ---------------- */

function field(label, value, onchange, type = "number", step = "0.1") {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const l = document.createElement("label");
  l.textContent = label;
  const inp = document.createElement("input");
  inp.type = type;
  if (type === "number") inp.step = step;
  inp.value = value ?? "";
  inp.onchange = () => onchange(type === "number" ? parseFloat(inp.value) : inp.value);
  wrap.append(l, inp);
  return wrap;
}

function selectField(label, value, options, onchange) {
  const wrap = document.createElement("div");
  wrap.className = "field";
  const l = document.createElement("label");
  l.textContent = label;
  const s = document.createElement("select");
  ["", ...options].forEach((o) => {
    const op = document.createElement("option");
    op.value = o; op.textContent = o || "(none)";
    if ((value || "") === o) op.selected = true;
    s.appendChild(op);
  });
  s.onchange = () => onchange(s.value || null);
  wrap.append(l, s);
  return wrap;
}

function renderInspector() {
  const body = $("insBody");
  body.innerHTML = "";
  if (!sel) { $("insTitle").textContent = "Nothing selected"; return; }

  if (sel.kind === "clip") {
    const c = proj.timeline.video[sel.index];
    if (!c) { sel = null; return renderInspector(); }
    $("insTitle").textContent = `Clip ${c.id}`;
    const r2 = document.createElement("div"); r2.className = "row2";
    r2.append(
      field("In (s)", c.in, (v) => { c.in = v; renderAll(); }),
      field("Out (s)", c.out, (v) => { c.out = v; renderAll(); }));
    body.appendChild(r2);
    body.appendChild(field("Speed", c.speed ?? 1, (v) => { c.speed = v; renderAll(); }));
    body.appendChild(selectField("Transition out", c.transition_out?.type,
      meta.transitions, (v) => {
        c.transition_out = v ? { type: v, duration: c.transition_out?.duration || 0.5 } : null;
        renderAll();
      }));
    if (c.transition_out)
      body.appendChild(field("Transition secs", c.transition_out.duration,
        (v) => { c.transition_out.duration = v; renderAll(); }));
    body.appendChild(selectField("Look", c.color?.look, meta.looks, (v) => {
      c.color = c.color || {}; c.color.look = v; renderAll();
    }));
    const r3 = document.createElement("div"); r3.className = "row2";
    r3.append(
      field("Contrast", c.color?.contrast ?? 1, (v) => { c.color = c.color || {}; c.color.contrast = v; }),
      field("Saturation", c.color?.saturation ?? 1, (v) => { c.color = c.color || {}; c.color.saturation = v; }));
    body.appendChild(r3);
    const r4 = document.createElement("div"); r4.className = "row2";
    r4.append(
      field("Fade in (s)", c.fade_in ?? 0, (v) => { c.fade_in = v; }),
      field("Fade out (s)", c.fade_out ?? 0, (v) => { c.fade_out = v; }));
    body.appendChild(r4);

    const controls = document.createElement("div"); controls.className = "row2";
    const split = document.createElement("button");
    split.textContent = "Split in half";
    split.onclick = () => {
      const mid = (c.in + c.out) / 2;
      const c2 = JSON.parse(JSON.stringify(c));
      c2.id = c.id + "b"; c2.in = mid; c.out = mid;
      proj.timeline.video.splice(sel.index + 1, 0, c2);
      renderAll();
    };
    const del = document.createElement("button");
    del.textContent = "Delete"; del.className = "danger";
    del.onclick = () => { proj.timeline.video.splice(sel.index, 1); sel = null; renderAll(); };
    controls.append(split, del);
    body.appendChild(controls);
    const move = document.createElement("div"); move.className = "row2";
    const left = document.createElement("button"); left.textContent = "← Move";
    left.onclick = () => {
      if (sel.index > 0) {
        const [x] = proj.timeline.video.splice(sel.index, 1);
        proj.timeline.video.splice(sel.index - 1, 0, x);
        sel.index--; renderAll();
      }
    };
    const right = document.createElement("button"); right.textContent = "Move →";
    right.onclick = () => {
      if (sel.index < proj.timeline.video.length - 1) {
        const [x] = proj.timeline.video.splice(sel.index, 1);
        proj.timeline.video.splice(sel.index + 1, 0, x);
        sel.index++; renderAll();
      }
    };
    move.append(left, right);
    body.appendChild(move);
  }

  if (sel.kind === "text") {
    const t = proj.timeline.texts[sel.index];
    if (!t) { sel = null; return renderInspector(); }
    $("insTitle").textContent = `Text ${t.id}`;
    body.appendChild(field("Text", t.text, (v) => { t.text = v; renderAll(); }, "text"));
    const r = document.createElement("div"); r.className = "row2";
    r.append(
      field("Start (s)", t.start, (v) => { t.start = v; renderAll(); }),
      field("End (s)", t.end, (v) => { t.end = v; renderAll(); }));
    body.appendChild(r);
    const r2 = document.createElement("div"); r2.className = "row2";
    r2.append(
      field("Size", t.style?.size ?? 64, (v) => { t.style = t.style || {}; t.style.size = v; }, "number", "1"),
      field("Y (0-1)", t.style?.y ?? 0.85, (v) => { t.style = t.style || {}; t.style.y = v; }));
    body.appendChild(r2);
    body.appendChild(field("Color", t.style?.color ?? "white", (v) => { t.style.color = v; }, "text"));
    const del = document.createElement("button");
    del.textContent = "Delete"; del.className = "danger";
    del.onclick = () => { proj.timeline.texts.splice(sel.index, 1); sel = null; renderAll(); };
    body.appendChild(del);
  }

  if (sel.kind === "music") {
    const m = proj.timeline.music[sel.index];
    if (!m) { sel = null; return renderInspector(); }
    $("insTitle").textContent = `Music ${m.id}`;
    const r = document.createElement("div"); r.className = "row2";
    r.append(
      field("Volume", m.volume ?? 1, (v) => { m.volume = v; }),
      field("Start (s)", m.start ?? 0, (v) => { m.start = v; }));
    body.appendChild(r);
    const r2 = document.createElement("div"); r2.className = "row2";
    r2.append(
      field("Fade in", m.fade_in ?? 0, (v) => { m.fade_in = v; }),
      field("Fade out", m.fade_out ?? 0, (v) => { m.fade_out = v; }));
    body.appendChild(r2);
    const duck = document.createElement("button");
    duck.textContent = m.duck ? "Ducking: ON" : "Ducking: off";
    duck.onclick = () => { m.duck = !m.duck; renderInspector(); };
    body.appendChild(duck);
    const del = document.createElement("button");
    del.textContent = "Delete"; del.className = "danger";
    del.onclick = () => { proj.timeline.music.splice(sel.index, 1); sel = null; renderAll(); };
    body.appendChild(del);
  }
}

/* ---------------- actions ---------------- */

async function save() {
  await api("/api/project", { method: "POST", body: JSON.stringify(proj) });
  $("projDur").textContent = totalDur().toFixed(1) + "s";
}

async function render(mode) {
  const btn = mode === "preview" ? $("btnPreview") : $("btnFinal");
  const old = btn.textContent;
  btn.textContent = "Rendering…"; btn.disabled = true;
  try {
    await save();
    const res = await api("/api/render", { method: "POST", body: JSON.stringify({ mode }) });
    const v = $("player");
    v.src = res.output + "?t=" + Date.now();
    $("renderMsg").classList.add("hidden");
    v.play().catch(() => {});
  } catch (e) {
    alert(e.message);
  } finally {
    btn.textContent = old; btn.disabled = false;
  }
}

function tryLoadPreview() {
  const v = $("player");
  const url = `/render/${proj.name}_preview.mp4`;
  fetch(url, { method: "HEAD" }).then((r) => {
    if (r.ok) { v.src = url; $("renderMsg").classList.add("hidden"); }
  }).catch(() => {});
}

$("btnSave").onclick = () => save().catch((e) => alert(e.message));
$("btnPreview").onclick = () => render("preview");
$("btnFinal").onclick = () => render("final");

boot().catch((e) => alert("Failed to load project: " + e.message));
