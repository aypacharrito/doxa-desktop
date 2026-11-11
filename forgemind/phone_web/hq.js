/* Doxa HQ: the owner's business as islands around Doxa's command island (GET /api/team every 2 s; all server text goes in
   with textContent). Five warehouses, one per money line (the owner 2026-11-09): AI Stores (dropshipping / Etsy / Shopify),
   AI Trading (paper), AI Arbitrage, Insurance (Pacifica) and Marketing Studio, each with a free research bot whose live
   feed is its "screen"; plus Research Lab (upgrade ideas Doxa reviews and builds in a safe copy), Code Forge, Knowledge
   Vault and Your Desk. Each worker is an original robot with anime-style touches, or the picture he drops in
   Documents\Doxa Team\characters. Light on purpose: no blur filters, few animations, panel redraws only on change. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const SVG = "http://www.w3.org/2000/svg";
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const session = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } },
  };
  const fragment = new URLSearchParams(location.hash.slice(1));
  if (fragment.get("k")) { store.set("jarvis.key", fragment.get("k")); history.replaceState(null, "", location.pathname); }
  const key = store.get("jarvis.key") || "";

  const W = 1360, H = 1200, CX = W / 2, CY = H / 2, RX = 540, RY = 480, ISLAND = 180, PRIME_SIZE = 250;
  const ANGLE = { stores: -162, trading: -129, arbitrage: -96, pacifica: -64, marketing: -31, stenos: 2, websites: 34, reverse: 67, lab: 100, code: 133, knowledge: 165 };
  const WAREHOUSES = ["stores", "trading", "arbitrage", "pacifica", "marketing", "stenos"];
  const pos = (k) => { const a = (ANGLE[k] ?? 0) * Math.PI / 180; return [CX + RX * Math.cos(a), CY + RY * Math.sin(a)]; };
  const INK = "#0b0b0d", BONE = "#f2ede4", BLOOD = "#e5383b", MUSTARD = "#f4c430";
  const EYE = { marketing: MUSTARD, stores: BLOOD, trading: BLOOD, arbitrage: "#9bd36b", lab: "#9bd36b", code: BLOOD, knowledge: MUSTARD, desk: MUSTARD, pacifica: MUSTARD, stenos: "#7fd4ff", websites: "#9bd36b" };
  const COMMAND = { key: "prime", name: "Command", worker: "Doxa", about: "Runs everything: sends every AI to work when its job is due, within your budgets. Never posts, sends, spends or trades." };
  let state = null, selected = "prime", isles = {}, busy = false, base = 1, focused = null, touring = null, panelSig = "";
  let threeOn = false;  // the WebGL world (hq3d.js) draws HQ when the device supports it; this file keeps data + panel
  const art = {};

  const el = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v; else if (k.startsWith("on")) node.addEventListener(k.slice(2), v); else node.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid instanceof Node ? kid : String(kid));
    return node;
  };
  const svg = (tag, attrs = {}) => { const n = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const toast = (text) => { const t = $("toast"); t.textContent = text; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), 3600); };
  const spans = (n) => Array.from({ length: n }, () => el("span"));
  const money = (n) => "$" + Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const usd = (n) => (n < 0 ? "-" : "") + "$" + Math.abs(Number(n || 0)).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dept = (k) => ((state && state.departments) || {})[k] || {};

  async function api(path, body) {
    const res = await fetch(path, { method: body ? "POST" : "GET", headers: { "content-type": "application/json", authorization: "Bearer " + key },
      body: body ? JSON.stringify(body) : undefined });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Doxa didn't answer (${res.status})`);
    return data;
  }

  // --- the crew: one original robot per island ---------------------------------------------------------------------
  function robot(k) {
    const c = EYE[k] || BLOOD;
    const s = svg("svg", { viewBox: "-20 -30 92 118", class: `hq-bot bot-${k}` });
    const add = (...nodes) => s.append(...nodes);
    add(svg("ellipse", { cx: 26, cy: 82, rx: 20, ry: 3.5, fill: "#000", opacity: ".55" }));
    if (k === "marketing") {  // a guardian spirit rises behind it (ゴゴゴ when it works)
      const ghost = svg("g", { class: "spirit", opacity: ".55" });
      ghost.append(svg("path", { d: "M6 -22 q20 -10 40 0 l4 26 q-24 10 -48 0z", fill: BLOOD }),
        svg("path", { d: "M-6 6 q32 -12 64 0 l-6 46 q-26 8 -52 0z", fill: BLOOD }),
        svg("rect", { x: 14, y: -14, width: 24, height: 7, rx: 3.5, fill: INK }));
      add(ghost);
    }
    if (k === "code") {  // scythe arm
      add(svg("rect", { x: 46, y: -26, width: 3.5, height: 100, rx: 1.5, fill: "#2b2a30", transform: "rotate(14 48 24)" }),
        svg("path", { d: "M50 -26 q-34 -6 -54 18 q22 -10 44 -2z", fill: BLOOD, stroke: INK, "stroke-width": "2" }));
    }
    if (k === "pacifica") {  // a guardian's shield
      add(svg("path", { d: "M-10 40 q12 -6 22 0 v18 q0 12 -11 18 q-11 -6 -11 -18z", fill: BONE, stroke: INK, "stroke-width": "2" }),
        svg("path", { d: "M1 46 v24 M-6 54 h14", stroke: BLOOD, "stroke-width": "3" }));
    }
    const body = svg("rect", { x: 12, y: 40, width: 28, height: 32, rx: 11, fill: "#1c1b20", stroke: BONE, "stroke-width": "1.6" });
    const stripe = svg("rect", { x: 23, y: 41, width: 6, height: 30, fill: BONE });
    const head = svg("rect", { x: 8, y: 10, width: 36, height: 30, rx: 13, fill: BONE, stroke: INK, "stroke-width": "2" });
    const visor = svg("rect", { x: 13, y: 18, width: 26, height: 13, rx: 6.5, fill: INK });
    const eyes = [svg("circle", { cx: 21, cy: 24.5, r: 2.8, fill: c }), svg("circle", { cx: 31, cy: 24.5, r: 2.8, fill: c })];
    const arms = [svg("rect", { x: 5, y: 44, width: 8, height: 20, rx: 4, fill: "#2b2a30", stroke: BONE, "stroke-width": "1.2" }),
      svg("rect", { x: 39, y: 44, width: 8, height: 20, rx: 4, fill: "#2b2a30", stroke: BONE, "stroke-width": "1.2" })];
    add(...arms, body, stripe, head, visor, ...eyes);
    if (k === "code") add(svg("path", { d: "M14 33 l4 -3 l4 3 l4 -3 l4 3 l4 -3 l4 3", stroke: BLOOD, "stroke-width": "1.4", fill: "none" }));
    if (k === "stores") {  // shopkeeper: striped awning hat + a box
      add(svg("path", { d: "M4 13 h44 l-4 -9 h-36z", fill: BLOOD, stroke: INK, "stroke-width": "1.5" }),
        svg("path", { d: "M12 4 v9 M20 4 v9 M28 4 v9 M36 4 v9 M44 4 v9", stroke: BONE, "stroke-width": "2" }),
        svg("rect", { x: 40, y: 52, width: 16, height: 14, fill: MUSTARD, stroke: INK, "stroke-width": "1.5" }));
    }
    if (k === "lab") {  // stitched, with a bolt through the head
      add(svg("rect", { x: -4, y: 21, width: 60, height: 5, rx: 2, fill: "#9a958c" }), svg("circle", { cx: -4, cy: 23.5, r: 4, fill: "#6b665e" }),
        svg("path", { d: "M14 12 l8 26 M18 18 l-4 2 M20 25 l-4 2 M22 32 l-4 2 M16 46 h20 M20 43 v6 M26 43 v6 M32 43 v6",
          stroke: INK, "stroke-width": "1.3", fill: "none" }));
    }
    if (k === "trading") {  // skull mask + three stripes, perfectly symmetrical
      visor.setAttribute("fill", BONE);
      eyes.forEach((e) => { e.setAttribute("r", "4"); e.setAttribute("fill", INK); });
      add(svg("path", { d: "M22 33 h8 M24 31 v4 M28 31 v4", stroke: INK, "stroke-width": "1.4" }),
        svg("path", { d: "M12 13 h10 M10 17 h9 M9 21 h7", stroke: INK, "stroke-width": "2", "stroke-linecap": "round" }));
    }
    if (k === "desk") {  // the boss: gold visor + crown
      visor.setAttribute("fill", MUSTARD);
      eyes.forEach((e) => e.setAttribute("fill", INK));
      add(svg("path", { d: "M14 10 l4 -9 l8 6 l8 -6 l4 9z", fill: MUSTARD, stroke: INK, "stroke-width": "1.2" }));
    }
    if (k === "knowledge") {  // a book under the arm, tall antenna
      add(svg("rect", { x: 40, y: 50, width: 14, height: 18, fill: BLOOD, stroke: INK, "stroke-width": "1.5" }),
        svg("rect", { x: 25, y: -2, width: 2, height: 12, fill: BONE }), svg("circle", { cx: 26, cy: -3, r: 3, fill: MUSTARD }));
    }
    if (k === "marketing") add(svg("rect", { x: 25, y: 0, width: 2, height: 10, fill: BONE }), svg("circle", { cx: 26, cy: 0, r: 3.2, fill: c }));
    if (k === "websites") {  // the builder: hard hat + a little browser window
      add(svg("path", { d: "M8 14 q18 -16 36 0 v3 h-36z", fill: MUSTARD, stroke: INK, "stroke-width": "1.5" }),
        svg("rect", { x: 40, y: 46, width: 20, height: 16, rx: 2, fill: BONE, stroke: INK, "stroke-width": "1.4" }),
        svg("path", { d: "M40 50 h20", stroke: INK, "stroke-width": "1.4" }), svg("circle", { cx: 43, cy: 48, r: 0.9, fill: BLOOD }));
    }
    if (k === "stenos") {  // the court reporter: a stenotype on a stand, paper tape, a padlock (private, on your GPU)
      add(svg("rect", { x: 30, y: 58, width: 26, height: 10, rx: 2, fill: "#2b2a30", stroke: BONE, "stroke-width": "1.4" }),
        svg("path", { d: "M33 61 h20 M33 64 h20", stroke: "#7fd4ff", "stroke-width": "1.4" }),
        svg("rect", { x: 41, y: 68, width: 3, height: 14, fill: "#2b2a30" }),
        svg("path", { d: "M54 58 q8 -10 2 -22 q-4 -6 4 -12", fill: "none", stroke: BONE, "stroke-width": "2", class: "tape" }),
        svg("rect", { x: 20, y: 50, width: 12, height: 9, rx: 2, fill: MUSTARD, stroke: INK, "stroke-width": "1.2" }),
        svg("path", { d: "M22 50 v-3 a4 4 0 0 1 8 0 v3", fill: "none", stroke: MUSTARD, "stroke-width": "1.6" }));
    }
    if (k === "arbitrage") {  // the dealer: tall hat and a coin flipping over one hand
      add(svg("rect", { x: 14, y: -10, width: 24, height: 20, rx: 2, fill: INK, stroke: BONE, "stroke-width": "1.4" }),
        svg("rect", { x: 8, y: 8, width: 36, height: 4, rx: 2, fill: INK, stroke: BONE, "stroke-width": "1.2" }),
        svg("rect", { x: 14, y: 2, width: 24, height: 3, fill: BLOOD }),
        svg("circle", { cx: 52, cy: 34, r: 5.5, fill: MUSTARD, stroke: INK, "stroke-width": "1.5", class: "coin" }));
    }
    return s;
  }

  function primeBot() {  // Doxa: a bone-white wireframe commander with a red eye slit
    const s = svg("svg", { viewBox: "0 0 120 200", class: "prime-holo" });
    const g = svg("g", { fill: "none", stroke: BONE, "stroke-width": "2", "stroke-linejoin": "round" });
    g.append(svg("ellipse", { cx: 60, cy: 26, rx: 15, ry: 18 }), svg("path", { d: "M44 48 L76 48 L84 96 L60 108 L36 96 Z M60 48 V108 M40 70 H80" }),
      svg("path", { d: "M44 50 L22 92 L28 124 M76 50 L98 92 L92 124" }),
      svg("path", { d: "M44 104 L40 150 L34 192 M76 104 L80 150 L86 192 M48 104 L56 150 M72 104 L64 150" }),
      svg("path", { d: "M36 46 L60 40 L84 46 L90 70 M36 46 L30 70", stroke: BLOOD, "stroke-width": "3" }));
    s.append(svg("ellipse", { cx: 60, cy: 194, rx: 34, ry: 5, fill: "#000", opacity: ".6" }), g,
      svg("rect", { x: 50, y: 22, width: 20, height: 4, rx: 2, fill: BLOOD }));
    return s;
  }

  async function artCard(k) {
    const res = await fetch(`/api/team/character/${k}`, { headers: { authorization: "Bearer " + key } });
    if (!res.ok) throw new Error("no picture");
    const img = el("img", { class: "hq-art" + (k === "prime" ? " prime-art" : ""), alt: "" });
    img.src = URL.createObjectURL(await res.blob());
    return img;
  }
  async function syncArt() {
    const have = (state && state.characters) || {};
    for (const k of Object.keys(isles)) {
      const slot = isles[k].slot;
      const wanted = have[k] || 0;
      if ((art[k] || 0) === wanted) continue;
      art[k] = wanted;
      const old = slot.querySelector("img.hq-art");
      if (old) URL.revokeObjectURL(old.src);
      try { slot.replaceChildren(wanted ? await artCard(k) : isles[k].make()); } catch { slot.replaceChildren(isles[k].make()); }
      isles[k].node.classList.toggle("has-art", !!wanted);
    }
  }

  // What stands on each island; lit by real numbers only.
  function prop(k) {
    const wrap = el("div", { class: `hq-prop p-${k}` });
    if (k === "marketing") wrap.append(el("div", { class: "p-wall" }, spans(6)));
    if (k === "stores") wrap.append(el("div", { class: "p-shop" }, el("i"), el("div", {}, spans(3))));
    if (k === "trading") wrap.append(el("div", { class: "p-chart" }, spans(5)));
    if (k === "lab") wrap.append(el("div", { class: "p-flasks" }, spans(3)));
    if (k === "code") wrap.append(el("div", { class: "p-timeline" }, spans(4)), el("div", { class: "p-tag" }, "</>"));
    if (k === "knowledge") wrap.append(el("div", { class: "p-dms" }, spans(8)));
    if (k === "desk") wrap.append(el("div", { class: "p-gate" }, el("i"), el("i"), el("b", {}, "APPROVE")), el("div", { class: "p-phones" }, spans(4)));
    if (k === "pacifica") wrap.append(el("div", { class: "p-shield" }, el("b", {}, "P")));
    if (k === "websites") wrap.append(el("div", { class: "p-site" }, el("i"), el("div", {}, spans(4))));
    if (k === "stenos") wrap.append(el("div", { class: "p-steno" }, el("b", {}, "WEB STUDIO"), el("div", {}, spans(8))));
    if (k === "arbitrage") wrap.append(el("div", { class: "p-flip" }, el("b", {}, "BUY"), el("i", {}, "→"), el("b", {}, "SELL"), el("div", {}, spans(3))));
    return wrap;
  }

  function island(k, label, size, x, y, kids) {
    const node = el("div", { class: `hq-room hq-island k-${k}`, role: "button", tabindex: "0", "aria-label": label,
      onclick: (e) => { e.stopPropagation(); stopTour(); select(k, true); },
      onkeydown: (e) => { if (e.key === "Enter") { stopTour(); select(k, true); } } });
    node.style.cssText = `left:${x - size / 2}px;top:${y - size / 2}px;width:${size}px;height:${size}px`;
    const float = el("div", { class: "float" });
    float.append(el("div", { class: "under" }), el("div", { class: "top" }), el("div", { class: "hq-stand" }, el("div", { class: "rock" }), ...kids));
    node.append(float);
    return node;
  }

  function buildFloor(list) {
    if (window.HQ3D) {
      threeOn = true;
      $("scene").hidden = true;
      $("stage").classList.add("three");
      window.HQ3D.build($("stage"), list.map((i) => ({ ...i, warehouse: WAREHOUSES.includes(i.key) })), {
        onPick: (k) => { stopTour(); select(k, true); },
        onEmpty: () => { stopTour(); overview(); } });
      isles = {};
      buildTourBar(list);
      return;
    }
    const floor = $("floor");
    floor.style.width = W + "px";
    floor.style.height = H + "px";
    const belt = $("belt");
    belt.setAttribute("viewBox", `0 0 ${W} ${H}`);
    belt.replaceChildren();
    for (const i of list) {
      const [x, y] = pos(i.key);
      belt.append(svg("line", { x1: CX, y1: CY, x2: x, y2: y, class: "beam", "data-k": i.key }));
    }
    const pts = list.map((i) => pos(i.key));
    pts.push(pts[0]);  // a closed ring: every island is on the network
    const d = pts.map((p, n) => (n ? `A ${RX} ${RY} 0 0 1 ${p[0]} ${p[1]}` : `M ${p[0]} ${p[1]}`)).join(" ");
    belt.append(svg("path", { d, class: "track" }), svg("path", { d, class: "flow", id: "beltpath" }));

    const primeSlot = el("div", { class: "hq-worker" }, primeBot());
    const prime = island("prime", "Doxa · Command", PRIME_SIZE, CX, CY,
      [el("div", { class: "prime-ring" }), primeSlot,
       el("div", { class: "hq-sign prime-sign" }, el("strong", {}, "Doxa"), el("em", { id: "prime-runs" }, "0"))]);
    prime.classList.add("prime");
    floor.append(prime);
    isles.prime = { node: prime, count: prime.querySelector("#prime-runs"), prop: null, slot: primeSlot, make: primeBot };

    for (const i of list) {
      const [x, y] = pos(i.key);
      const count = el("em", {}, "0");
      const sign = el("div", { class: "hq-sign" }, WAREHOUSES.includes(i.key) ? el("small", {}, "WAREHOUSE") : null, el("strong", {}, i.name), count);
      const make = () => robot(i.key);
      const slot = el("div", { class: "hq-worker" }, make());
      const item = prop(i.key);
      const menace = i.key === "marketing" ? el("div", { class: "menace" }, "ゴ", "ゴ", "ゴ") : null;
      const node = island(i.key, i.name, ISLAND, x, y, [item, slot, menace, sign].filter(Boolean));
      if (WAREHOUSES.includes(i.key)) node.classList.add("warehouse");
      floor.append(node);
      isles[i.key] = { node, count, prop: item, slot, make, info: i };
    }
    buildTourBar(list);
    fit();
  }

  function moveCrates(n) {
    if (threeOn) { window.HQ3D.setCrates(n); return; }
    const belt = $("belt");
    belt.querySelectorAll(".crate").forEach((c) => c.remove());
    for (let i = 0; i < n; i++) {
      const crate = svg("g", { class: "crate" });
      crate.append(svg("rect", { width: 14, height: 22, x: -7, y: -11, rx: 3 }), svg("rect", { width: 9, height: 10, x: -4.5, y: -8, rx: 1, class: "screen" }));
      const motion = svg("animateMotion", { dur: "24s", repeatCount: "indefinite", begin: `${-(24 / n) * i}s`, rotate: "auto" });
      motion.append(svg("mpath", { href: "#beltpath" }));
      crate.append(motion);
      belt.append(crate);
    }
  }

  // --- camera (measures the real ring: perspective makes guesses wrong) ------------------------------------------
  let shift = [0, 0];
  const overviewTransform = () => `scale(${base}) translate(${shift[0]}px, ${shift[1]}px)`;
  function fit() {
    if (threeOn) return;  // the 3D view sizes itself
    const stage = $("stage"), scene = $("scene");
    const previous = scene.style.transition;
    scene.style.transition = "none";
    scene.style.transform = "scale(1)";
    const box = stage.getBoundingClientRect();
    const parts = [...scene.querySelectorAll(".hq-island .top, .hq-sign, .hq-prop, .prime-holo")].map((n) => n.getBoundingClientRect());
    if (parts.length) {
      const left = Math.min(...parts.map((r) => r.left)), right = Math.max(...parts.map((r) => r.right));
      const top = Math.min(...parts.map((r) => r.top)), bottom = Math.max(...parts.map((r) => r.bottom));
      const room = 64;
      base = Math.max(0.15, Math.min((box.width - 24) / (right - left), (box.height - room - 16) / (bottom - top), 1.3));
      shift = [box.left + box.width / 2 - (left + right) / 2, box.top + (box.height - room) / 2 - (top + bottom) / 2];
    }
    void scene.offsetWidth;
    scene.style.transform = overviewTransform();
    void scene.offsetWidth;
    scene.style.transition = previous || "";
    if (focused) { const k = focused; focused = null; flyTo(k, true); }
  }
  let resizeTimer = null;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(fit, 120); });

  function flyTo(k, instant) {
    if (threeOn) { window.HQ3D.flyTo(k); focused = k; caption(k); paintTourBar(); return; }
    const scene = $("scene"), stage = $("stage"), ui = isles[k];
    if (!ui) return;
    const previous = scene.style.transition, from = scene.style.transform;
    scene.style.transition = "none";
    const box = stage.getBoundingClientRect();
    const zoom = base * (k === "prime" ? 2.0 : 2.6);
    const lift = (k === "prime" ? 110 : 60) * zoom / 2.6;
    const error = () => {
      const r = ui.node.querySelector(".top").getBoundingClientRect();
      return [r.left + r.width / 2 - (box.left + box.width / 2), r.top + r.height / 2 - (box.top + (box.height - 64) / 2) - lift];
    };
    const apply = (v) => { scene.style.transform = `scale(${zoom}) translate(${v[0]}px, ${v[1]}px)`; };
    let t = [shift[0], shift[1]], g = [zoom, zoom];
    apply(t);
    let e = error();
    for (let i = 0; i < 8 && (Math.abs(e[0]) > 1 || Math.abs(e[1]) > 1); i++) {
      const next = [t[0] - e[0] / g[0], t[1] - e[1] / g[1]];
      apply(next);
      const now = error();
      for (const a of [0, 1]) {
        const step = next[a] - t[a];
        if (Math.abs(step) > 1e-3) { const gain = (now[a] - e[a]) / step; if (gain > zoom * 0.2 && gain < zoom * 8) g[a] = gain; }
      }
      t = next;
      e = now;
    }
    const target = scene.style.transform;
    if (!instant) scene.style.transform = from;
    void scene.offsetWidth;
    scene.style.transition = previous || "";
    scene.style.transform = target;
    focused = k;
    caption(k);
    paintTourBar();
  }

  function overview() {
    focused = null;
    if (threeOn) window.HQ3D.overview(); else $("scene").style.transform = overviewTransform();
    $("caption").hidden = true;
    paintTourBar();
  }

  function islandInfo(k) {
    if (k === "prime") return COMMAND;
    return (isles[k] && isles[k].info) || ((state && state.islands) || []).find((i) => i.key === k) || null;  // 3D has no isles
  }

  function summary(k) {  // one line of real numbers per island
    const d = dept(k), p = (state && state.prime) || {};
    switch (k) {
      case "prime": return (p.note || "Keeps every AI working.") + ` Mission: ${money(p.earned)} of ${money(p.mission || 1e12)}.`;
      case "marketing": return `${d.label || "No campaign yet"} · ${d.count || 0} scripts · ${d.waiting || 0} waiting on you · ${d.posts || 0} posted.`;
      case "stores": return `${d.count || 0} products found in ${d.hunts || 0} hunts · ${d.testing || 0} testing · ${d.winners || 0} winners · ${d.sites || 0} store pages.` + botLine(d);
      case "trading": return (d.arena ? `Arena: ${(d.arena.alive || []).length} paper bots alive, ${d.arena.died || 0} died. ` : "") + `Paper only, no real money.` + botLine(d);
      case "arbitrage": return `${(d.bot && d.bot.runs) || 0} research runs so far.` + botLine(d);
      case "reverse": return `Car head unit (CarPlay / Android Auto), game mods, any program. ${(d.bot && d.bot.runs) || 0} research runs.` + botLine(d);
      case "websites": return `${d.count || 0} site(s) built in Doxa Sites.` + botLine(d);
      case "stenos": return `Web studio · ${(d.bot && d.bot.runs) || 0} research runs.` + botLine(d);
      case "pacifica": return (d.connected ? "Pacifica connected: Doxa drafts quote requests, you send them." : "Pacifica not connected yet (Settings → Pacifica).") + botLine(d);
      case "lab": return d.busy ? "Researching ways to upgrade Doxa right now…" : `${d.count || 0} upgrade idea(s) waiting` + (d.auto_on ? " for Doxa's review (or yours)." : " for your approval.") + (d.status && !d.status.includes("waiting") ? ` ${d.status}` : "");
      case "code": return d.busy ? `Working: ${d.task || ""}` : "Idle. Ask Doxa to build or fix anything, or approve an upgrade in the Research Lab.";
      case "knowledge": return `${d.count || 0} lessons every AI reads.`;
      case "desk": return `${d.scripts || 0} script(s) and ${d.upgrades || 0} upgrade idea(s) waiting.`;
      default: return "";
    }
  }

  function botLine(d) {
    const b = d.bot;
    if (!b) return "";
    const last = (b.activity || []).slice(-1)[0];
    return b.busy && last ? ` ${b.name}: ${last.text}` : "";
  }
  const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  function caption(k) {
    const info = islandInfo(k);
    if (!info) return;
    $("cap-step").textContent = info.worker;
    $("cap-title").textContent = k === "prime" ? "Doxa" : info.name;
    $("cap-text").textContent = summary(k);
    $("caption").hidden = false;
  }

  function buildTourBar(list) {
    $("tour").replaceChildren(
      el("button", { class: "play", "data-k": "__play", onclick: () => (touring ? stopTour() : startTour()) }, "▶ Tour"),
      el("button", { "data-k": "__all", onclick: () => { stopTour(); overview(); } }, "Overview"),
      el("button", { "data-k": "prime", onclick: () => { stopTour(); select("prime", true); } }, "Command"),
      ...list.map((i) => el("button", { "data-k": i.key, onclick: () => { stopTour(); select(i.key, true); } }, i.name)));
  }
  function paintTourBar() {
    for (const b of $("tour").querySelectorAll("button")) {
      const k = b.dataset.k;
      const on = k === "__all" ? !focused : k === "__play" ? !!touring : k === focused;
      b.classList.toggle("on", on);
      if (k === "__play") b.textContent = touring ? "❚❚ Pause" : "▶ Tour";
      if (on && k === focused && b.scrollIntoView) b.scrollIntoView({ block: "nearest", inline: "center" });
    }
  }
  function order() { return ["prime", ...((state && state.islands) || []).map((i) => i.key)]; }
  function startTour() {
    const list = order();
    let i = focused ? (list.indexOf(focused) + 1) % list.length : 0;
    const step = () => {
      if (i >= list.length) { stopTour(); overview(); return; }
      select(list[i], true);
      i += 1;
      touring = setTimeout(step, 4200);
      paintTourBar();
    };
    touring = -1;
    step();
  }
  function stopTour() { clearTimeout(touring); touring = null; paintTourBar(); }
  $("stage").addEventListener("click", (e) => { if (e.target.closest(".hq-tour, .hq-arrow, canvas")) return; stopTour(); if (focused) overview(); });
  // Move between islands without hunting for them (the owner 2026-11-09: "I can't actually click every island"):
  // big ‹ › arrows on the stage, swipe left/right on a phone, ←/→ on a keyboard.
  const step = (dir) => {
    stopTour();
    const list = order(), at = list.indexOf(focused || selected);
    select(list[(at + dir + list.length) % list.length], true);
  };
  for (const [dir, label, side] of [[-1, "‹", "left"], [1, "›", "right"]]) {
    $("stage").append(el("button", { class: `hq-arrow ${side}`, "aria-label": dir < 0 ? "Previous island" : "Next island",
      onclick: (e) => { e.stopPropagation(); step(dir); } }, label));
  }
  let touchX = null;
  $("stage").addEventListener("touchstart", (e) => { touchX = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
  $("stage").addEventListener("touchend", (e) => {
    if (touchX === null || (threeOn && !focused)) { touchX = null; return; }  // 3D overview: a drag spins HQ instead
    const dx = e.changedTouches[0].clientX - touchX;
    touchX = null;
    if (Math.abs(dx) > 60) step(dx < 0 ? 1 : -1);
  }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (!state || e.target.closest("input, textarea") || !$("modal").hidden) return;
    const list = order(), at = list.indexOf(focused || selected);
    if (e.key === "ArrowRight") { stopTour(); select(list[(at + 1) % list.length], true); }
    if (e.key === "ArrowLeft") { stopTour(); select(list[(at - 1 + list.length) % list.length], true); }
    if (e.key === "Escape") { stopTour(); overview(); }
  });

  function status(k) {
    if (!state) return "";
    const d = dept(k);
    if (k === "prime") return (state.busy || []).length || dept("lab").busy || dept("code").busy ? "working" : (state.prime && state.prime.on) ? "done" : "";
    if (d.busy) return "working";
    if ((k === "desk" && d.count) || (k === "marketing" && d.waiting) || (k === "lab" && d.count)) return "waiting";
    return "";
  }

  function paintProps() {
    if (threeOn) return;  // the 3D islands light their own props in HQ3D.update
    const light = (k, n) => isles[k] && isles[k].prop.querySelectorAll("span").forEach((s, i) => s.classList.toggle("lit", i < n));
    light("marketing", Math.min(6, dept("marketing").count || 0));
    light("stores", Math.min(3, Math.ceil((dept("stores").count || 0) / 4)));
    light("trading", Math.min(5, dept("trading").fills || 0));
    light("lab", Math.min(3, dept("lab").count || 0));
    light("code", dept("code").busy ? 4 : 0);
    light("knowledge", Math.min(8, Math.ceil((dept("knowledge").count || 0) / 3)));
    light("desk", Math.min(4, dept("desk").count || 0));
    light("arbitrage", Math.min(3, dept("arbitrage").count || 0));
    light("websites", Math.min(4, dept("websites").count || 0));
    light("stenos", Math.min(8, (dept("stenos").bot && dept("stenos").bot.runs) || 0));
    if (isles.pacifica) isles.pacifica.node.classList.toggle("live", !!dept("pacifica").connected);
    for (const line of $("belt").querySelectorAll(".beam")) line.classList.toggle("on", status(line.dataset.k) === "working");
  }

  function render() {
    const s = state, p = s.prime || {};
    $("name").textContent = "Doxa HQ";
    $("goal").textContent = s.campaign ? `Marketing: ${s.campaign.name} · Goal: ${s.campaign.goal}` : "Your money lines, one island each. Tap an island.";
    const st = [["products", dept("stores").count], ["bot runs", (s.bots || {}).runs], ["upgrades", dept("lab").count], ["paper trades", dept("trading").fills]];
    const sig = JSON.stringify([st, p.earned]);
    if (sig !== render.stats) {
      render.stats = sig;
      $("stats").replaceChildren(...st.map(([label, value]) => el("div", { class: "hq-stat" }, el("b", {}, String(value || 0)), el("span", {}, label))),
        el("div", { class: "hq-stat mission" }, el("b", {}, money(p.earned)), el("span", {}, "of $1T")));
    }
    for (const k of order()) {
      if (threeOn) {
        window.HQ3D.update(k, { status: status(k), count: k === "prime" ? (p.runs || 0) : (dept(k).count || 0) });
        window.HQ3D.setArt(k, (s.characters || {})[k] || 0);   // the robot portraits, when they exist
        if (window.HQ3D.setFigure) window.HQ3D.setFigure(k, ((s.art || {}).figures || {})[k] || 0);   // 3D figures (1.37)
        if (window.HQ3D.setIslandArt) window.HQ3D.setIslandArt(k, ((s.art || {}).islands || {})[k] || 0);   // renders (1.38.2)
      }
      const ui = isles[k]; if (!ui) continue;
      const stt = status(k);
      for (const cls of ["working", "waiting", "done", "problem"]) ui.node.classList.toggle(cls, cls === stt);
      ui.node.classList.toggle("selected", k === selected);
      ui.count.textContent = String(k === "prime" ? (p.runs || 0) : (dept(k).count || 0));
    }
    paintProps();
    const crates = Math.min(6, 2 + Math.floor((dept("desk").count || 0) / 2));
    if (moveCrates.last !== crates) { moveCrates.last = crates; moveCrates(crates); }
    if (focused) caption(focused);
    renderPanel();
    syncChat();
    syncArt();
  }

  // --- a chat box on every island (the owner 2026-11-09): ask anything, give ideas, paste a prompt to build ------------
  // Docked under the panel and never rebuilt by the 2-second poll, so what you type stays put. Doxa answers with the
  // island's live numbers and knowledge, and can queue research for the island's bot or a build for Code mode.
  let chatKey = null, chatSig = "", chatMsgs = [];
  const chatName = (k) => (k === "prime" ? "Doxa" : (islandInfo(k) || {}).name || k);
  function paintChat() {
    const info = ((state && state.chats) || {})[selected] || {};
    $("chat-head").textContent = `CHAT · ${chatName(selected).toUpperCase()}`;
    $("chat-text").placeholder = selected === "prime" ? "Ask Doxa anything, give an idea, or paste a prompt to build…"
      : `Ask ${chatName(selected)} anything, queue research, or paste a prompt…`;
    const nodes = chatMsgs.map((m) => el("div", { class: "msg " + (m.role === "you" ? "you" : "doxa") + (m.error ? " err" : "") },
      el("p", {}, m.text), ...(m.queued || []).map((q) => el("small", { class: "queued" }, q)),
      m.role !== "you" && m.by ? el("time", {}, m.by) : null));
    if (info.busy) nodes.push(el("div", { class: "msg doxa thinking" }, el("p", {}, "Doxa is thinking…")));
    if (!nodes.length) nodes.push(el("div", { class: "hint" }, "The bots keep working either way. Ask a question, drop an idea, or paste a prompt and Doxa queues the research or the build."));
    const log = $("chat-log");
    log.replaceChildren(...nodes);
    log.scrollTop = log.scrollHeight;
  }
  async function syncChat(force) {
    if (chatKey !== selected) { chatKey = selected; chatMsgs = []; chatSig = ""; paintChat(); }
    const info = ((state && state.chats) || {})[selected] || { n: 0, at: 0, busy: false };
    const sig = JSON.stringify([selected, info]);
    if (!force && sig === chatSig) return;
    chatSig = sig;
    if (info.n) {
      try {
        const r = await api("/api/hq/action", { action: "island_chat_view", key: selected });
        if (r.key === selected) chatMsgs = r.messages || [];
      } catch { /* shown on the next poll */ }
    }
    paintChat();
  }
  $("chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = $("chat-text"), text = box.value.trim();
    if (!text) return;
    $("chat-send").disabled = true;
    try {
      await api("/api/hq/action", { action: "island_chat", key: selected, text });
      box.value = "";
      chatMsgs.push({ role: "you", text });
      state.chats = { ...(state.chats || {}), [selected]: { n: chatMsgs.length, at: Date.now() / 1000, busy: true } };
      paintChat();
      chatSig = "";
      poll();
    } catch (err) { toast(err.message); }
    $("chat-send").disabled = false;
  });
  $("chat-text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("chat-form").requestSubmit(); }
  });

  // --- the side panel: what each island has and what you can do there ---------------------------------------------
  const card = (...kids) => el("div", { class: "hq-card" }, ...kids);
  const meta = (text) => el("div", { class: "meta" }, text);
  const button = (label, onclick, ghost) => el("button", { class: "hq-btn" + (ghost ? " ghost" : ""), ...(busy ? { disabled: "" } : {}), onclick }, label);

  function scriptCards(waiting) {
    return waiting.map((item) => card(
      el("div", { class: "hook" }, `${item.angle ? item.angle + ": " : ""}${item.hook}`),
      item.model ? el("div", { class: "by" }, `Written by ${item.model}`) : null,
      meta(`${(item.script || "").slice(0, 500)}\nCTA: ${item.cta || ""}`),
      el("div", { class: "row" }, button("Approve", () => decide(item.id, true)), button("Reject", () => decide(item.id, false), true))));
  }
  function botSection(k) {
    const b = dept(k).bot, o = (state && state.bots) || {};
    if (!b) return [];
    const lines = (b.activity || []).slice(-8);
    const feed = el("div", { class: "feed" + (b.busy ? " live" : "") },
      ...lines.map((a) => el("div", {}, el("time", {}, clock(a.at)), el("span", {}, a.text))));
    if (!lines.length) {
      feed.append(el("div", {}, el("span", {}, o.brain ? `Waiting for its turn: the bots take turns every ${o.every_min || 20} minutes, all day.`
        : "No free AI connected yet. Add your OpenCode Go or Gemini key in Settings → AI brains and the bots start on their own.")));
    }
    const out = [el("div", { class: "term" }, `${b.name.toUpperCase()} · RESEARCH BOT${b.busy ? " · LIVE" : ""}`), feed,
      ...(b.asks || []).map((q) => el("div", { class: "line-row" }, el("b", {}, "NEXT"), el("div", {}, el("strong", {}, q), el("span", {}, "your question, queued from the chat")))),
      el("div", { class: "row" }, button(b.busy ? "Researching…" : "Research now", () => act("bot_run", { key: k })),
        el("span", { class: "by" }, `${b.runs || 0} runs${o.brain ? " · " + o.brain : ""}`))];
    if ((b.findings || []).length) {
      out.push(el("div", { class: "term" }, "FINDINGS"));
      for (const f of b.findings) out.push(card(el("div", { class: "hook" }, f.title), meta(f.detail || ""), f.source ? el("div", { class: "src" }, f.source) : null));
    }
    return out;
  }

  function upgradeCards(list) {
    return list.map((u) => {
      const prompt = el("pre", { class: "prompt", hidden: "" }, u.prompt || "");
      return card(el("div", { class: "hook" }, u.title), el("div", { class: "by" }, `for ${u.island || "Doxa"}`), meta(u.why || ""),
        u.note ? el("div", { class: "by" }, u.note) : null,
        ...(u.sources || []).slice(0, 3).map((src) => el("div", { class: "src" }, src)),
        el("button", { class: "linkish", onclick: () => { prompt.hidden = !prompt.hidden; } }, "Show the Code mode prompt"), prompt,
        el("div", { class: "row" }, button("Approve & build", () => labDecide(u.id, true)), button("Reject", () => labDecide(u.id, false), true)));
    });
  }

  function renderPanel() {
    const s = state, panel = $("panel"), k = selected, info = islandInfo(k), d = dept(k);
    if (!info) return;
    const sig = JSON.stringify([k, busy, s.campaign, s.prime, s.bots, d, k === "marketing" || k === "desk" ? [s.waiting, s.workers, s.busy, s.counts, s.models, dept("lab")] : null]);
    if (sig === panelSig) return;  // nothing changed: leave the DOM (and your scroll position) alone
    panelSig = sig;
    const parts = [el("div", { class: "term" }, info.worker.toUpperCase()), el("h2", {}, k === "prime" ? "Doxa" : info.name),
      el("div", { class: "about" }, info.about), el("div", { class: "status" }, summary(k))];

    if (k === "prime") {
      const p = s.prime || {};
      const pct = Math.min(100, (Number(p.earned || 0) / Number(p.mission || 1e12)) * 100);
      parts.push(el("div", { class: "mission-box" }, el("small", {}, "MISSION"), el("b", {}, `${money(p.earned)} of $1,000,000,000,000`),
        (() => { const bar = el("i"); bar.style.width = `${Math.max(0.5, pct)}%`; return el("div", { class: "bar" }, bar); })(),  // CSP blocks style="…"
        el("span", {}, "Counts the revenue you enter in each post's results.")),
        el("div", { class: "who" }, `${p.on ? "On duty" : "Paused"} · ${p.runs || 0} of ${p.max_runs || 4} paid jobs started today`));
      const art = s.art || {};
      parts.push(el("div", { class: "term" }, "ROBOT ART"),
        el("div", { class: "who" }, art.status || (art.missing ? `${art.missing} island(s) still use the built-in robot. ChatGPT's image AI can draw them (about $${(art.missing * 0.063).toFixed(2)} of the OpenAI budget).` : "Every island has its picture.")),
        ...(art.missing && !art.running ? [el("div", { class: "row" }, button("Make robot art", () => act("make_art")))] : []),
        ...(!art.missing && art.figures_missing && !art.running ? [el("div", { class: "who" }, `${art.figures_missing} island(s) have no 3D figure yet (about $${(art.figures_missing * 0.25).toFixed(2)}).`),
          el("div", { class: "row" }, button("Make 3D figures", () => act("make_art", { kind: "figure" })))] : []));
      const o = s.bots || {};
      parts.push(el("div", { class: "term" }, "RESEARCH BOTS"),
        el("div", { class: "who" }, o.paused ? "Paused." : o.brain ? `Working nonstop (next on ${o.brain}, no extra cost): one warehouse every ${o.every_min || 15} min, ${o.runs || 0} runs so far.` + (o.resting ? ` Resting ${Math.ceil(o.resting / 60)} min (free limit).` : "")
          : "Waiting for a free AI: add your OpenCode Go or Gemini key in Settings → AI brains."),
        el("div", { class: "row" }, button(o.paused ? "Resume the bots" : "Pause the bots", () => act("bots_pause", { paused: !o.paused }), !o.paused)));
      const log = (p.log || []).slice().reverse();
      parts.push(el("div", { class: "term" }, "LOG"));
      if (!log.length) parts.push(card(meta("Nothing sent yet. Doxa checks every minute while your PC is on.")));
      for (const entry of log) {
        parts.push(el("div", { class: "log-line" }, el("time", {}, new Date(entry.at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })),
          el("span", {}, entry.text)));
      }
    }
    if (k === "marketing") {
      if (!s.campaign) parts.push(button("+ New campaign", openModal));
      parts.push(el("div", { class: "term" }, "THE LINE"));
      for (const r of s.rooms || []) {
        const running = (s.busy || []).includes(r.key);
        const auto = ["research", "writers", "analyst"].includes(r.key);
        const w = (s.workers || {})[r.key] || {};
        parts.push(el("div", { class: "line-row" + (running ? " on" : "") },
          el("b", {}, String((s.counts || {})[r.key] || 0)),
          el("div", {}, el("strong", {}, r.room), el("span", {}, running ? "working…" : w.detail || r.about)),
          auto && s.campaign ? el("button", { class: "mini", ...(running || busy ? { disabled: "" } : {}), onclick: () => run(r.key) }, running ? "…" : "Run") : null));
      }
      if ((s.waiting || []).length) parts.push(el("div", { class: "term" }, "WAITING ON YOU"), ...scriptCards(s.waiting));
    }
    if (dept(k).bot) parts.push(...botSection(k));  // every island has its research bot
    if (k === "websites" && d.publish) {
      const pub = d.publish;
      parts.push(el("div", { class: "term" }, "HOSTING · CLOUDFLARE (FREE)"),
        el("div", { class: "who" }, pub.status || (pub.connected ? "Connected to your Cloudflare. Press Publish to put a site online."
          : pub.connected === false ? "Connect Cloudflare once (you approve it on Cloudflare's page), then publish any site with one press."
          : "Checking your Cloudflare connection…")));
      if (pub.connected === false) parts.push(el("div", { class: "row" }, button("Connect Cloudflare", () => act("cloudflare_connect"))));
      for (const site of pub.sites || []) parts.push(el("div", { class: "line-row" },
        el("b", {}, site.url ? "LIVE" : "—"),
        el("div", {}, el("strong", {}, site.name), el("span", {}, site.url || (site.ready ? "not published yet" : "no index.html yet"))),
        site.ready ? el("button", { class: "mini", ...(pub.busy ? { disabled: "" } : {}), onclick: () => act("site_publish", { name: site.name }) },
          pub.busy === site.name ? "…" : site.url ? "Update" : "Publish") : null));
      if (!(pub.sites || []).length) parts.push(card(meta("No sites yet. Ask Doxa to \"build a website for <business>\" first.")));
    }
    if (k === "reverse") {
      parts.push(card(meta("Give Doxa any file or program in Code mode (\"reverse engineer …\") and it takes it apart. For the car: the screen/radio unit only; never engine, brakes, airbags or emissions. Keep a backup before writing anything.")));
    }
    if (k === "stenos") {
      parts.push(card(meta("Plans: Essential Care $99, Growth $249, Studio Partner $499 a month. Portfolio: Chess Academy, the owner's Insurance, Pacifica CRM, Mercado Fútbol, Revive, Vyra."),
        el("div", { class: "src" }, "https://example.com")));
    }
    if (k === "pacifica") {
      parts.push(card(meta(d.connected ? "Pacifica is connected. Say \"start a quote for <name>, <coverage>\" and Doxa drafts the quote request in Pacifica for you to send."
        : "Connect Pacifica in Settings → Pacifica connection."), meta("Carrier quoting from Doxa is the next build: it learns your clicks once, logs in from the private login vault and asks your phone for the Farmers code.")));
    }
    if (k === "stores") {
      parts.push(el("div", { class: "row" }, button(d.busy ? "Hunting…" : "Hunt products now", () => act("hunt"))));
      if ((d.top || []).length) parts.push(el("div", { class: "term" }, "PRODUCTS"));
      for (const prod of d.top || []) parts.push(el("div", { class: "line-row" }, el("b", {}, String(prod.score || 0)),
        el("div", {}, el("strong", {}, prod.name), el("span", {}, prod.status))));
      parts.push(card(meta("Etsy listings and a Shopify store for your best product are queued in the Research Lab.")));
    }
    if (k === "trading" && d.arena) {
      const ar = d.arena;
      parts.push(el("div", { class: "term" }, `ARENA · ${ar.rules}`));
      if (!(ar.alive || []).length) parts.push(card(meta("The first bots are born after today's US market close (1:30 PM your time).")));
      for (const b of ar.alive || []) parts.push(el("div", { class: "line-row" + (b.equity > 1000 ? " on" : "") },
        el("b", {}, `$${Math.round(b.equity)}`),
        el("div", {}, el("strong", {}, `${b.name} · ${b.symbol}`), el("span", {}, `${b.strategy} · day ${b.days} · ${b.trades} trades · backtest +${b.audition}%`))));
      if ((ar.dead || []).length) {
        parts.push(el("div", { class: "term" }, `GRAVEYARD · ${ar.died} died`));
        for (const b of ar.dead) parts.push(el("div", { class: "line-row" }, el("b", { class: "tag rejected" }, "RIP"),
          el("div", {}, el("strong", {}, `${b.name} · ${b.symbol}`), el("span", {}, b.reason || ""))));
      }
    }
    if (k === "trading") {
      const pos = Object.entries(d.positions || {});
      parts.push(el("div", { class: "term" }, "OPEN PAPER POSITIONS"),
        ...(pos.length ? pos.map(([sym, q]) => el("div", { class: "line-row" }, el("b", {}, String(q)), el("div", {}, el("strong", {}, sym)))) : [card(meta("None yet."))]),
        card(meta("Tell Doxa \"paper trade …\" with the real price you saw and your reason. It records every fill, fee and result so you can see what actually works before real money. Doxa never places real trades.")));
    }
    if (k === "lab") {
      parts.push(el("div", { class: "row" }, button(d.busy ? "Researching…" : "Research upgrades now", () => act("lab_research"))));
      const a = d.auto || {};
      parts.push(el("div", { class: "who" }, d.auto_on ? `Doxa approves everything (Claude Opus reviews each idea) and builds the good ones in a safe copy: ${a.reviews || 0} reviewed, ${a.builds || 0} of 8 built today.`
        : "Ideas wait for your OK."));
      if ((d.proposals || []).length) parts.push(el("div", { class: "term" }, "WAITING"), ...upgradeCards(d.proposals));
      if ((d.recent || []).length) {
        parts.push(el("div", { class: "term" }, "DECIDED"));
        for (const r of d.recent) parts.push(el("div", { class: "line-row" }, el("b", { class: "tag " + r.status }, r.status), el("div", {}, el("strong", {}, r.title), el("span", {}, r.note || ""))));
      }
    }
    if (k === "code") {
      if (d.busy) parts.push(card(el("div", { class: "hook" }, d.engine || "Code mode"), meta(d.task || "")), button("Stop", stopCode, true));
    }
    if (k === "knowledge") {
      parts.push(el("div", { class: "term" }, "NEWEST LESSONS"), ...(dept("knowledge").latest || []).map((t) => el("div", { class: "line-row" }, el("div", {}, el("strong", {}, t)))));
    }
    if (k === "desk") {
      const lab = dept("lab");
      if ((s.waiting || []).length) parts.push(el("div", { class: "term" }, "SCRIPTS"), ...scriptCards(s.waiting));
      if ((lab.proposals || []).length) parts.push(el("div", { class: "term" }, "UPGRADES"), ...upgradeCards(lab.proposals));
      if (!(s.waiting || []).length && !(lab.proposals || []).length) parts.push(card(meta("Nothing waiting on you. Nothing gets filmed or posted without your OK.")));
    }
    panel.replaceChildren(...parts);
  }

  function islandsChanged() { return JSON.stringify((state.islands || []).map((i) => i.key)); }
  function select(k, fly) { selected = k; if (state) render(); if (fly) flyTo(k); }

  async function run(room) {
    busy = true; panelSig = ""; renderPanel();
    try { await api("/api/team/run", { room }); toast("Started. Watch the island light up."); } catch (e) { toast(e.message); }
    busy = false; panelSig = ""; poll();
  }
  async function decide(id, approve) {
    try { await api("/api/team/decide", { id, approve }); toast(approve ? "Approved → film it" : "Rejected"); } catch (e) { toast(e.message); }
    panelSig = ""; poll();
  }
  async function act(action, extra = {}) {
    busy = true; panelSig = ""; renderPanel();
    try { const r = await api("/api/hq/action", { action, ...extra }); toast(r.message || "Done."); } catch (e) { toast(e.message); }
    busy = false; panelSig = ""; poll();
  }
  const labDecide = (id, approve) => act("lab_decide", { id, approve });
  async function stopCode() {
    try { await api("/api/code/stop", {}); toast("Stopping Code mode."); } catch (e) { toast(e.message); }
    panelSig = ""; poll();
  }

  // --- new marketing campaign ----------------------------------------------------------------------------------------
  function openModal() { $("modal").hidden = false; $("campaign-form").elements.name.focus(); }
  function closeModal() { $("modal").hidden = true; }
  $("new-campaign").addEventListener("click", openModal);
  $("modal-cancel").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
  $("campaign-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target.elements;
    try {
      await api("/api/team/campaign", { name: f.name.value, goal: f.goal.value, audience: f.audience.value, offer: f.offer.value });
      e.target.reset();
      closeModal();
      toast("Campaign started. Doxa puts the marketing team to work.");
      select("marketing", true);
      panelSig = ""; poll();
    } catch (err) { toast(err.message); }
  });

  let timer = null, built = "";
  window.addEventListener("hq3d-ready", () => { built = ""; poll(); });  // the 3D world loaded: rebuild into it
  async function poll() {
    clearTimeout(timer);
    try {
      state = await api("/api/team");
      if (!(state.islands || []).length) throw new Error("This Doxa is too old for islands.");
      if (built !== islandsChanged()) {
        built = islandsChanged();
        $("floor").querySelectorAll(".hq-island").forEach((n) => n.remove());
        isles = {};
        buildFloor(state.islands);
        if (!session.get("hq.toured") && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
          session.set("hq.toured", "1");
          setTimeout(startTour, 1200);
        }
      }
      render();
    } catch (e) {
      $("goal").textContent = key ? (e.message.includes("too old") ? e.message : "Can't reach Doxa — is your PC on?") : "Open this from Doxa (Team HQ) or your Doxa phone page.";
    }
    timer = setTimeout(poll, document.hidden ? 8000 : 2000);
  }
  document.addEventListener("visibilitychange", () => { document.body.classList.toggle("paused", document.hidden); if (!document.hidden) poll(); });
  poll();
})();
