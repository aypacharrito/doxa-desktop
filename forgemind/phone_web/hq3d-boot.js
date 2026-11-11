/* Loads the 3D HQ (hq3d.js + three.js, ~700 KB) only on the laptop. the owner 2026-11-09: "on the phone we want it simple …
   I don't want anything to change on my phone": phones keep the light 2D HQ and download nothing extra.
   ?3d forces the 3D world on any device, ?2d turns it off everywhere. */
const small = matchMedia("(max-width: 900px), (pointer: coarse)").matches;
// 1.38.2: the laptop opens the art view (hqart.js, the Higgsfield renders); ?3d opens this 3D world instead.
const want = /[?&]3d\b/.test(location.search) && !/[?&]2d\b/.test(location.search);
void small;
if (want) import("./hq3d.js").catch(() => { /* WebGL or loading failed: the 2D HQ simply stays */ });
