/* Doxa HQ in real 3D (WebGL, three.js bundled locally: the page's CSP allows only Doxa's own scripts).
   the owner 2026-11-09: "more 3D, more video game, more high quality 4K, cooler looking". Inspired by AI-office projects
   (Claw3D, AI Office, StarNet's station) but original: floating islands over a night city, a warehouse and a robot per
   island, Doxa's command tower in the middle, glowing beams and a conveyor of crates. Everything is built from code
   (no downloaded models). hq.js keeps the data, panel, tour and buttons; this file only draws and flies the camera.
   API: window.HQ3D = {build(stage, islands, {onPick}), update(key, {status, count}), flyTo(key), overview(), setCrates(n)}. */
import * as THREE from "./vendor/three.module.min.js";
import { EffectComposer } from "./vendor/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/jsm/postprocessing/OutputPass.js";

const INK = 0x0b0b0d, BONE = 0xf2ede4, BLOOD = 0xe5383b, MUSTARD = 0xf4c430, GREEN = 0x9bd36b, CYAN = 0x7fd4ff, BRONZE = 0xc8925a;
const PINK = 0xff3d9a, PURPLE = 0xa64dff, LIME = 0x7cff4f, ORANGE = 0xff8a3d, TEAL = 0x00e6c3, BLUE = 0x5b7bff, GOLD = 0xffd23f;
const ACCENT = { stores: PINK, trading: GOLD, arbitrage: LIME, pacifica: CYAN, reverse: 0xff6bd6, marketing: PURPLE, stenos: ORANGE,
  websites: TEAL, lab: 0x9dff3a, code: BLOOD, knowledge: BLUE, prime: BLOOD };
const tint = (hex, amount) => new THREE.Color(hex).lerp(new THREE.Color(0x14081f), amount);   // a dark shade of a colour

function checker(accent) {              // the checkered floor, tinted with the island's colour
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d");
  const light = "#" + new THREE.Color(accent).lerp(new THREE.Color(0xffffff), 0.55).getHexString();
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) { g.fillStyle = (x + y) % 2 ? "#0b0b0d" : light; g.fillRect(x * 32, y * 32, 32, 32); }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(3, 3);
  return t;
}

function menaceSprite(color = "#a64dff") {   // a floating 「ゴ」 sound effect
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.font = "900 104px 'Yu Gothic', 'Meiryo', 'MS Gothic', sans-serif";
  g.textAlign = "center"; g.textBaseline = "middle";
  g.lineWidth = 12; g.strokeStyle = "#0b0b0d"; g.strokeText("ゴ", 64, 68);
  g.fillStyle = color; g.fillText("ゴ", 64, 68);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthWrite: false, opacity: 0 }));
  sprite.scale.set(2.4, 2.4, 1);
  return sprite;
}
// --- 3D figures (1.37): ChatGPT's cut-out figure of each robot, standing on its island -----------------------------
// A transparent PNG becomes a figure with real thickness (dark copies of its silhouette behind it) and a neon edge in
// the island's colour that pulses while the island works. It turns toward the camera so it always looks right.
function silhouette(image, color) {           // the figure's outline filled with one colour
  const c = document.createElement("canvas");
  c.width = image.width; c.height = image.height;
  const g = c.getContext("2d");
  g.drawImage(image, 0, 0);
  g.globalCompositeOperation = "source-in";
  g.fillStyle = color; g.fillRect(0, 0, c.width, c.height);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function standee(texture, height, accent, maxAniso) {
  const image = texture.image;
  const width = height * image.width / image.height;
  const geo = new THREE.PlaneGeometry(width, height);
  geo.translate(0, height / 2, 0);                                   // stands on its feet
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = maxAniso;
  const g = new THREE.Group();
  const front = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: texture, alphaTest: 0.5, roughness: 0.45, metalness: 0.15 }));
  front.castShadow = true;
  front.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: texture, alphaTest: 0.5 });
  const body = silhouette(image, "#1a1220");
  for (let i = 1; i <= 6; i++) {                                     // thickness, like a painted cut-out figure
    const layer = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: body, alphaTest: 0.5 }));
    layer.position.z = -i * 0.04;
    g.add(layer);
  }
  const edgeMat = new THREE.MeshBasicMaterial({ map: silhouette(image, "#ffffff"), alphaTest: 0.5, toneMapped: false,
    color: new THREE.Color(accent).multiplyScalar(1.6) });
  const edge = new THREE.Mesh(geo, edgeMat);                         // neon outline (bloom makes it glow)
  edge.scale.set(1.045, 1.025, 1);
  edge.position.set(0, -height * 0.012, -0.3);
  g.add(edge, front);
  g.userData = { edge, accent: new THREE.Color(accent), height };
  return g;
}

const STATUS = { working: MUSTARD, waiting: BLOOD, done: GREEN, "": 0x5a5650 };
const R = 30;                                   // ring radius
const mobile = matchMedia("(max-width: 900px), (pointer: coarse)").matches;

function supported() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; }
}

const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.15, ...extra });
const glow = (color, intensity = 2.2) => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: color, emissiveIntensity: intensity });

