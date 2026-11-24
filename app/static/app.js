const $ = (id) => document.getElementById(id);
const state = { presets: null, niche: null, platform: null, currentJob: null, poll: null };
const enabledPlatforms = () => Object.entries(state.presets.platforms).filter(([, p]) => p.enabled !== false);

const fmtDuration = (s) => (s < 60 ? `${s}s` : s % 60 ? `${Math.floor(s / 60)}m${s % 60}s` : `${s / 60} min`);

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
    throw new Error(detail || `Erro ${res.status}`);
  }
  return data;
}

function chip(label, active, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "chip" + (active ? " active" : "");
  b.textContent = label;
  b.onclick = onClick;
  return b;
}

// ---------------- formulário ----------------

function renderNiches() {
  const box = $("niches");
  box.innerHTML = "";
  for (const [key, n] of Object.entries(state.presets.niches)) {
    box.appendChild(chip(n.label, key === state.niche, () => selectNiche(key)));
  }
}

function selectNiche(key) {
  state.niche = key;
  const n = state.presets.niches[key];
  if (n.default_tone) $("tone").value = n.default_tone;
  renderNiches();
}

function renderPlatforms() {
  const box = $("platforms");
  box.innerHTML = "";
  const platforms = enabledPlatforms();
  box.style.gridTemplateColumns = `repeat(${platforms.length}, 1fr)`;
  for (const [key, p] of platforms) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = p.label.replace(" (16:9)", "");
    b.className = key === state.platform ? "active" : "";
    b.onclick = () => selectPlatform(key);
    box.appendChild(b);
  }
}

function selectPlatform(key) {
  state.platform = key;
  const p = state.presets.platforms[key];
  $("duration").value = p.default_duration;
  $("duration").max = p.max_duration || 1800;
  renderPlatforms();
  renderDurations();
}

function renderDurations() {
  const box = $("durations");
  box.innerHTML = "";
  const current = Number($("duration").value);
  for (const d of state.presets.platforms[state.platform].durations) {
    box.appendChild(chip(fmtDuration(d), d === current, () => { $("duration").value = d; renderDurations(); }));
  }
}

function renderVoices() {
  const engine = $("engine").value;
  const lang = $("language").value;
  const voices = (state.presets.voices[engine] || {})[lang] || [];
  $("voice").innerHTML = voices.map((v) => `<option value="${v.id}">${v.label}</option>`).join("");
}

function fillSelect(id, entries) {
  $(id).innerHTML = entries.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
}

async function loadHealth() {
  const h = await api("/api/health");
  const items = [
    [`IA: ${h.llm}`, h.llm_ready], ["ffmpeg", h.ffmpeg],
    // Vídeos stock exigem Pixabay ou Pexels; sem eles, só fotos do Openverse
    [h.pixabay || h.pexels ? "Vídeos stock" : "Só fotos (Openverse)", h.pixabay || h.pexels],
    ["ElevenLabs", h.elevenlabs], ["YouTube", h.youtube],
  ];
  $("health").innerHTML = items.map(([n, ok]) => `<span class="${ok ? "ok" : "bad"}"></span>`).join("");
  [...$("health").children].forEach((el, i) => (el.textContent = items[i][0]));
  $("health").title = "Abra Configurações para ajustar";

  const banner = $("setupBanner");
  banner.hidden = h.llm_ready;
  if (!h.llm_ready) {
    banner.innerHTML = 'Nenhuma IA pronta para escrever roteiros. Use a <b>IA local grátis</b> (Ollama) ou cole sua chave da Anthropic. <button class="link" type="button">Abrir configurações</button>';
    banner.querySelector("button").onclick = openSettings;
  }
}

// ---------------- configurações ----------------

const KEY_INFO = {
  ANTHROPIC_API_KEY: ["Anthropic", "https://console.anthropic.com/settings/keys"],
  PIXABAY_API_KEY: ["Pixabay", "https://pixabay.com/api/docs/"],
  PEXELS_API_KEY: ["Pexels", "https://www.pexels.com/api/"],
  ELEVENLABS_API_KEY: ["ElevenLabs", "https://elevenlabs.io/app/settings/api-keys"],
};
const clearKeys = new Set();

