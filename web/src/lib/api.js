import { auth, PREVIEW } from "./firebase.js";

// In preview (no Firebase config), talk to the local API with the seeded dev key.
const BASE = import.meta.env.VITE_API_BASE || (PREVIEW ? "http://127.0.0.1:8099" : "");
const PREVIEW_KEY = "pro_dev_key";
const PREVIEW_ADMIN_KEY = "test-admin-secret";   // dev-only; matches a locally-booted API

// Real users send a Firebase ID token (never an API key in the browser); the dev
// preview sends the seeded local dev key instead. In prod, admin endpoints are
// authorized by an `admin` custom claim on the same Firebase token.
async function authHeaders(path = "") {
  if (PREVIEW) {
    const h = { "X-API-Key": PREVIEW_KEY };
    if (path.startsWith("/admin") || path.startsWith("/mock")) h["X-Admin-Key"] = PREVIEW_ADMIN_KEY;
    return h;
  }
  const user = auth?.currentUser;
  if (!user) throw new Error("Not signed in.");
  return { Authorization: `Bearer ${await user.getIdToken(true)}` };
}

async function handle(res) {
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    const map = {
      401: "Session expired, sign out and back in.",
      402: detail || "Your plan doesn't include this yet.",
      429: detail || "Limit reached, try again shortly.",
    };
    const err = new Error(map[res.status] || detail || `Request failed (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function apiPost(path, body) {
  const headers = { "Content-Type": "application/json", ...(await authHeaders(path)) };
  return handle(await fetch(`${BASE}${path}`, { method: "POST", headers, body: JSON.stringify(body) }));
}

export async function apiGet(path) {
  return handle(await fetch(`${BASE}${path}`, { headers: await authHeaders(path) }));
}

export async function getTiers() {
  const res = await fetch(`${BASE}/v1/tiers`);
  return res.ok ? res.json() : [];
}

// Curated cities → lat/lon/utc-offset (extend freely).
export const CITIES = [
  ["New Delhi, IN", 28.6139, 77.2090, "+05:30"], ["Gurugram, IN", 28.4595, 77.0266, "+05:30"],
  ["Mumbai, IN", 19.0760, 72.8777, "+05:30"], ["Bengaluru, IN", 12.9716, 77.5946, "+05:30"],
  ["Chennai, IN", 13.0827, 80.2707, "+05:30"], ["Kolkata, IN", 22.5726, 88.3639, "+05:30"],
  ["Hyderabad, IN", 17.3850, 78.4867, "+05:30"], ["Pune, IN", 18.5204, 73.8567, "+05:30"],
  ["Durgapur, IN", 23.5204, 87.3119, "+05:30"], ["Patna, IN", 25.5941, 85.1376, "+05:30"],
  ["London, UK", 51.5074, -0.1278, "+00:00"], ["New York, US", 40.7128, -74.0060, "-05:00"],
  ["Dubai, AE", 25.2048, 55.2708, "+04:00"], ["Singapore, SG", 1.3521, 103.8198, "+08:00"],
];
