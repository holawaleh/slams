import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { isNative, isStandalone, setupNative } from "./lib/platform";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);

if (isStandalone()) document.documentElement.classList.add("standalone");

if (isNative) {
  // The Android app ships its files inside the APK, so it needs no
  // service worker; it does need the back button and status bar.
  setupNative();
} else if (import.meta.env.PROD && "serviceWorker" in navigator) {
  // Installed PWA: keep the app shell for offline start, and pick up a new
  // version on the next load after a deploy.
  import("virtual:pwa-register").then(({ registerSW }) =>
    registerSW({ immediate: true }));
}