function renderSettings(s) {
  document.querySelectorAll('input[name="llm"]').forEach((r) => (r.checked = r.value === s.llm_provider));

  $("ollamaStatus").textContent = s.ollama_running ? "rodando" : "não encontrado";
  $("ollamaStatus").className = `badge ${s.ollama_running ? "done" : "error"}`;
  $("ollamaMissing").hidden = s.ollama_running;
  $("pullModel").disabled = !s.ollama_running;

  const options = new Map();
  s.ollama_models.forEach((m) => options.set(m, `${m} ✓ instalado`));
  s.recommended_models.forEach((m) => { if (!options.has(m.id)) options.set(m.id, m.label); });
  if (!options.has(s.ollama_model)) options.set(s.ollama_model, s.ollama_model);
  $("ollamaModel").innerHTML = "";
  for (const [id, label] of options) {
    const o = document.createElement("option");
    o.value = id;
    o.textContent = label;
    o.selected = id === s.ollama_model;
    $("ollamaModel").appendChild(o);
  }
  const updatePullBtn = () => {
    const installed = s.ollama_models.includes($("ollamaModel").value);
    $("pullModel").textContent = installed ? "Instalado" : "Baixar";
    $("pullModel").disabled = !s.ollama_running || installed;
  };
  $("ollamaModel").onchange = updatePullBtn;
  updatePullBtn();

  clearKeys.clear();
  $("keyFields").innerHTML = "";
  for (const [key, [label, url]] of Object.entries(KEY_INFO)) {
    const row = document.createElement("div");
    row.className = "key-row";
    row.innerHTML = `<label></label><input type="password" autocomplete="off" /><span></span>`;
    row.querySelector("label").textContent = label;
    const input = row.querySelector("input");
    input.dataset.key = key;
    input.placeholder = s.keys[key] ? `${s.keys[key]} (deixe vazio para manter)` : "não configurada";
    const side = row.querySelector("span");
    if (s.keys[key]) {
      const rm = document.createElement("button");
      rm.type = "button";
      rm.className = "copy";
      rm.textContent = "Remover";
      rm.onclick = () => { clearKeys.add(key); input.value = ""; input.placeholder = "será removida ao salvar"; };
      side.appendChild(rm);
    } else {
      side.innerHTML = `<a href="${url}" target="_blank" rel="noopener">obter</a>`;
    }
    $("keyFields").appendChild(row);
  }
}

async function openSettings() {
  $("settingsMsg").textContent = "";
  renderSettings(await api("/api/settings"));
  $("settings").showModal();
  pollPull();
}

async function saveSettings() {
  const keys = {};
  document.querySelectorAll("#keyFields input").forEach((i) => { if (i.value.trim()) keys[i.dataset.key] = i.value.trim(); });
  const llm = document.querySelector('input[name="llm"]:checked');
  try {
    const s = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        llm_provider: llm ? llm.value : null,
        ollama_model: $("ollamaModel").value,
        keys,
        clear_keys: [...clearKeys],
      }),
    });
    renderSettings(s);
    $("settingsMsg").textContent = "✓ Salvo.";
    loadHealth();
  } catch (err) {
    $("settingsMsg").textContent = err.message;
  }
}

let pullTimer = null;

function renderPull(p) {
  const active = p.status === "pulling";
  $("pullBarWrap").hidden = !active;
  $("pullBar").style.width = `${p.percent}%`;
  $("pullStatus").textContent =
    active ? `Baixando ${p.model}… ${p.percent}%` :
    p.status === "done" ? `✓ ${p.model} instalado.` :
    p.status === "error" ? `Erro: ${p.error}` : "";
  return active;
}

async function pollPull() {
  clearTimeout(pullTimer);
  const p = await api("/api/ollama/pull");
  if (renderPull(p)) {
    pullTimer = setTimeout(pollPull, 1000);
  } else if (p.status === "done") {
    renderSettings(await api("/api/settings"));
    loadHealth();
  }
}

async function pullModel() {
  try {
    await api("/api/ollama/pull", { method: "POST", body: JSON.stringify({ model: $("ollamaModel").value }) });
    // Já seleciona o modelo que está sendo baixado
    await api("/api/settings", { method: "POST", body: JSON.stringify({ ollama_model: $("ollamaModel").value }) });
    pollPull();
  } catch (err) {
    $("pullStatus").textContent = err.message;
  }
}