// --- text signs: a canvas texture on a sprite (always faces the camera) ---------------------------------------------
function makeSign() {
  const canvas = document.createElement("canvas");
  canvas.width = 512; canvas.height = 160;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthWrite: false }));
  sprite.scale.set(9, 2.8, 1);
  sprite.userData.draw = (title, count, status, warehouse) => {
    const g = canvas.getContext("2d");
    g.clearRect(0, 0, 512, 160);
    const bg = status === "working" ? "#f4c430" : status === "waiting" ? "#e5383b" : "#f2ede4";
    const fg = status === "waiting" ? "#f2ede4" : "#0b0b0d";
    g.save(); g.translate(256, 80); g.rotate(-0.04); g.translate(-256, -80);
    g.fillStyle = "#e5383b"; g.fillRect(26, 26, 470, 112);                 // comic red shadow
    g.fillStyle = bg; g.fillRect(14, 14, 470, 112);
    g.lineWidth = 6; g.strokeStyle = "#0b0b0d"; g.strokeRect(14, 14, 470, 112);
    g.fillStyle = status === "waiting" ? "#f2ede4" : "#e5383b";
    g.font = "700 22px Bahnschrift, 'Segoe UI', sans-serif";
    if (warehouse) g.fillText(warehouse, 34, 48);
    g.fillStyle = fg;
    g.font = "700 46px Bahnschrift, 'Segoe UI', sans-serif";
    g.fillText(title.toUpperCase().slice(0, 16), 34, warehouse ? 100 : 88, 340);
    g.textAlign = "right";
    g.font = "700 64px Bahnschrift, 'Segoe UI', sans-serif";
    g.fillStyle = status === "waiting" ? "#f2ede4" : "#e5383b";
    g.fillText(String(count), 466, 100);
    g.restore();
    texture.needsUpdate = true;
  };
  return sprite;
}

// --- the crew: one original robot per island ------------------------------------------------------------------
function robot(key, scale = 1) {
  const accent = ACCENT[key] ?? BLOOD;
  const g = new THREE.Group();
  const shell = mat(0x1c1b20, { roughness: 0.45, metalness: 0.5 });
  const bone = mat(BONE, { roughness: 0.4, metalness: 0.1 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.75, 1.1, 6, 16), shell);
  body.position.y = 1.55;
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(0.32, 1.3, 1.52), bone);
  stripe.position.set(0, 1.55, 0.02);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.85, 24, 18), bone);
  head.scale.set(1.15, 0.95, 1);
  head.position.y = 3.15;
  const visor = new THREE.Mesh(new THREE.BoxGeometry(1.45, 0.5, 0.4), mat(INK, { roughness: 0.2, metalness: 0.8 }));
  visor.position.set(0, 3.15, 0.66);
  const eyes = [-0.3, 0.3].map((x) => { const e = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 10), glow(accent, 4)); e.position.set(x, 3.16, 0.88); return e; });
  const arms = [-1, 1].map((side) => {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.95, 2.15, 0);
    const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.8, 4, 10), shell);
    arm.position.y = -0.55;
    pivot.add(arm);
    return pivot;
  });
  const legs = [-0.35, 0.35].map((x) => { const l = new THREE.Mesh(new THREE.CapsuleGeometry(0.24, 0.4, 4, 10), shell); l.position.set(x, 0.42, 0); return l; });
  const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.7), bone);
  antenna.position.set(0, 4.25, 0);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 10), glow(accent, 3));
  tip.position.set(0, 4.65, 0);
  g.add(body, stripe, head, visor, ...eyes, ...arms, ...legs, antenna, tip);

  // a signature touch per island (original designs with an anime attitude, not copies of any character)
  const add = (mesh, x, y, z) => { mesh.position.set(x, y, z); g.add(mesh); return mesh; };
  if (key === "stores") {                       // shopkeeper: striped awning hat + a box
    const hat = add(new THREE.Mesh(new THREE.CylinderGeometry(0.95, 1.15, 0.45, 12), mat(BLOOD)), 0, 3.95, 0);
    hat.add(new THREE.Mesh(new THREE.CylinderGeometry(1.16, 1.16, 0.12, 12), bone));
    add(new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.6, 0.6), mat(MUSTARD)), 1.25, 1.2, 0.3);
  }
  if (key === "trading") {                      // skull-white mask + three stripes, holding a glowing chart slate
    visor.material = bone;
    eyes.forEach((e) => { e.material = mat(INK); e.scale.setScalar(1.5); });
    for (let i = 0; i < 3; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.5, 0.06), mat(INK)), -0.75 + i * 0.13, 3.4, 0.6);
    add(new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.6, 0.05), glow(GREEN, 1.5)), -1.25, 1.6, 0.45);
  }
  if (key === "arbitrage") {                    // the dealer: tall hat with a red band, a gold coin
    add(new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 1.0, 20), mat(INK)), 0, 4.35, 0);
    add(new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.08, 24), mat(INK)), 0, 3.86, 0);
    add(new THREE.Mesh(new THREE.CylinderGeometry(0.61, 0.61, 0.16, 20), mat(BLOOD)), 0, 4.0, 0);
    const coin = add(new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.06, 24), glow(MUSTARD, 1.6)), 1.3, 2.6, 0.4);
    coin.rotation.x = Math.PI / 2;
    g.userData.spin = coin;
  }
  if (key === "reverse") {                      // the safecracker: glowing goggles + a magnifying glass
    [-0.32, 0.32].forEach((x) => add(new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.2, 18), glow(0xff6bd6, 2.4)), x, 3.2, 0.82).rotation.x = Math.PI / 2);
    add(new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.07, 8, 24), mat(GOLD, { metalness: 0.8, roughness: 0.3 })), 1.3, 2.1, 0.5);
    add(new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.8), mat(0x2b2a30)), 1.55, 1.55, 0.5).rotation.z = 0.6;
  }
  if (key === "pacifica") {                     // guardian with a big shield
    const shield = add(new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.16, 6), bone), -1.35, 1.7, 0.4);
    shield.rotation.z = Math.PI / 2; shield.rotation.y = 0.3;
    add(new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.9, 0.05), mat(BLOOD)), -1.45, 1.7, 0.52);
  }
  if (key === "marketing") {                    // a guardian spirit rising behind it
    const spirit = add(new THREE.Mesh(new THREE.SphereGeometry(1.4, 20, 16),
      new THREE.MeshStandardMaterial({ color: BLOOD, emissive: BLOOD, emissiveIntensity: 0.8, transparent: true, opacity: 0.32 })), 0, 3.6, -1.1);
    spirit.scale.set(1, 1.5, 0.7);
    g.userData.spirit = spirit;
  }
  if (key === "stenos") {                       // the studio's art director: bronze headset + a stylus
    add(new THREE.Mesh(new THREE.TorusGeometry(0.88, 0.07, 8, 24, Math.PI), mat(BRONZE, { metalness: 0.8, roughness: 0.3 })), 0, 3.25, 0);
    add(new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.02, 1.0), glow(BRONZE, 2)), 1.2, 1.7, 0.4).rotation.z = 0.6;
  }
  if (key === "websites") {                     // the builder: hard hat
    add(new THREE.Mesh(new THREE.SphereGeometry(0.95, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), mat(MUSTARD)), 0, 3.45, 0);
    add(new THREE.Mesh(new THREE.CylinderGeometry(1.15, 1.15, 0.08, 20), mat(MUSTARD)), 0, 3.48, 0);
  }
  if (key === "lab") {                          // patched together, a bolt through the head
    const bolt = add(new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 2.6, 10), mat(0x9a958c, { metalness: 0.8 })), 0, 3.25, 0);
    bolt.rotation.z = Math.PI / 2;
  }
  if (key === "code") {                         // a scythe arm
    const pole = add(new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 4.2), mat(0x2b2a30)), 1.3, 2.6, 0);
    pole.rotation.z = -0.2;
    const blade = add(new THREE.Mesh(new THREE.TorusGeometry(1.1, 0.1, 6, 20, Math.PI * 0.8), glow(BLOOD, 1.8)), 1.7, 4.4, 0);
    blade.rotation.z = Math.PI * 0.55;
  }
  if (key === "knowledge") {                    // a floating book
    const book = add(new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.15, 0.65), mat(BLOOD)), -1.2, 2.3, 0.6);
    g.userData.spin = book;
  }
  g.scale.setScalar(scale);
  g.userData.parts = { eyes, arms, tip };
  g.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
  return g;
}

