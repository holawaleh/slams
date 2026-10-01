// Mobile / touch / PWA checks for the dashboard, on real Chrome.
//
//   node scripts/ui-check.mjs [baseUrl] [screenshotDir]
//
// Needs the app served (npm run build && npx vite preview) and a backend
// with the demo data (python manage.py seed_demo --password Demo-pass1).
// Exits non-zero if any page overflows sideways, a field would make an
// iPhone zoom, or touch targets are too small.
import { chromium } from "playwright-core";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:4173";
const SHOTS = process.argv[3] || "ui-shots";
const USER = process.env.UI_USER || "demo_admin";
const PASS = process.env.UI_PASS || "Demo-pass1";
mkdirSync(SHOTS, { recursive: true });

const chrome = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].find(existsSync);

const DEVICES = [
  { name: "android-phone", viewport: { width: 412, height: 915 }, dpr: 2.6, touch: true, mobile: true },
  { name: "iphone",        viewport: { width: 390, height: 844 }, dpr: 3,   touch: true, mobile: true },
  { name: "small-phone",   viewport: { width: 360, height: 740 }, dpr: 3,   touch: true, mobile: true },
  { name: "tablet-portrait",  viewport: { width: 820, height: 1180 }, dpr: 2, touch: true, mobile: true },
  { name: "tablet-landscape", viewport: { width: 1180, height: 820 }, dpr: 2, touch: true, mobile: true },
  { name: "desktop",       viewport: { width: 1366, height: 768 }, dpr: 1,  touch: false, mobile: false },
];

const PAGES = ["/dashboard", "/students", "/cards", "/cards?tab=activity", "/courses",
  "/timetable", "/reports", "/settings/profile", "/settings/password",
  "/settings/team", "/settings/roles", "/settings/devices", "/settings/organisation",
  "/settings/audit"];
const PUBLIC = ["/", "/login", "/register"];

// Runs in the page: what sticks out sideways, which targets are small,
// which fields are under 16px.
function audit({ isTouch, isPhone }) {
  const vw = window.innerWidth;
  const scrollers = ".table-wrap, .tt-card, .tabs, .pick-list";
  const visible = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
  };
  const overflow = document.documentElement.scrollWidth - vw;
  const sticking = [];
  if (overflow > 1) {
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest(scrollers) || !visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1) sticking.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} (right ${Math.round(r.right)})`);
      if (sticking.length > 5) break;
    }
  }
  const small = [];
  if (isTouch) {
    for (const el of document.querySelectorAll("button, select, input:not([type=hidden]), .navlink, [role=tab]")) {
      if (!visible(el) || el.closest(".sidebar:not(.open)") && isPhone) continue;
      const r = el.getBoundingClientRect();
      const box = el.type === "checkbox" || el.type === "radio" ? 20 : 36;
      if (r.height < box || r.width < box) {
        small.push(`${el.tagName.toLowerCase()} "${(el.innerText || el.getAttribute("aria-label") || el.name || el.type || "").trim().slice(0, 24)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
  }
  const zoomers = [];
  if (isPhone) {
    for (const el of document.querySelectorAll("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")) {
      if (!visible(el)) continue;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < 16) zoomers.push(`${el.id || el.name || el.placeholder || el.type} ${fs}px`);
    }
  }
  return { overflow: Math.max(0, overflow), sticking, small, zoomers };
}

let failures = 0;
const report = (dev, page, a) => {
  const problems = [];
  if (a.overflow > 1) problems.push(`overflows sideways by ${a.overflow}px: ${a.sticking.join(", ")}`);
  if (a.zoomers.length) problems.push(`fields under 16px (iPhone zooms): ${a.zoomers.join(", ")}`);
  if (a.small.length) problems.push(`small touch targets: ${a.small.slice(0, 4).join("; ")}${a.small.length > 4 ? ` (+${a.small.length - 4})` : ""}`);
  if (problems.length) { failures++; console.log(`  FAIL ${dev} ${page}\n       - ${problems.join("\n       - ")}`); }
  else console.log(`  ok   ${dev} ${page}`);
};

const browser = await chromium.launch({ executablePath: chrome, headless: true });