async function init() {
  state.presets = await api("/api/presets");
  fillSelect("language", Object.entries(state.presets.languages));
  fillSelect("tone", Object.keys(state.presets.tones).map((t) => [t, t[0].toUpperCase() + t.slice(1)]));
  state.niche = Object.keys(state.presets.niches)[0];
  selectNiche(state.niche);
  selectPlatform(enabledPlatforms()[0][0]);
  renderVoices();
  $("engine").onchange = renderVoices;
  $("language").onchange = renderVoices;
  $("duration").oninput = () => { renderDurations(); updateBriefInfo(); };
  $("idea").onclick = () => {
    const ideas = state.presets.niches[state.niche].ideas || [];
    if (ideas.length) $("prompt").value = ideas[Math.floor(Math.random() * ideas.length)];
  };
  $("form").onsubmit = submit;
  setupGuided();
  $("openSettings").onclick = openSettings;
  $("saveSettings").onclick = saveSettings;
  $("pullModel").onclick = pullModel;
  $("upload").onclick = upload;
  document.querySelectorAll(".copy").forEach((b) => {
    b.onclick = () => {
      navigator.clipboard.writeText($(b.dataset.copy).textContent);
      b.textContent = "Copiado!";
      setTimeout(() => (b.textContent = "Copiar"), 1200);
    };
  });
  loadHealth().catch(() => {});
  await refreshHistory();
}

// ---------------- roteiro guiado ----------------

const BRIEF_FIELDS = { topic: "bTopic", hook: "bHook", twist: "bTwist", ending: "bEnding" };
const looksLikeBrief = (text) => /(^|\n)\s*(gancho|fatos|virada|final)\s*:/i.test(text);
let lastBrief = null;

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("#modeSwitch button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("freeMode").hidden = mode !== "free";
  $("guidedMode").hidden = mode !== "guided";
  updateBriefInfo();
}

function readBrief() {
  const b = { facts: $("bFacts").value.split("\n").map((l) => l.replace(/^\s*[-•*–]\s*/, "").trim()).filter(Boolean) };
  for (const [k, id] of Object.entries(BRIEF_FIELDS)) b[k] = $(id).value.trim();
  return b;
}

function fillBrief(b) {
  for (const [k, id] of Object.entries(BRIEF_FIELDS)) $(id).value = b[k] || "";
  $("bFacts").value = (b.facts || []).join("\n");
}

async function updateBriefInfo() {
  if (state.mode !== "guided") return;
  const b = readBrief();
  const info = $("briefInfo");
  if (!b.hook && !b.facts.length && !b.ending) { info.textContent = ""; return; }
  try {
    const r = await api("/api/brief", { method: "POST", body: JSON.stringify({ brief: b }) });
    lastBrief = r;
    const current = Number($("duration").value);
    const rec = r.recommended_seconds;
    const summary = `${b.facts.length} fato(s) · gancho ${b.hook ? "✓" : "—"} · final ${b.ending ? "✓" : "—"} · ~${r.words} palavras`;
    if (rec && current < rec) {
      info.className = "hint warn";
      info.innerHTML = `${summary}. ⚠ Não cabe em ${fmtDuration(current)}: recomendado ${fmtDuration(rec)}.`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy";
      btn.textContent = `Usar ${fmtDuration(rec)}`;
      btn.onclick = () => { $("duration").value = rec; renderDurations(); updateBriefInfo(); };
      info.appendChild(btn);
    } else {
      info.className = "hint";
      info.textContent = `${summary}. Cabe em ${fmtDuration(current)}.`;
    }
  } catch (err) {
    info.textContent = err.message;
  }
}

async function absorbPastedBrief(text) {
  if (!looksLikeBrief(text)) return false;
  const r = await api("/api/brief", { method: "POST", body: JSON.stringify({ text }) });
  if (!r.brief) return false;
  fillBrief(r.brief);
  setMode("guided");
  if (r.recommended_seconds && Number($("duration").value) < r.recommended_seconds) {
    $("duration").value = r.recommended_seconds;
    renderDurations();
  }
  updateBriefInfo();
  return true;
}

function setupGuided() {
  state.mode = "free";
  document.querySelectorAll("#modeSwitch button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  let timer = null;
  const debounced = () => { clearTimeout(timer); timer = setTimeout(updateBriefInfo, 400); };
  ["bHook", "bFacts", "bTwist", "bEnding"].forEach((id) => ($(id).oninput = debounced));
  // Colar um briefing inteiro no campo de ideia ou de tema preenche os campos guiados
  for (const id of ["prompt", "bTopic"]) {
    $(id).addEventListener("paste", () => setTimeout(() => absorbPastedBrief($(id).value), 0));
  }
}

async function submit(e) {
  e.preventDefault();
  $("formError").hidden = true;
  $("submit").disabled = true;
  const body = {
    prompt: state.mode === "guided" ? $("bTopic").value : $("prompt").value,
    brief: state.mode === "guided" ? readBrief() : null,
    niche: state.niche,
    platform: state.platform,
    duration_seconds: Number($("duration").value),
    language: $("language").value,
    tone: $("tone").value,
    voice_engine: $("engine").value,
    voice: $("voice").value || null,
    captions: $("captions").checked,
    music: $("music").checked,
    cta: $("cta").checked,
    extra_instructions: $("extra").value,
  };
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(body) });
    showJob(job);
    refreshHistory();
  } catch (err) {
    $("formError").textContent = err.message;
    $("formError").hidden = false;
  } finally {
    $("submit").disabled = false;
  }
}

