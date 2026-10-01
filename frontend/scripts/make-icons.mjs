// Renders the SLAMS app icons from one SVG design, using the Chrome or
// Edge already on this machine, so no image library is needed.
//
//   node scripts/make-icons.mjs
//
// Writes the PWA icons into public/ and, when an android/ project exists,
// the Android launcher icons into its res/ folders.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BROWSERS = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];
const browser = BROWSERS.find(existsSync);
if (!browser) throw new Error("Chrome or Edge is needed to render the icons.");

const C1 = "#6c5ef5", C2 = "#a855c7";
const gradient = `<linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="${C1}"/><stop offset="1" stop-color="${C2}"/></linearGradient>`;
// The check mark from the sidebar logo (a 24x24 design).
const check = (scale, offset) =>
  `<polyline points="4 13 9 18 20 6" fill="none" stroke="#fff" stroke-width="2.6"
    stroke-linecap="round" stroke-linejoin="round"
    transform="translate(${offset} ${offset}) scale(${scale})"/>`;

// "any": rounded square on transparent. The check fills ~60%.
const anySvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>${gradient}</defs>
  <rect width="512" height="512" rx="112" fill="url(#g)"/>
  ${check(13, 100)}</svg>`;
// "maskable" and launcher foreground: full bleed, check inside the 66%
// safe circle that Android and maskable masks always keep.
const fullSvg = (withBg) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>${gradient}</defs>
  ${withBg ? '<rect width="512" height="512" fill="url(#g)"/>' : ""}
  ${check(9.5, 142)}</svg>`;
const roundSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>${gradient}</defs><circle cx="256" cy="256" r="256" fill="url(#g)"/>
  ${check(13, 100)}</svg>`;

const work = join(tmpdir(), "slams-icons");
mkdirSync(work, { recursive: true });

function render(svg, size, out, transparent = true) {
  const html = join(work, `i${size}.html`);
  writeFileSync(html, `<!doctype html><html><body style="margin:0;overflow:hidden;background:transparent">
    <div style="width:${size}px;height:${size}px">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</div>
    </body></html>`);
  mkdirSync(dirname(out), { recursive: true });
  execFileSync(browser, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars",
    `--window-size=${size},${size}`, `--screenshot=${out}`,
    ...(transparent ? ["--default-background-color=00000000"] : []),
    pathToFileURL(html).href,
  ], { stdio: "ignore" });
  if (!existsSync(out)) throw new Error(`failed to render ${out}`);
  console.log("wrote", out.replace(root, "."));
}

const pub = join(root, "public");
writeFileSync(join(pub, "favicon.svg"), anySvg);
console.log("wrote ./public/favicon.svg");
render(anySvg, 192, join(pub, "pwa-192.png"));
render(anySvg, 512, join(pub, "pwa-512.png"));
render(fullSvg(true), 512, join(pub, "maskable-512.png"), false);
render(fullSvg(true), 180, join(pub, "apple-touch-icon.png"), false);

// Android launcher icons, if the Capacitor project has been created.
const res = join(root, "android", "app", "src", "main", "res");
if (existsSync(res)) {
  const densities = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 };
  for (const [d, px] of Object.entries(densities)) {
    render(anySvg, px, join(res, `mipmap-${d}`, "ic_launcher.png"));
    render(roundSvg, px, join(res, `mipmap-${d}`, "ic_launcher_round.png"));
    // Adaptive icon foreground is 108dp with the visible part in the middle 72dp.
    render(fullSvg(false), Math.round(px * 108 / 48),
           join(res, `mipmap-${d}`, "ic_launcher_foreground.png"));
  }
  // Background of the adaptive icon: the brand gradient's first colour.
  writeFileSync(join(res, "values", "ic_launcher_background.xml"),
    `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${C1}</color>\n</resources>\n`);
  console.log("wrote android launcher icons");
}
rmSync(work, { recursive: true, force: true });