// --- props on each island (lit by real numbers) -----------------------------------------------------------------
function prop(key) {
  const g = new THREE.Group();
  const lights = [];
  const add = (mesh, x, y, z, lit) => { mesh.position.set(x, y, z); g.add(mesh); if (lit) lights.push(mesh); return mesh; };
  const dim = () => mat(0x2b2a2f);
  if (key === "trading") for (let i = 0; i < 6; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6 + i * 0.45, 0.5), dim()), -2 + i * 0.75, 0.3 + i * 0.22, 0, true);
  if (key === "stores" || key === "arbitrage") for (let i = 0; i < 5; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.9), dim()), (i % 3) - 1, 0.45 + Math.floor(i / 3) * 0.9, 0, true);
  if (key === "marketing" || key === "websites" || key === "stenos") {
    for (let i = 0; i < 6; i++) add(new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.7, 0.08), dim()), -1.3 + (i % 3) * 1.3, 0.9 + Math.floor(i / 3) * 0.85, 0, true);
  }
  if (key === "lab") for (let i = 0; i < 3; i++) add(new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.45, 1.2, 12), dim()), -1 + i, 0.6, 0, true);
  if (key === "code") for (let i = 0; i < 4; i++) add(new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.18, 0.5), dim()), 0, 0.3 + i * 0.35, 0, true);
  if (key === "knowledge") for (let i = 0; i < 8; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.35, 1.1, 0.8), dim()), -1.6 + i * 0.45, 0.55, 0, true);
  if (key === "reverse") for (let i = 0; i < 6; i++) add(new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.25, 0.7), dim()), -1 + (i % 3) * 1, 0.2 + Math.floor(i / 3) * 0.6, 0, true);
  if (key === "pacifica") add(new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, 0.2, 6), dim()), 0, 1.2, 0, true).rotation.x = Math.PI / 2;
  g.userData.lights = lights;
  return g;
}