// ---------------- job / resultado ----------------

const STATUS = { queued: "Na fila", running: "Gerando", done: "Pronto", error: "Erro" };

function showJob(job) {
  state.currentJob = job.id;
  $("empty").hidden = true;
  $("job").hidden = false;
  renderJob(job);
  clearInterval(state.poll);
  if (job.status === "queued" || job.status === "running" || (job.upload_status || "").startsWith("Enviando")) {
    state.poll = setInterval(async () => {
      const j = await api(`/api/jobs/${job.id}`);
      if (state.currentJob !== j.id) return;
      renderJob(j);
      const busy = j.status === "queued" || j.status === "running" || (j.upload_status || "").startsWith("Enviando");
      if (!busy) { clearInterval(state.poll); refreshHistory(); }
    }, 1500);
  }
  document.querySelectorAll("#history li").forEach((li) => li.classList.toggle("active", li.dataset.id === job.id));
}

let renderedResultFor = null;

function renderJob(job) {
  $("jobTitle").textContent = job.title || job.request.prompt || state.presets.niches[job.request.niche]?.label || "Vídeo";
  $("jobBadge").textContent = STATUS[job.status] || job.status;
  $("jobBadge").className = `badge ${job.status}`;
  $("bar").style.width = `${job.progress}%`;
  $("jobStep").textContent = job.step;
  $("jobLog").textContent = job.log.join("\n");
  $("jobError").hidden = !job.error;
  $("jobError").textContent = job.error || "";
  $("uploadStatus").innerHTML = job.youtube_id
    ? `Publicado: <a href="https://youtu.be/${job.youtube_id}" target="_blank" rel="noopener">youtu.be/${job.youtube_id}</a>`
    : job.upload_status || "";

  const done = job.status === "done";
  $("result").hidden = !done;
  if (done && renderedResultFor !== job.id) {
    renderedResultFor = job.id;
    const base = `/api/jobs/${job.id}`;
    const vertical = state.presets.platforms[job.request.platform]?.orientation === "vertical";
    document.querySelector(".media").classList.toggle("vertical", vertical);
    $("player").src = `${base}/video`;
    $("thumb").src = `${base}/thumbnail`;
    $("dlVideo").href = `${base}/video?download=true`;
    $("dlThumb").href = `${base}/thumbnail?download=true`;
    $("dlPost").href = `${base}/post?download=true`;
    const m = job.metadata || {};
    // Instagram/TikTok: não há título nem tags; a "descrição" é a legenda do post
    const social = ["reels", "tiktok"].includes(job.request.platform);
    $("boxTitle").hidden = social;
    $("boxTags").hidden = social;
    $("publishBox").hidden = social;
    $("igHint").hidden = job.request.platform !== "reels";
    $("descLabel").textContent = social ? "Legenda do post" : "Descrição";
    $("mTitle").textContent = m.title || "";
    $("mDesc").textContent = m.description || "";
    $("mHash").textContent = (m.hashtags || []).join(" ");
    $("mTags").textContent = (m.tags || []).join(", ");
  }
}

async function upload() {
  if (!state.currentJob) return;
  try {
    await api(`/api/jobs/${state.currentJob}/youtube`, {
      method: "POST",
      body: JSON.stringify({ privacy: $("privacy").value }),
    });
    $("uploadStatus").textContent = "Iniciando upload… (uma janela de login do Google pode abrir)";
    showJob(await api(`/api/jobs/${state.currentJob}`));
  } catch (err) {
    $("uploadStatus").textContent = err.message;
  }
}

async function refreshHistory() {
  const jobs = await api("/api/jobs");
  const ul = $("history");
  ul.innerHTML = "";
  if (!jobs.length) ul.innerHTML = '<li class="muted">Nenhum vídeo ainda</li>';
  for (const j of jobs) {
    const li = document.createElement("li");
    li.dataset.id = j.id;
    const plat = state.presets.platforms[j.request.platform]?.label || j.request.platform;
    li.innerHTML = `<span class="t"></span><span class="s">${STATUS[j.status]} · ${plat} · ${fmtDuration(j.request.duration_seconds)}</span>`;
    li.querySelector(".t").textContent = j.title || j.request.prompt || "(tema automático)";
    li.onclick = () => showJob(j);
    if (j.id === state.currentJob) li.classList.add("active");
    ul.appendChild(li);
  }
}

init();
