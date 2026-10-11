// A tiny deterministic animation timeline for the demo's graphics.
//
// Scenes describe each element's state at key times; seek(t) sets every element's style for
// time t. Nothing depends on the wall clock, so the renderer can step frame by frame and every
// render of a scene is identical.
//
//   anim(".title", [[0.2, { o: 0, y: 24 }], [0.9, { o: 1, y: 0 }], [4.2, { o: 1 }], [4.8, { o: 0 }]]);
//
// Properties: o (opacity), x and y (px), s (scale), blur (px), wipe (0-100, reveals from the
// left), and any CSS custom property given as "--name".

const tracks = [];
const calls = [];

const EASE = {
  linear: (t) => t,
  out: (t) => 1 - Math.pow(1 - t, 3),
  in: (t) => t * t * t,
  inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  // Material's "emphasized decelerate", approximated.
  emph: (t) => 1 - Math.pow(1 - t, 4.2),
};

const DEFAULTS = { o: 1, x: 0, y: 0, s: 1, blur: 0, wipe: 100 };

export function anim(target, keys, ease = "emph") {
  const els = typeof target === "string" ? [...document.querySelectorAll(target)] : [target];
  if (!els.length) throw new Error(`anim: nothing matches ${target}`);
  for (const el of els) tracks.push({ el, keys: keys.map(([t, props]) => [t, props]), ease: EASE[ease] ?? ease });
}

/** Run `fn(t)` on every seek, for things a key frame cannot express, such as counting numbers. */
export function every(fn) {
  calls.push(fn);
}

function valueAt(keys, name, t, ease) {
  const withProp = keys.filter(([, p]) => name in p);
  if (!withProp.length) return undefined;
  if (t <= withProp[0][0]) return withProp[0][1][name];
  for (let i = 1; i < withProp.length; i++) {
    const [t1, p1] = withProp[i];
    const [t0, p0] = withProp[i - 1];
    if (t <= t1) {
      const k = ease((t - t0) / (t1 - t0 || 1));
      return p0[name] + (p1[name] - p0[name]) * k;
    }
  }
  return withProp[withProp.length - 1][1][name];
}

export function seek(t) {
  for (const { el, keys, ease } of tracks) {
    const names = new Set(keys.flatMap(([, p]) => Object.keys(p)));
    const v = Object.fromEntries([...names].map((n) => [n, valueAt(keys, n, t, ease)]));
    const get = (n) => v[n] ?? DEFAULTS[n];
    if (names.has("o")) el.style.opacity = get("o");
    if (names.has("x") || names.has("y") || names.has("s")) {
      el.style.transform = `translate(${get("x")}px, ${get("y")}px) scale(${get("s")})`;
    }
    if (names.has("blur")) el.style.filter = get("blur") > 0.01 ? `blur(${get("blur")}px)` : "none";
    if (names.has("wipe")) el.style.clipPath = `inset(-20% ${100 - get("wipe")}% -20% -2%)`;
    for (const n of names) if (n.startsWith("--")) el.style.setProperty(n, get(n));
  }
  for (const fn of calls) fn(t);
}

/** Scene parameters from the page's URL: ?p=<JSON>. */
export const params = (() => {
  try {
    return JSON.parse(new URLSearchParams(location.search).get("p") || "{}");
  } catch {
    return {};
  }
})();

/** Called by the renderer once fonts are in. */
export function ready(duration) {
  window.DURATION = duration;
  window.seek = seek;
  document.fonts.ready.then(() => {
    seek(0);
    window.READY = true;
  });
}
