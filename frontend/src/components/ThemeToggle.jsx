import { useState } from "react";
import { setNativeBars } from "../lib/platform";

function current() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export default function ThemeToggle({ floating = false }) {
  const [theme, setTheme] = useState(current);

  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* private mode */ }
    setTheme(next);
    // The phone's status bar / browser chrome follows the theme too.
    const bar = next === "light" ? "#f4f5fa" : "#1b1f2e";
    document.querySelectorAll('meta[name="theme-color"]')
            .forEach((m) => m.setAttribute("content", bar));
    setNativeBars(next);
  }

  const label = theme === "light" ? "Switch to dark theme" : "Switch to light theme";
  return (
    <button type="button" onClick={toggle} aria-label={label} title={label}
            className={"theme-toggle" + (floating ? " floating" : "")}>
      {theme === "light" ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      )}
    </button>
  );
}