// --- a floating island with its warehouse -----------------------------------------------------------------------
function island(key, title, warehouse) {
  const accent = ACCENT[key] ?? BLOOD;
  const g = new THREE.Group();
  const top = new THREE.Mesh(new THREE.CylinderGeometry(6.4, 6.0, 1.1, 48), mat(0x17171c, { roughness: 0.9 }));
  top.receiveShadow = true;
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(6.1, 6.1, 0.06, 48), mat(0xffffff, { map: checker(accent), roughness: 0.55, metalness: 0.1 }));
  deck.position.y = 0.58; deck.receiveShadow = true;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(6.35, 0.2, 8, 64), glow(accent, 1.4));
  rim.rotation.x = Math.PI / 2; rim.position.y = 0.55;
  const rock = new THREE.Mesh(new THREE.ConeGeometry(6.0, 10, 9, 3), mat(tint(accent, 0.78), { flatShading: true, roughness: 1 }));
  rock.rotation.x = Math.PI; rock.position.y = -5.5;
  const pos = rock.geometry.attributes.position;          // jagged underside
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i);
    if (y < 4.9) { pos.setX(i, pos.getX(i) * (0.82 + Math.random() * 0.36)); pos.setZ(i, pos.getZ(i) * (0.82 + Math.random() * 0.36)); }
  }
  rock.geometry.computeVertexNormals();
  g.add(top, deck, rim, rock);
  for (let i = 0; i < 3; i++) {                           // little rocks hanging below
    const pebble = new THREE.Mesh(new THREE.DodecahedronGeometry(0.7 + Math.random() * 0.6), mat(0x2b2228, { flatShading: true }));
    pebble.position.set((Math.random() - 0.5) * 7, -9 - Math.random() * 5, (Math.random() - 0.5) * 7);
    pebble.userData.bob = Math.random() * 6;
    g.add(pebble);
  }
  // the warehouse: walls, a pitched roof, a glowing door and a strip light in the island's colour
  const house = new THREE.Group();
  const walls = new THREE.Mesh(new THREE.BoxGeometry(6.2, 3.4, 4.2), mat(tint(accent, 0.62), { roughness: 0.7 }));
  walls.position.y = 2.25; walls.castShadow = true; walls.receiveShadow = true;
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(2.6, 2.6, 6.6, 3, 1), mat(accent, { roughness: 0.5, metalness: 0.2 }));
  roof.rotation.z = Math.PI / 2; roof.rotation.x = Math.PI / 6; roof.position.y = 4.35; roof.scale.set(1, 1, 0.62); roof.castShadow = true;
  const door = new THREE.Mesh(new THREE.PlaneGeometry(2.0, 2.3), glow(accent, 0.55));
  door.position.set(0, 1.75, 2.11);
  const strip = new THREE.Mesh(new THREE.BoxGeometry(6.3, 0.12, 0.12), glow(accent, 1.5));
  strip.position.set(0, 3.95, 2.12);
  house.add(walls, roof, door, strip);
  house.position.set(0, 0.6, -2.2);
  g.add(house);
  const bot = robot(key);
  bot.position.set(-2.2, 0.62, 2.4);
  g.add(bot);
  const props = prop(key);
  props.position.set(2.4, 0.62, 2.0);
  g.add(props);
  const sign = makeSign();
  sign.position.set(0, 8.6, -1.5);
  sign.userData.draw(title, 0, "", warehouse ? "WAREHOUSE" : "");
  g.add(sign);
  const pool = new THREE.PointLight(accent, mobile ? 0 : 40, 22, 1.6);   // a pool of the island's colour
  pool.position.set(0, 5, 3);
  g.add(pool);
  const menace = [0, 1, 2].map((i) => { const m = menaceSprite("#" + new THREE.Color(accent).getHexString()); m.position.set(3.6 + i * 0.6, 3 + i * 1.6, 1.5); g.add(m); return m; });
  g.userData = { key, rim, bot, props, sign, title, warehouse: warehouse ? "WAREHOUSE" : "", status: "", count: -1, phase: Math.random() * 6, door, strip, menace, accent };
  g.traverse((o) => { o.userData.island = key; });
  return g;
}

// --- Doxa's command tower in the middle -------------------------------------------------------------------------
function commandTower() {
  const g = new THREE.Group();
  const base = new THREE.Mesh(new THREE.CylinderGeometry(9, 8.4, 1.4, 64), mat(0x141418, { roughness: 0.85 }));
  base.receiveShadow = true;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(9, 0.22, 8, 96), glow(BLOOD, 2));
  rim.rotation.x = Math.PI / 2; rim.position.y = 0.7;
  const rock = new THREE.Mesh(new THREE.ConeGeometry(8.4, 15, 10, 3), mat(0x2b2228, { flatShading: true, roughness: 1 }));
  rock.rotation.x = Math.PI; rock.position.y = -8.2;
  const tower = new THREE.Mesh(new THREE.CylinderGeometry(1.8, 3.2, 12, 6), mat(0x1a1a20, { roughness: 0.4, metalness: 0.6 }));
  tower.position.y = 6.6; tower.castShadow = true;
  const rings = [];
  for (let i = 0; i < 4; i++) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.4 - i * 0.25, 0.07, 6, 48), glow(BLOOD, 3));
    ring.rotation.x = Math.PI / 2; ring.position.y = 2.5 + i * 2.6;
    rings.push(ring);
  }
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(3.4, 2.2, 0.6, 32), mat(0x232229, { metalness: 0.5, roughness: 0.4 }));
  deck.position.y = 12.9;
  const doxa = robot("prime", 1.6);
  doxa.position.y = 13.2;
  // Doxa is a hologram-like commander: bone-white edges around its body
  doxa.traverse((o) => { if (o.isMesh && o.material.color && o.material.color.getHex() === 0x1c1b20) o.material = mat(0x0f0f12, { metalness: 0.8, roughness: 0.25 }); });
  const halo = new THREE.Mesh(new THREE.TorusGeometry(3.6, 0.06, 6, 96), glow(BONE, 2.2));
  halo.position.y = 17.4; halo.rotation.x = Math.PI / 2.4;
  const halo2 = halo.clone(); halo2.rotation.x = Math.PI / 1.7; halo2.scale.setScalar(0.85);
  g.add(base, rim, rock, tower, ...rings, deck, doxa, halo, halo2);
  const sign = makeSign();
  sign.position.set(0, 23.5, 0);
  sign.scale.set(10, 3.1, 1);
  sign.userData.draw("Doxa", 0, "", "COMMAND");
  g.add(sign);
  g.userData = { key: "prime", rim, bot: doxa, sign, halos: [halo, halo2], rings, title: "Doxa", warehouse: "COMMAND", status: "", count: -1 };
  g.traverse((o) => { o.userData.island = "prime"; });
  return g;
}

