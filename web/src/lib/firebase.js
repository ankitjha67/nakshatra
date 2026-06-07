import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const cfg = {
  apiKey: import.meta.env.VITE_FB_API_KEY,
  authDomain: import.meta.env.VITE_FB_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FB_PROJECT_ID,
};

// The Firebase *web* config is not secret (it ships in client code), but with
// none supplied we can't do real auth. `firebaseReady` lets the app fall back to
// a dev-only preview (see PREVIEW in App.jsx / api.js) instead of white-screening.
export const firebaseReady = Boolean(cfg.apiKey && cfg.authDomain && cfg.projectId);

// Dev-only escape hatch: when running `npm run dev` with no Firebase config, render
// the signed-in shell with a mock user so the UI is reviewable without secrets.
// Never true in a production build.
export const PREVIEW = import.meta.env.DEV && !firebaseReady;

export const app = firebaseReady ? initializeApp(cfg) : null;
export const auth = firebaseReady ? getAuth(app) : null;
