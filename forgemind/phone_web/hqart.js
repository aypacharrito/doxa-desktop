/* Doxa HQ, art view (1.38.2): the Higgsfield island renders the owner approved on 2026-11-10 ("fix all the islands with
   what we made on Higgsfield"). Overview = a world map: Command in the middle, the other islands around it, linked by
   glowing lines. Opening an island shows its render full screen with a slow camera drift. Same API as the 3D world
   (window.HQ3D), so hq.js keeps the data, panel, chat, tour and arrows. ?3d opens the old 3D world; phones keep 2D. */
(() => {
  "use strict";
  const small = matchMedia("(max-width: 900px), (pointer: coarse)").matches;
  const three = /[?&]3d\b/.test(location.search);
  const paintToggle = () => {   // header link: Art view <-> 3D view (laptop only)
    const toggle = document.getElementById("view-toggle");
    if (!toggle) return;
    toggle.hidden = small;
    toggle.textContent = three ? "Art view" : "3D view";
    toggle.href = three ? "hq.html" : "hq.html?3d";
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paintToggle); else paintToggle();
  if (three || /[?&]2d\b/.test(location.search) || small) return;
  const key = (() => { try { return localStorage.getItem("jarvis.key") || ""; } catch { return ""; } })()
    || new URLSearchParams(location.hash.slice(1)).get("k") || "";
  const ORDER = ["stores", "trading", "arbitrage", "pacifica", "marketing", "stenos", "websites", "reverse", "lab", "code", "knowledge"];
  const make = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const NS = "http://www.w3.org/2000/svg";

  const ART = {
    root: null, map: null, lines: null, focusView: null, cards: {}, info: {}, urls: {}, versions: {}, focus: null,
    onPick: null, onEmpty: null,

    build(stage, list, { onPick, onEmpty } = {}) {
      this.onPick = onPick; this.onEmpty = onEmpty;
      stage.classList.add("art");
      this.root?.remove();
      this.root = make("div", "art-world");
      this.lines = document.createElementNS(NS, "svg");
      this.lines.setAttribute("class", "art-lines");
      this.map = make("div", "art-map");
      this.focusView = make("div", "art-focus");
      this.focusView.hidden = true;
      this.root.append(this.lines, this.map, this.focusView);
      stage.prepend(this.root);
      this.cards = {};
      const islands = [{ key: "prime", name: "Command" }, ...list];
      for (const i of islands) this.info[i.key] = i;
      for (const i of islands) this.map.append(this.card(i));
      this.place();
      if (!this.resizer) {
        this.resizer = new ResizeObserver(() => this.place());
        this.resizer.observe(stage);
      }
      for (const [k, v] of Object.entries(this.versions)) this.load(k, v, true);
    },

    card(i) {
      const card = make("button", "art-isle" + (i.key === "prime" ? " prime" : ""));
      card.type = "button";
      card.dataset.k = i.key;
      card.style.setProperty("--d", `${(ORDER.indexOf(i.key) + 1) * -0.7}s`);   // islands bob out of step
      const frame = make("span", "art-frame");
      const img = make("img");
      img.alt = "";
      img.decoding = "async";
      frame.append(img, make("span", "art-shine"));
      const plate = make("span", "art-plate");
      const name = make("strong", "", i.key === "prime" ? "Command / Doxa" : i.name);
      const count = make("em", "", "0");
      plate.append(name, count);
      card.append(frame, plate);
      card.addEventListener("click", (e) => { e.stopPropagation(); this.onPick?.(i.key); });
      this.cards[i.key] = { card, img, count };
      return card;
    },

    place() {   // the world map: Command in the middle, the others on an ellipse around it, lines to each
      if (!this.map) return;
      const W = this.map.clientWidth, H = this.map.clientHeight;
      if (!W || !H) return;
      const w = Math.max(150, Math.min(W * 0.165, H * 0.3)), h = w * 9 / 16, label = 30;
      const pw = Math.min(w * 1.62, W * 0.3), ph = pw * 9 / 16;
      const rx = W / 2 - w / 2 - 18, ry = H / 2 - (h + label) / 2 - 14;
      const at = {};
      at.prime = [W / 2, H / 2];
      ORDER.forEach((k, n) => {
        const a = (-90 + (360 / ORDER.length) * n) * Math.PI / 180;
        at[k] = [W / 2 + rx * Math.cos(a), H / 2 + ry * Math.sin(a)];
      });
      for (const [k, ui] of Object.entries(this.cards)) {
        const [x, y] = at[k] || [W / 2, H / 2];
        const cw = k === "prime" ? pw : w, ch = k === "prime" ? ph : h;
        Object.assign(ui.card.style, { left: `${x - cw / 2}px`, top: `${y - (ch + label) / 2}px`, width: `${cw}px` });
        ui.card.querySelector(".art-frame").style.height = `${ch}px`;
      }
      this.lines.setAttribute("viewBox", `0 0 ${W} ${H}`);
      this.lines.replaceChildren();
      for (const k of ORDER) {
        if (!this.cards[k]) continue;
        const [x, y] = at[k];
        const line = document.createElementNS(NS, "line");
        Object.entries({ x1: W / 2, y1: H / 2, x2: x, y2: y, "data-k": k }).forEach(([a, v]) => line.setAttribute(a, v));
        this.lines.append(line);
      }
      ORDER.forEach((k, n) => {   // the outer ring: every island is on the network
        const next = ORDER[(n + 1) % ORDER.length];
        if (!this.cards[k] || !this.cards[next]) return;
        const ring = document.createElementNS(NS, "line");
        Object.entries({ x1: at[k][0], y1: at[k][1], x2: at[next][0], y2: at[next][1], class: "ring" })
          .forEach(([a, v]) => ring.setAttribute(a, v));
        this.lines.append(ring);
      });
    },

    async load(k, version, force) {
      if (!version || (!force && this.versions[k] === version && this.urls[k])) return;
      this.versions[k] = version;
      const ui = this.cards[k];
      if (!ui) return;
      try {
        const res = await fetch(`/api/team/island-art/thumb/${k}/${version}`, { headers: { authorization: "Bearer " + key } });
        if (!res.ok) return;
        const url = URL.createObjectURL(await res.blob());
        if (this.urls[k]) URL.revokeObjectURL(this.urls[k]);
        this.urls[k] = url;
        ui.img.src = url;
        ui.card.classList.add("has-art");
        if (this.focus === k) this.show(k);
      } catch { /* offline: the card keeps its plain frame */ }
    },

    async show(k) {   // open an island: its render full screen, then the sharp version when it arrives
      const view = this.focusView, info = this.info[k] || { name: k };
      view.replaceChildren();
      const back = make("img", "art-big");
      back.alt = "";
      if (this.urls[k]) back.src = this.urls[k];
      const shade = make("div", "art-shade");
      const plate = make("div", "art-plate big");
      plate.append(make("small", "", k === "prime" ? "ISLAND 00" : `ISLAND ${String(ORDER.indexOf(k) + 1).padStart(2, "0")}`),
        make("strong", "", k === "prime" ? "Command / Doxa" : info.name));
      const close = make("button", "art-back", "‹  All islands");
      close.type = "button";
      close.addEventListener("click", (e) => { e.stopPropagation(); this.onEmpty?.(); });
      view.append(back, shade, plate, close);
      view.hidden = false;
      requestAnimationFrame(() => view.classList.add("on"));
      this.root.classList.add("focused");
      if (this.versions[k]) {
        try {
          const res = await fetch(`/api/team/island-art/full/${k}/${this.versions[k]}`, { headers: { authorization: "Bearer " + key } });
          if (res.ok && this.focus === k) {
            const url = URL.createObjectURL(await res.blob());
            back.onload = () => setTimeout(() => URL.revokeObjectURL(url), 1000);
            back.src = url;
          }
        } catch { /* the map picture is already showing */ }
      }
    },

    flyTo(k) {
      if (!this.cards[k]) return;
      this.focus = k;
      for (const [key2, ui] of Object.entries(this.cards)) ui.card.classList.toggle("selected", key2 === k);
      this.show(k);
    },

    overview() {
      this.focus = null;
      this.root?.classList.remove("focused");
      if (this.focusView) {
        this.focusView.classList.remove("on");
        setTimeout(() => { if (!this.focus) this.focusView.hidden = true; }, 380);
      }
      for (const ui of Object.values(this.cards)) ui.card.classList.remove("selected");
    },

    update(k, { status = "", count = 0 } = {}) {
      const ui = this.cards[k];
      if (!ui) return;
      ui.count.textContent = String(count);
      ui.card.classList.remove("working", "waiting", "done", "problem", "later");
      if (status) ui.card.classList.add(status);
      const line = this.lines?.querySelector(`line[data-k="${k}"]`);
      if (line) line.classList.toggle("on", status === "working");
    },

    setIslandArt(k, version) { this.load(k, version); },
    setCrates() {}, setArt() {}, setFigure() {},
  };

  window.HQART = ART;
  window.HQ3D = ART;   // hq.js draws through this API; the old WebGL world only loads with ?3d
})();
