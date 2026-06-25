import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import OrreryBg from "./components/OrreryBg.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { initAnalytics } from "./lib/analytics.js";
import "./styles.css";

initAnalytics();   // cookieless Umami; no-op unless VITE_UMAMI_* configured

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <OrreryBg />
    <App />
  </ErrorBoundary>
);
