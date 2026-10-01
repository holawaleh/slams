// Where the app is running - a browser tab, an installed PWA, or the
// Android app built with Capacitor - and the few things that differ.
import { Capacitor } from "@capacitor/core";

export const isNative = Capacitor.isNativePlatform();

export const isStandalone = () =>
  isNative ||
  window.matchMedia?.("(display-mode: standalone)").matches ||
  window.navigator.standalone === true;          // iOS home-screen app

// ---- status bar colour in the Android app ----

export async function setNativeBars(theme) {
  if (!isNative) return;
  try {
    const { StatusBar, Style } = await import("@capacitor/status-bar");
    // Style.Dark = light text, for the dark theme.
    await StatusBar.setStyle({ style: theme === "light" ? Style.Light : Style.Dark });
    await StatusBar.setBackgroundColor({ color: theme === "light" ? "#f4f5fa" : "#1b1f2e" });
  } catch {
    /* older Android or plugin missing: the default bar is fine */
  }
}

// ---- Android back button ----
// Closes whatever is on top first - a dialog, the menu drawer, the
// account menu - then goes back a page, and only leaves the app from the
// first screen. Without this, back from any page exits straight away.

function closeTopLayer() {
  if (document.querySelector(".modal-scrim")) {
    // Modal.jsx closes on Escape.
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    return true;
  }
  const scrim = document.querySelector(".scrim");
  if (scrim) {
    scrim.click();          // the drawer or the account menu
    return true;
  }
  return false;
}

export async function setupNative() {
  if (!isNative) return;
  const theme = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  setNativeBars(theme);
  const { App } = await import("@capacitor/app");
  App.addListener("backButton", ({ canGoBack }) => {
    if (closeTopLayer()) return;
    if (canGoBack && window.history.length > 1) window.history.back();
    else App.exitApp();
  });
}

// ---- "Install app" for the PWA ----
// Chrome and Edge offer installation through an event that has to be kept
// until the user asks; Safari has no such event (Share > Add to Home Screen).

let deferred = null;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn(!!deferred));

if (!isNative) {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferred = e;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    notify();
  });
}

export function onInstallAvailable(fn) {
  listeners.add(fn);
  fn(!!deferred);
  return () => listeners.delete(fn);
}

export async function promptInstall() {
  if (!deferred) return false;
  deferred.prompt();
  const { outcome } = await deferred.userChoice;
  deferred = null;
  notify();
  return outcome === "accepted";
}
