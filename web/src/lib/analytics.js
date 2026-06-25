// Umami product analytics — privacy-first: cookieless, no PII, honors Do-Not-Track.
// Dormant until configured: set VITE_UMAMI_SRC (e.g. https://cloud.umami.is/script.js
// or your self-hosted URL) and VITE_UMAMI_WEBSITE_ID in web/.env. Because it sets no
// cookies and collects no personal data, it needs no consent banner (see Privacy Policy).
const SRC = import.meta.env.VITE_UMAMI_SRC || "";
const ID = import.meta.env.VITE_UMAMI_WEBSITE_ID || "";

export const analyticsEnabled = !!(SRC && ID);

export function initAnalytics() {
  if (!analyticsEnabled || typeof document === "undefined") return;
  if (document.querySelector("script[data-umami]")) return;       // load once
  const s = document.createElement("script");
  s.async = true;
  s.defer = true;
  s.src = SRC;
  s.dataset.websiteId = ID;
  s.dataset.umami = "1";
  document.head.appendChild(s);
}

// Custom event (e.g. track("reading", { type: "maha_kundali" })). Never throws —
// analytics must never break the app.
export function track(event, data) {
  try { window.umami?.track?.(event, data); } catch { /* no-op */ }
}

// SPA "pageview" for a tab change, so Umami's pages report reflects feature usage.
export function trackPage(tab) {
  try { window.umami?.track?.((p) => ({ ...p, url: "/" + tab, title: tab })); } catch { /* no-op */ }
}