for (const d of DEVICES) {
  const ctx = await browser.newContext({
    viewport: d.viewport, deviceScaleFactor: d.dpr, hasTouch: d.touch, isMobile: d.mobile,
    serviceWorkers: "block",              // test the pages, not a cached copy
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const isPhone = d.viewport.width <= 600;
  const slug = (p) => p.replace(/[/?=]+/g, "_").replace(/^_|_$/g, "") || "home";

  for (const p of PUBLIC) {
    await page.goto(BASE + p, { waitUntil: "networkidle" });
    report(d.name, p, await page.evaluate(audit, { isTouch: d.touch, isPhone }));
    await page.screenshot({ path: join(SHOTS, `${d.name}-${slug(p)}.png`), fullPage: false });
  }

  // Sign in through the real form.
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.fill("#u", USER);
  await page.fill("#p", PASS);
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/auth/login/") &&
                                r.request().method() === "POST", { timeout: 30000 }),
    page.locator('button[type="submit"]').click(),
  ]);
  if (resp.status() !== 200) throw new Error(`sign-in failed: HTTP ${resp.status()} ${await resp.text()}`);
  await page.waitForURL("**/dashboard", { timeout: 20000 });

  for (const p of PAGES) {
    await page.goto(BASE + p, { waitUntil: "networkidle" });
    await page.waitForTimeout(250);
    report(d.name, p, await page.evaluate(audit, { isTouch: d.touch, isPhone }));
    await page.screenshot({ path: join(SHOTS, `${d.name}-${slug(p)}.png`), fullPage: false });
  }

  // Phone interactions: the drawer, and a dialog as a bottom sheet.
  if (isPhone) {
    await page.goto(BASE + "/students", { waitUntil: "networkidle" });
    await page.locator(".menu-btn").tap();
    await page.waitForTimeout(350);
    const drawer = await page.locator(".sidebar").boundingBox();
    const drawerOk = drawer && drawer.x >= -1;
    await page.screenshot({ path: join(SHOTS, `${d.name}-drawer.png`) });
    await page.locator(".navlink", { hasText: "Courses" }).tap();
    await page.waitForURL("**/courses");
    await page.waitForTimeout(350);
    const closed = await page.locator(".sidebar").boundingBox();
    const closesOk = closed && closed.x + closed.width <= 1;
    console.log(`  ${drawerOk && closesOk ? "ok  " : "FAIL"} ${d.name} drawer opens on tap and closes after navigating`);
    if (!(drawerOk && closesOk)) failures++;

    await page.goto(BASE + "/students", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Add student" }).first().tap();
    await page.waitForTimeout(400);
    const sheet = await page.locator(".modal").boundingBox();
    const sheetOk = sheet && Math.abs(sheet.y + sheet.height - d.viewport.height) < 2 && sheet.width >= d.viewport.width - 1;
    console.log(`  ${sheetOk ? "ok  " : "FAIL"} ${d.name} dialog is a full-width bottom sheet`);
    if (!sheetOk) failures++;
    await page.screenshot({ path: join(SHOTS, `${d.name}-sheet.png`) });
  }
  if (errors.length) { failures++; console.log(`  FAIL ${d.name} script errors: ${errors.slice(0, 3).join(" | ")}`); }
  await ctx.close();
}

// The PWA: manifest, icons, and the service worker taking control.
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  const pwa = await page.evaluate(async () => {
    const link = document.querySelector('link[rel="manifest"]');
    const m = await (await fetch(link.href)).json();
    const icons = await Promise.all(m.icons.map(async (i) => (await fetch(new URL(i.src, link.href))).status));
    const reg = await Promise.race([navigator.serviceWorker.ready.then(() => true),
                                    new Promise((r) => setTimeout(() => r(false), 10000))]);
    return { name: m.name, display: m.display, start: m.start_url, icons, sw: reg,
             maskable: m.icons.some((i) => i.purpose === "maskable") };
  });
  const ok = pwa.sw && pwa.icons.every((s) => s === 200) && pwa.maskable && pwa.display === "standalone";
  console.log(`  ${ok ? "ok  " : "FAIL"} PWA: "${pwa.name}", display ${pwa.display}, start ${pwa.start}, icons ${pwa.icons.join("/")}, maskable ${pwa.maskable}, service worker ${pwa.sw ? "active" : "NOT active"}`);
  if (!ok) failures++;

  // Offline: the app shell must still open once the worker has it.
  await page.reload({ waitUntil: "networkidle" });
  await ctx.setOffline(true);
  await page.goto(BASE + "/login", { waitUntil: "domcontentloaded" }).catch(() => {});
  const offlineOk = await page.locator("form").count() > 0;
  console.log(`  ${offlineOk ? "ok  " : "FAIL"} PWA opens offline from its cache`);
  if (!offlineOk) failures++;
  await ctx.close();
}

await browser.close();
console.log(failures ? `\n${failures} problem(s)` : "\nall checks passed");
process.exit(failures ? 1 : 0);