// --- the night: stars, a crescent moon, a city far below --------------------------------------------------------
function sky(scene) {
  const dome = new THREE.Mesh(new THREE.SphereGeometry(700, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x0a0420) }, mid: { value: new THREE.Color(0x3b0f6b) },
      band: { value: new THREE.Color(0xff2e88) }, deep: { value: new THREE.Color(0x12051f) } },
    vertexShader: "varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    // deep purple below, a thin hot-pink dusk band at the horizon, purple then night above
    fragmentShader: "uniform vec3 top; uniform vec3 mid; uniform vec3 band; uniform vec3 deep; varying float h; void main(){ vec3 c = h > 0.03 ? mix(band, mix(mid, top, smoothstep(0.2, 0.75, h)), smoothstep(0.03, 0.2, h)) : mix(deep, band, smoothstep(-0.18, 0.03, h)); gl_FragColor = vec4(c, 1.0); }",
  }));
  scene.add(dome);
  const stars = new THREE.BufferGeometry();
  const pts = [];
  for (let i = 0; i < (mobile ? 900 : 2200); i++) {
    const v = new THREE.Vector3().randomDirection().multiplyScalar(380 + Math.random() * 60);
    v.y = Math.abs(v.y) * 0.9 + 10;
    pts.push(v.x, v.y, v.z);
  }
  stars.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  scene.add(new THREE.Points(stars, new THREE.PointsMaterial({ color: 0xffffff, size: 1.1, sizeAttenuation: true, transparent: true, opacity: 0.85 })));
  const moon = new THREE.Mesh(new THREE.SphereGeometry(22, 48, 32), new THREE.MeshBasicMaterial({ color: 0xf6e3a1 }));
  moon.position.set(-150, 120, -300);
  const bite = new THREE.Mesh(new THREE.SphereGeometry(21, 48, 32), new THREE.MeshBasicMaterial({ color: 0x050507 }));
  bite.position.set(-140, 128, -290);
  scene.add(moon, bite);
  // the city: dark towers in a wide ring far below, with a few lit windows
  const count = mobile ? 140 : 260;
  const towers = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat(0x1a0d2b, { roughness: 1 }), count);
  const windows = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ color: 0xffffff }), count * 3);
  const neon = [0xff3d9a, 0x29d3ff, 0xffd23f, 0xa64dff].map((c) => new THREE.Color(c));
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3();
  let w = 0;
  for (let i = 0; i < count; i++) {
    const a = Math.random() * Math.PI * 2, d = 120 + Math.random() * 120, h = 15 + Math.random() * 70, wd = 6 + Math.random() * 10;
    p.set(Math.cos(a) * d, -60 + h / 2, Math.sin(a) * d);
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -a);
    s.set(wd, h, wd);
    towers.setMatrixAt(i, m.compose(p, q, s));
    for (let j = 0; j < 3; j++) {
      const wp = p.clone().add(new THREE.Vector3(-Math.cos(a) * (wd / 2 + 0.05), (Math.random() - 0.5) * h * 0.8, -Math.sin(a) * (wd / 2 + 0.05)));
      const wq = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -a - Math.PI / 2);
      windows.setColorAt(w, neon[(i + j) % neon.length]);
      windows.setMatrixAt(w++, m.compose(wp, wq, new THREE.Vector3(1.2, 1.6, 1)));
    }
  }
  scene.add(towers, windows);
}

