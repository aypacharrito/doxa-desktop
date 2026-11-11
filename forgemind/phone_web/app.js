/* Doxa phone app. Talks only to the Doxa on your PC (through your Cloudflare link).
   All server text is inserted with textContent. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
    del: (k) => { try { localStorage.removeItem(k); } catch { /* private mode */ } },
  };

  // The access key arrives once in the link's #fragment (never sent to any server), then is kept on this phone.
  const fragment = new URLSearchParams(location.hash.slice(1));
  if (fragment.get("k")) {
    store.set("jarvis.key", fragment.get("k"));
    history.replaceState(null, "", location.pathname);
  }
  // Opening a new link while Doxa is already open only changes the #fragment; reload to pick it up.
  window.addEventListener("hashchange", () => { if (location.hash.includes("k=")) location.reload(); });
  let key = store.get("jarvis.key");
  let busy = false, lastPending = null, browserTimer = null, lastLogLength = 0;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c instanceof Node ? c : String(c));
    return node;
  }

  function toast(text) {
    const t = $("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (t.hidden = true), 3500);
  }

  async function api(path, body) {
    const res = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + key },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch { /* empty */ }
    if (res.status === 401 || res.status === 429) lock(data.error);
    if (!res.ok) throw new Error(data.error || `Doxa didn't answer (${res.status}).`);
    return data;
  }

  function lock(reason) {
    if (reason) store.del("jarvis.key");
    key = store.get("jarvis.key");
    $("main").hidden = $("composer").hidden = true;
    $("locked").hidden = false;
    $("locked-reason").textContent = reason || "";
  }

  function orb(state) {
    $("orb").className = "orb " + (state || "");
  }

  // Chat ---------------------------------------------------------------------------
  const messages = $("messages");
  function add(role, text, note) {
    $("hero").classList.add("compact");
    const node = el("div", { class: "msg " + role }, text, note ? el("span", { class: "note" }, note) : null);
    messages.append(node);
    node.scrollIntoView({ block: "end", behavior: "smooth" });
    return node;
  }

  async function loadHistory() {
    try {
      const { messages: list } = await api("/api/history");
      messages.replaceChildren();
      for (const m of list.slice(-30)) add(m.role === "user" ? "user" : "assistant", m.content);
      if (!list.length) $("hero").classList.remove("compact");
    } catch (err) { /* status line shows connection problems */ }
  }

  function offerBrowserTask(task) {
    const box = el("textarea", { rows: "3" });
    box.value = task;
    const card = el("div", { class: "card" },
      el("strong", {}, "Start a browser task?"),
      el("p", { class: "muted" }, "Doxa works in its own browser window on your PC, asks you here for details, and waits for your OK before booking or submitting."),
      box,
      el("div", { class: "row" },
        el("button", { class: "btn primary", type: "button", onclick: async () => {
          try { await api("/api/browser/start", { task: box.value }); card.remove(); pollBrowser(); }
          catch (err) { toast(err.message); }
        } }, "Start"),
        el("button", { class: "btn", type: "button", onclick: () => card.remove() }, "Not now")));
    messages.append(card);
    card.scrollIntoView({ block: "end", behavior: "smooth" });
  }

  const input = $("input");
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });

  $("composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true;
    $("send").disabled = true;
    input.value = ""; input.style.height = "auto";
    add("user", text);
    const pending = add("assistant", "");
    pending.classList.add("pending");
    pending.textContent = "…";
    orb("thinking");
    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer " + key },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        let data = {};
        try { data = await res.json(); } catch { /* empty */ }
        if (res.status === 401 || res.status === 429) lock(data.error);
        throw new Error(data.error || `Doxa didn't answer (${res.status}).`);
      }
      // Words appear as soon as the model writes them.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "", shown = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, nl); buffer = buffer.slice(nl + 1);
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === "token") {
            shown += ev.text;
            pending.classList.remove("pending");
            pending.textContent = shown;
            pending.scrollIntoView({ block: "end" });
          } else if (ev.type === "status") {
            if (!shown) pending.textContent = ev.text;
          } else if (ev.type === "offer") {
            pending.classList.remove("pending");
            pending.textContent = ev.reply;
            offerBrowserTask(ev.task);
          } else if (ev.type === "done") {
            pending.classList.remove("pending");
            pending.replaceChildren(ev.reply, ev.note ? el("span", { class: "note" }, ev.note) : "");
          } else if (ev.type === "error") {
            throw new Error(ev.error);
          }
        }
      }
    } catch (err) {
      pending.textContent = "⚠ " + err.message;
      pending.classList.remove("pending");
    } finally {
      busy = false;
      $("send").disabled = false;
      orb("");
      refreshStatus();
      setTimeout(pollCode, 1500);  // "codex: …" / "ask Claude Code to …" starts a job: show its card
    }
  });

  // Dictation where the phone's browser supports it.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Recognition) {
    const mic = $("mic");
    mic.hidden = false;
    let rec = null;
    mic.addEventListener("click", () => {
      if (rec) { rec.stop(); return; }
      rec = new Recognition();
      rec.interimResults = true;
      rec.lang = navigator.language || "en-US";
      const base = input.value;
      rec.onresult = (ev) => { input.value = base + Array.from(ev.results).map((r) => r[0].transcript).join(" "); };
      rec.onend = () => { rec = null; mic.textContent = "🎙"; mic.setAttribute("aria-label", "Start dictation"); mic.setAttribute("aria-pressed", "false"); };
      rec.onerror = () => toast("Dictation isn't available right now.");
      mic.textContent = "■";
      mic.setAttribute("aria-label", "Listening — stop dictation");
      mic.setAttribute("aria-pressed", "true");
      try { rec.start(); toast("Listening. Review your words before sending. Phone dictation may use your browser's speech service."); }
      catch (_) { rec = null; mic.textContent = "🎙"; mic.setAttribute("aria-pressed", "false"); mic.setAttribute("aria-label", "Start dictation"); toast("Microphone could not start."); }
    });
    const stopDictation = () => { if (rec) rec.stop(); };
    $("stop").addEventListener("click", stopDictation);
    document.addEventListener("visibilitychange", () => { if (document.hidden) stopDictation(); });
    window.addEventListener("pagehide", stopDictation);
  }

  // Browser task card ------------------------------------------------------------------
  function renderPending(p) {
    const box = $("pending");
    if (!p) { box.hidden = true; box.replaceChildren(); lastPending = null; return; }
    if (lastPending === p.id) return;
    lastPending = p.id;
    box.hidden = false;
    if (navigator.vibrate) navigator.vibrate(120);
    const reply = async (value) => {
      try { await api("/api/browser/respond", { id: p.id, value }); } catch (err) { toast(err.message); }
      pollBrowser();
    };
    if (p.kind === "ask") {
      const field = el("input", { type: "text", autocomplete: "off" });
      const remember = el("input", { type: "checkbox" });
      const send = () => field.value.trim() && reply([field.value.trim(), remember.checked]);
      field.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
      box.replaceChildren(el("h3", {}, "Doxa asks: " + p.text), field,
        el("label", {}, remember, "Remember this for next time"),
        el("div", { class: "row" }, el("button", { class: "btn primary", type: "button", onclick: send }, "Answer"),
          el("button", { class: "btn", type: "button", onclick: () => reply(null) }, "Skip — stop the task")));
      field.focus();
    } else if (p.kind === "hand_off") {
      box.replaceChildren(el("h3", {}, "Your turn"), el("p", {}, p.text),
        el("p", { class: "muted" }, "This step has to be done at your PC, in Doxa's browser window."),
        el("div", { class: "row" }, el("button", { class: "btn primary", type: "button", onclick: () => reply(true) }, "Done — continue"),
          el("button", { class: "btn", type: "button", onclick: () => reply(false) }, "Stop task")));
    } else {
      box.replaceChildren(el("h3", {}, "Approve? " + p.title), el("pre", {}, p.body),
        el("div", { class: "row" }, el("button", { class: "btn primary", type: "button", onclick: () => reply(true) }, "Approve"),
          el("button", { class: "btn danger", type: "button", onclick: () => reply(false) }, "Decline — submit nothing")));
    }
  }

  async function pollBrowser() {
    clearTimeout(browserTimer);
    let s;
    try { s = await api("/api/browser"); } catch { browserTimer = setTimeout(pollBrowser, 5000); return; }
    const card = $("task");
    if (!s.running && !s.result && !s.task) { card.hidden = true; return; }
    card.hidden = false;
    $("task-goal").textContent = s.task;
    const dot = $("task-dot");
    if (s.running) {
      $("task-title").textContent = s.pending ? "Browser task · needs you" : s.paused ? "Browser task · paused" : "Browser task · working";
      dot.className = "dot " + (s.pending ? "wait" : "on");
      orb(s.pending ? "waiting" : "working");
    } else if (s.result) {
      const label = { completed: "Done", needs_input: "Needs you", stopped: "Stopped", error: "Couldn't finish" }[s.result.status] || s.result.status;
      $("task-title").textContent = "Browser task · " + label;
      dot.className = "dot " + (s.result.status === "completed" ? "done" : "wait");
      if (!busy) orb("");
    }
    const result = $("task-result");
    result.hidden = !(s.result && s.result.message);
    if (s.result && s.result.message) {
      result.textContent = s.result.message;
      result.className = "task-result " + (s.result.status === "completed" ? "done" : "attention");
    }
    if (s.log.length !== lastLogLength) {
      lastLogLength = s.log.length;
      $("task-log").replaceChildren(...s.log.slice(-6).map((line) => el("li", {}, line)));
      $("task-log").scrollTop = $("task-log").scrollHeight;
    }
    renderPending(s.pending);
    if (s.running) browserTimer = setTimeout(pollBrowser, s.pending ? 2500 : 1500);
  }

  // Status + Stop ---------------------------------------------------------------------
  async function refreshStatus() {
    try {
      const s = await api("/api/status");
      $("meta").textContent = `${s.model_loaded ? s.model : "Model loading…"} · ${s.pc}`;
      if (!busy && !s.browser_running) orb(s.model_loaded ? "" : "offline");
      if (s.browser_running) pollBrowser();
    } catch (err) {
      $("meta").textContent = "Can't reach Doxa — is your PC on?";
      orb("offline");
    }
  }

  $("stop").addEventListener("click", async () => {
    try { await api("/api/stop", {}); toast("Stopped."); } catch (err) { toast(err.message); }
    refreshStatus(); pollBrowser();
  });

  // Code mode (Codex / Claude Code on the PC) ---------------------------------------------
  let codeTimer = null, codeSteps = -1, codeEngines = "";
  async function pollCode() {
    clearTimeout(codeTimer);
    let s;
    try { s = await api("/api/code"); } catch { codeTimer = setTimeout(pollCode, 6000); return; }
    const names = Object.entries(s.engines || {});
    if (names.map((n) => n[0]).join() !== codeEngines) {
      codeEngines = names.map((n) => n[0]).join();
      $("code-engine").replaceChildren(el("option", { value: "auto" }, "Same / automatic"),
        ...names.map(([value, label]) => el("option", { value }, label)));
    }
    const job = s.job, card = $("code");
    if (!job) {  // nothing yet: offer the card so a job can be started from here
      card.hidden = !names.length;
      $("code-title").textContent = "Code mode";
      $("code-task").textContent = "Give Codex or Claude Code a job on your PC: build, fix, reverse-engineer anything.";
      return;
    }
    card.hidden = false;
    const label = { running: "working", done: "done", failed: "problem", stopped: "stopped" }[job.status] || job.status;
    $("code-title").textContent = `${job.name} · ${label}`;
    $("code-dot").className = "dot " + (job.status === "running" ? "on" : job.status === "done" ? "done" : "wait");
    $("code-task").textContent = job.task;
    $("code-stop").hidden = job.status !== "running";
    if (job.step_count !== codeSteps) {
      codeSteps = job.step_count;
      $("code-log").replaceChildren(...job.steps.slice(-25).map((line) => el("li", {}, line)));
      $("code-log").scrollTop = $("code-log").scrollHeight;
    }
    $("code-result").hidden = !job.report;
    $("code-result").textContent = job.report || "";
    $("code-result").className = "task-result " + (job.status === "done" ? "done" : "attention");
    if (job.status === "running") { orb("working"); codeTimer = setTimeout(pollCode, 2000); }
    else if (!busy) orb("");
  }
  $("code-send").addEventListener("click", async () => {
    const task = $("code-input").value.trim();
    if (!task) return;
    $("code-send").disabled = true;
    try {
      const r = await api("/api/code/start", { task, engine: $("code-engine").value, fresh: $("code-fresh").checked });
      $("code-input").value = ""; $("code-fresh").checked = false;
      toast(r.note || "Started."); codeSteps = -1; pollCode();
    } catch (err) { toast(err.message); }
    $("code-send").disabled = false;
  });
  $("code-stop").addEventListener("click", async () => {
    try { await api("/api/code/stop", {}); toast("Stopping Code mode…"); } catch (err) { toast(err.message); }
    setTimeout(pollCode, 800);
  });

  // Live view of the PC screen (view only, about one picture a second) --------------------
  let screenOn = false, screenUrl = "", screenZoom = false;
  async function screenLoop() {
    if (!screenOn || document.hidden) return;
    const started = Date.now();
    try {
      const width = Math.min(2560, Math.round((screenZoom ? 2 : 1) * window.innerWidth * (window.devicePixelRatio || 1)));
      const res = await fetch("/api/screen?w=" + width, { headers: { authorization: "Bearer " + key } });
      if (res.status === 401 || res.status === 429) { lock("This phone link is not valid."); return; }
      if (!res.ok) throw new Error("Screen unavailable (" + res.status + ")");
      const url = URL.createObjectURL(await res.blob());
      $("screen-img").src = url;
      if (screenUrl) URL.revokeObjectURL(screenUrl);
      screenUrl = url;
      $("screen-meta").textContent = "Live · " + new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
    } catch (err) { $("screen-meta").textContent = err.message || "Can't reach your PC"; }
    setTimeout(screenLoop, Math.max(250, 1000 - (Date.now() - started)));
  }
  $("screen-open").addEventListener("click", () => { screenOn = true; $("screen").hidden = false; screenLoop(); });
  $("screen-close").addEventListener("click", () => { screenOn = false; $("screen").hidden = true; });
  $("screen-zoom").addEventListener("click", () => {
    screenZoom = !screenZoom;
    $("screen-frame").classList.toggle("zoom", screenZoom);
    $("screen-zoom").textContent = screenZoom ? "Fit" : "Zoom";
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && screenOn) screenLoop(); });

  // Boot ----------------------------------------------------------------------------------
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  if (!key) { lock(""); return; }
  // Android with the Doxa app installed: one tap hands this connection to the app (doxa://connect).
  $("hq-open").addEventListener("click", () => { location.href = "hq.html"; });
  if (/Android/i.test(navigator.userAgent)) {
    const open = $("open-app");
    open.href = "doxa://connect?u=" + encodeURIComponent(location.origin) + "&k=" + encodeURIComponent(key);
    open.hidden = false;
  }
  refreshStatus();
  loadHistory();
  pollBrowser();
  pollCode();
  setInterval(() => { if (!document.hidden) refreshStatus(); }, 8000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refreshStatus(); pollBrowser(); pollCode(); } });
})();