// =================================================================================================================
const HQ3D = {
  ok: supported(),
  build(stage, list, { onPick, onEmpty } = {}) {
    this.dispose();
    this.stage = stage;
    this.onPick = onPick;
    this.onEmpty = onEmpty;
    const renderer = new THREE.WebGLRenderer({ antialias: !mobile, powerPreference: "high-performance", alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, mobile ? 1.5 : 2.5));   // crisp on 4K screens
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.25;
    renderer.shadowMap.enabled = !mobile;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.className = "hq-3d";
    stage.prepend(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0420);
    scene.fog = new THREE.FogExp2(0x1b0a2e, 0.0042);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.5, 900);
    scene.add(new THREE.HemisphereLight(0xff8ad8, 0x2a0a3a, 1.0));
    const key = new THREE.DirectionalLight(0xfff1dc, 2.2);
    key.position.set(-40, 70, 30);
    key.castShadow = !mobile;
    key.shadow.mapSize.set(mobile ? 1024 : 4096, mobile ? 1024 : 4096);
    key.shadow.bias = -0.0004;
    Object.assign(key.shadow.camera, { left: -60, right: 60, top: 60, bottom: -60, near: 10, far: 200 });
    scene.add(key);
    const rimLight = new THREE.DirectionalLight(0xe5383b, 0.9);
    rimLight.position.set(30, 10, -60);
    scene.add(rimLight);
    sky(scene);

    const islands = {};
    const tower = commandTower();
    scene.add(tower);
    islands.prime = tower;
    list.forEach((item, i) => {
      const a = -Math.PI / 2 + (i / list.length) * Math.PI * 2;
      const g = island(item.key, item.name, item.warehouse);
      g.position.set(Math.cos(a) * R, (i % 2) * 1.6, Math.sin(a) * R);
      g.rotation.y = Math.atan2(Math.cos(a), Math.sin(a));  // robot + props face outward, warehouse behind, tower beyond
      g.userData.home = g.position.clone();
      scene.add(g);
      islands[item.key] = g;
    });
    // beams from Doxa to every island, and the conveyor ring with crates
    const beams = {};
    for (const item of list) {
      const to = islands[item.key].position;
      const len = to.length() - 15;
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, len, 6), glow(0x3a3438, 1));
      beam.position.copy(to.clone().setLength(9 + len / 2)).setY(1.2);
      beam.lookAt(new THREE.Vector3(0, 1.2, 0));
      beam.rotateX(Math.PI / 2);
      scene.add(beam);
      beams[item.key] = beam;
    }
    const track = new THREE.Mesh(new THREE.TorusGeometry(R, 0.45, 10, 160), mat(0x0d0d10, { roughness: 0.5, metalness: 0.6 }));
    track.rotation.x = Math.PI / 2; track.position.y = -1.6;
    const lane = new THREE.Mesh(new THREE.TorusGeometry(R, 0.08, 6, 160), glow(BONE, 0.8));
    lane.rotation.x = Math.PI / 2; lane.position.y = -1.1;
    scene.add(track, lane);
    const crates = new THREE.InstancedMesh(new THREE.BoxGeometry(1.0, 0.8, 1.4), mat(BONE, { roughness: 0.5 }), 12);
    const screens = new THREE.InstancedMesh(new THREE.BoxGeometry(0.6, 0.45, 1.42), glow(BLOOD, 2), 12);
    scene.add(crates, screens);

    let composer = null;
    try {
      const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: mobile ? 0 : 4 });
      composer = new EffectComposer(renderer, target);   // anti-aliased even with bloom on (crisp edges on 4K screens)
      composer.addPass(new RenderPass(scene, camera));
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(256, 256), mobile ? 0.42 : 0.55, 0.45, 0.9));
      composer.addPass(new OutputPass());
    } catch { composer = null; }

    Object.assign(this, { renderer, scene, camera, composer, islands, beams, crates, screens, crateCount: 4, list,
      target: new THREE.Vector3(), lookTarget: new THREE.Vector3(), lookNow: new THREE.Vector3(), focus: null,
      azimuth: 0.0, distance: 1, lastInput: performance.now(), dragging: null });
    this.resize();
    this.overview(true);
    this._events();
    this._observer = new ResizeObserver(() => this.resize());
    this._observer.observe(stage);
    this._clock = new THREE.Clock();
    this._frame = 0;
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      if (document.hidden) return;
      this._frame++;
      if (mobile && this._frame % 2) return;                 // ~30 fps on phones: smooth and cool
      this._tick(Math.min(this._clock.getDelta(), 0.1));
    };
    loop();
    return true;
  },

  resize() {
    if (!this.renderer) return;
    const box = this.stage.getBoundingClientRect();
    const w = Math.max(1, box.width), h = Math.max(1, box.height);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.composer) this.composer.setSize(w, h);
    this.distance = this.camera.aspect < 1 ? 1.2 / Math.max(0.5, this.camera.aspect) : 1;  // phones: step back a little
    if (!this.focus) this.overview();
  },

  _overviewPose() {
    const d = 66 * this.distance;
    const a = this.azimuth;
    return { pos: new THREE.Vector3(Math.sin(a) * d, 34 * Math.min(this.distance, 1.6), Math.cos(a) * d), look: new THREE.Vector3(0, -2, 0) };
  },

  overview(instant) {
    this.focus = null;
    const pose = this._overviewPose();
    this.target.copy(pose.pos);
    this.lookTarget.copy(pose.look);
    if (instant) { this.camera.position.copy(pose.pos); this.lookNow.copy(pose.look); this.flight = null; }
    else this._fly();
  },

  _fly() {
    const c = this.camera.position, to = this.target;
    const a0 = Math.atan2(c.z, c.x), a1 = Math.atan2(to.z, to.x);
    const da = Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0));          // shortest way round
    const r0 = Math.hypot(c.x, c.z), r1 = Math.hypot(to.x, to.z);
    this.flight = { t: 0, dur: 1.2 + Math.abs(da) * 0.35, a0, da, r0, r1, y0: c.y, y1: to.y, l0: this.lookNow.clone(),
      swing: Math.min(18, Math.abs(da) * 9) };                              // swing wider for longer turns
  },

  flyTo(key) {
    const g = this.islands[key];
    if (!g) return;
    this.focus = key;
    this.lastInput = performance.now();
    const at = g.position.clone();
    if (key === "prime") {
      const side = this.camera.position.clone().setY(0).normalize().multiplyScalar(30 * Math.max(1, this.distance * 0.8));
      this.target.set(side.x, 22, side.z);
      this.lookTarget.set(0, 13, 0);
      this._fly();
      return;
    }
    const out = at.clone().setY(0).normalize();
    const back = 21 * Math.max(1, this.distance * 0.75);
    this.target.copy(at).add(out.multiplyScalar(back)).add(new THREE.Vector3(0, 10.5, 0));
    this.lookTarget.copy(at).add(new THREE.Vector3(0, 3, 0));
    this._fly();
  },

  update(key, { status = "", count = 0, title } = {}) {
    const g = this.islands && this.islands[key];
    if (!g) return;
    const u = g.userData;
    if (u.status !== status || u.count !== count || (title && title !== u.title)) {
      if (title) u.title = title;
      u.status = status; u.count = count;
      u.sign.userData.draw(u.title, count, status, u.warehouse);
      u.rim.material.emissive.setHex(key === "prime" ? BLOOD : status === "waiting" ? BLOOD : (u.accent ?? BLOOD));
      if (u.props) u.props.userData.lights.forEach((m, i) => {
        const on = i < Math.min(count, u.props.userData.lights.length);
        m.material = on ? glow(ACCENT[key] ?? MUSTARD, 1.3) : mat(0x2b2a2f);
      });
      const beam = this.beams[key];
      if (beam) { beam.material.emissive.setHex(status === "working" ? BLOOD : status === "waiting" ? MUSTARD : 0x3a3438); beam.material.emissiveIntensity = status === "working" ? 3 : 1; }
    }
  },

  setCrates(n) { this.crateCount = Math.max(1, Math.min(12, n)); },

  setArt(key, version) {                     // version = the picture's timestamp (0 = none): reload when it changes
    const g = this.islands && this.islands[key];
    if (!g || g.userData.artVersion === version) return;
    g.userData.artVersion = version;
    if (g.userData.portrait) { g.remove(g.userData.portrait); g.userData.portrait = null; }
    if (!version) return;
    const token = (() => { try { return localStorage.getItem("jarvis.key") || ""; } catch { return ""; } })();
    fetch(`/api/team/character/${key}`, { headers: { authorization: "Bearer " + token } })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((blob) => new THREE.TextureLoader().loadAsync(URL.createObjectURL(blob)))
      .then((texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        const ratio = texture.image.height / texture.image.width;
        const card = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture }));
        const prime = key === "prime";
        card.scale.set(prime ? 6 : 4.2, (prime ? 6 : 4.2) * ratio, 1);
        card.position.set(prime ? 7.5 : -4.8, prime ? 16 : 6.2, prime ? 2 : 1.5);
        g.add(card);
        g.userData.portrait = prime ? null : card;
        if (prime) g.userData.primeCard = card;
        if (g.userData.figure) card.visible = false;
      })
      .catch(() => {});
  },

  setFigure(key, version) {                  // the 3D figure (version = file time, 0 = none) replaces the robot
    const g = this.islands && this.islands[key];
    if (!g || g.userData.figureVersion === version) return;
    g.userData.figureVersion = version;
    if (g.userData.figure) { g.remove(g.userData.figure); g.userData.figure = null; g.userData.bot.visible = true; }
    if (!version) { this._showPortrait(g, true); return; }
    const token = (() => { try { return localStorage.getItem("jarvis.key") || ""; } catch { return ""; } })();
    fetch(`/api/team/figure/${key}?v=${version}`, { headers: { authorization: "Bearer " + token } })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((blob) => new THREE.TextureLoader().loadAsync(URL.createObjectURL(blob)))
      .then((texture) => {
        if (g.userData.figureVersion !== version) return;
        const prime = key === "prime";
        const fig = standee(texture, prime ? 9.5 : 6.4, ACCENT[key] ?? BLOOD, this.renderer.capabilities.getMaxAnisotropy());
        fig.position.copy(g.userData.bot.position);
        if (!prime) fig.position.set(-2.0, 0.62, 2.6);
        g.add(fig);
        g.userData.figure = fig;
        g.userData.bot.visible = false;
        this._showPortrait(g, false);
      })
      .catch(() => {});
  },

  _showPortrait(g, on) {                      // with a 3D figure standing there, the flat poster is hidden
    if (g.userData.portrait) g.userData.portrait.visible = on;
    if (g.userData.primeCard) g.userData.primeCard.visible = on;
  },

  _tick(dt) {
    const t = this._clock.elapsedTime;
    const now = performance.now();
    if (!this.focus && !this.dragging && now - this.lastInput > 9000) {   // idle: the camera drifts around HQ
      this.azimuth += dt * 0.05;
      const pose = this._overviewPose();
      this.target.copy(pose.pos);
    }
    const k = 1 - Math.exp(-dt * 2.6);
    const c = this.camera.position;
    const f = this.flight;
    if (f) {
      // a timed flight in an arc around HQ (cylindrical coordinates): never straight through Doxa's tower
      f.t = Math.min(1, f.t + dt / f.dur);
      const e = f.t < 0.5 ? 4 * f.t ** 3 : 1 - (-2 * f.t + 2) ** 3 / 2;      // ease in-out
      const swing = Math.sin(Math.PI * e) * f.swing;
      const a = f.a0 + f.da * e, r = f.r0 + (f.r1 - f.r0) * e + swing;
      c.set(Math.cos(a) * r, f.y0 + (f.y1 - f.y0) * e + swing * 0.35, Math.sin(a) * r);
      this.lookNow.lerpVectors(f.l0, this.lookTarget, e);
      if (f.t >= 1) this.flight = null;
    } else {
      c.lerp(this.target, k);                                              // small moves: drag, idle drift
      this.lookNow.lerp(this.lookTarget, k);
    }
    this.camera.lookAt(this.lookNow);

    for (const g of Object.values(this.islands)) {
      const u = g.userData;
      if (u.home) g.position.y = u.home.y + Math.sin(t * 0.6 + u.phase) * 0.45;
      const bot = u.bot;
      const working = u.status === "working";
      const parts = bot.userData.parts;
      bot.position.y = (u.key === "prime" ? 13.2 : 0.62) + Math.abs(Math.sin(t * (working ? 6 : 2) + (u.phase || 0))) * (working ? 0.28 : 0.1);
      parts.arms[0].rotation.x = working ? Math.sin(t * 7) * 0.9 : Math.sin(t * 1.5) * 0.08;
      parts.arms[1].rotation.x = working ? -Math.sin(t * 7) * 0.9 : -Math.sin(t * 1.5) * 0.08;
      const blink = u.status === "waiting" ? (Math.sin(t * 8) > 0 ? 6 : 0.5) : 4;
      parts.eyes.forEach((e) => { if (e.material.emissive) e.material.emissiveIntensity = blink; });
      if (bot.userData.spin) bot.userData.spin.rotation.y += dt * (working ? 6 : 1.5);
      if (bot.userData.spirit) bot.userData.spirit.material.opacity = working ? 0.42 + Math.sin(t * 5) * 0.12 : 0.2;
      if (u.halos) { u.halos[0].rotation.z += dt * 0.6; u.halos[1].rotation.z -= dt * 0.45; }
      if (u.rings) u.rings.forEach((r, i) => { r.material.emissiveIntensity = 1.5 + Math.max(0, Math.sin(t * 2.4 - i * 0.9)) * 3; });
      g.children.forEach((c) => { if (c.userData.bob !== undefined) c.position.y += Math.sin(t + c.userData.bob) * 0.004; });
      if (u.door) u.door.material.emissiveIntensity = working ? 0.9 + Math.sin(t * 4) * 0.35 : 0.5;
      if (u.rim && u.key !== "prime") u.rim.material.emissiveIntensity = working ? 2.2 + Math.sin(t * 5) * 0.8 : u.status === "waiting" ? (Math.sin(t * 6) > 0 ? 2.6 : 0.6) : 1.2;
      if (u.menace) u.menace.forEach((m, i) => {            // ゴゴゴ rises around an island that's working
        const cycle = (t * 0.5 + i / 3) % 1;
        m.position.y = 2.5 + i * 1.4 + cycle * 2.2;
        m.material.opacity = working ? Math.sin(cycle * Math.PI) : 0;
        m.material.rotation = Math.sin(t * 3 + i) * 0.15;
      });
      if (u.portrait) u.portrait.position.y = 6.2 + Math.sin(t * 0.9 + (u.phase || 0)) * 0.25;
      const fig = u.figure;
      if (fig) {                                // turn toward the camera (upright), bounce and glow while working
        fig.getWorldPosition(this._v || (this._v = new THREE.Vector3()));
        const yaw = Math.atan2(c.x - this._v.x, c.z - this._v.z) - g.rotation.y;
        fig.rotation.y = yaw + Math.sin(t * 0.7 + (u.phase || 0)) * 0.22;
        const base = u.key === "prime" ? 13.2 : 0.62;
        fig.position.y = base + (working ? Math.abs(Math.sin(t * 5 + (u.phase || 0))) * 0.35 : Math.sin(t * 1.2 + (u.phase || 0)) * 0.06);
        const pulse = working ? 1.6 + Math.sin(t * 6) * 1.1 : u.status === "waiting" ? (Math.sin(t * 6) > 0 ? 2.2 : 0.6) : 0.9;
        fig.userData.edge.material.color.copy(fig.userData.accent).multiplyScalar(pulse);
      }
    }
    // crates riding the conveyor ring
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), one = new THREE.Vector3(1, 1, 1), hidden = new THREE.Vector3(0, 0, 0);
    for (let i = 0; i < 12; i++) {
      if (i >= this.crateCount) {
        this.crates.setMatrixAt(i, m.compose(p.set(0, -500, 0), q, hidden));
        this.screens.setMatrixAt(i, m.compose(p, q, hidden));
        continue;
      }
      const a = t * 0.12 + (i / this.crateCount) * Math.PI * 2;
      p.set(Math.cos(a) * R, -0.55, Math.sin(a) * R);
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -a);
      this.crates.setMatrixAt(i, m.compose(p, q, one));
      this.screens.setMatrixAt(i, m.compose(p.clone().setY(-0.48), q, one));
    }
    this.crates.instanceMatrix.needsUpdate = true;
    this.screens.instanceMatrix.needsUpdate = true;
    if (this.composer) this.composer.render(); else this.renderer.render(this.scene, this.camera);
  },

  _events() {
    const el = this.renderer.domElement;
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
    let down = null;
    this._on = [
      [el, "pointerdown", (e) => {
        down = { x: e.clientX, y: e.clientY, az: this.azimuth };
        this.dragging = null; this.lastInput = performance.now();
        if (!this.focus) this.azimuth = Math.atan2(this.camera.position.x, this.camera.position.z);  // drag from where we are
        down.az = this.azimuth;
      }],
      [el, "pointermove", (e) => {
        if (!down || this.focus) return;
        const dx = e.clientX - down.x;
        if (Math.abs(dx) > 6) {                       // drag to spin around HQ
          this.dragging = true;
          this.azimuth = down.az - dx * 0.006;
          const pose = this._overviewPose();
          this.target.copy(pose.pos);
          this.camera.position.lerp(pose.pos, 0.5);
        }
      }],
      [el, "pointerup", (e) => {
        const wasDrag = this.dragging;
        this.dragging = null;
        this.lastInput = performance.now();
        if (!down || wasDrag) { down = null; return; }
        down = null;
        const box = el.getBoundingClientRect();
        ndc.set(((e.clientX - box.left) / box.width) * 2 - 1, -((e.clientY - box.top) / box.height) * 2 + 1);
        ray.setFromCamera(ndc, this.camera);
        const hit = ray.intersectObjects(Object.values(this.islands), true).find((h) => h.object.userData.island);
        if (hit && this.onPick) this.onPick(hit.object.userData.island);
        else if (!hit && this.focus && this.onEmpty) this.onEmpty();
      }],
      [el, "wheel", (e) => {
        if (this.focus) return;
        e.preventDefault();
        this.distance = Math.max(0.55, Math.min(2.6, this.distance * (e.deltaY > 0 ? 1.08 : 0.93)));
        this.lastInput = performance.now();
        this.target.copy(this._overviewPose().pos);
      }],
    ];
    for (const [node, type, fn] of this._on) node.addEventListener(type, fn, { passive: type !== "wheel" });
  },

  dispose() {
    if (!this.renderer) return;
    cancelAnimationFrame(this._raf);
    this._observer?.disconnect();
    for (const [node, type, fn] of this._on || []) node.removeEventListener(type, fn);
    this.renderer.domElement.remove();
    this.renderer.dispose();
    this.renderer = null;
  },
};

if (HQ3D.ok && !/[?&]2d\b/.test(location.search)) {
  window.HQ3D = HQ3D;
  window.dispatchEvent(new Event("hq3d-ready"));
}
