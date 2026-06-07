import { auth } from "./firebase.js";

const BASE = import.meta.env.VITE_API_BASE;

// Authenticated POST to the cloud API using the Firebase ID token (never an API key in the browser).
export async function apiPost(path, body) {
  const user = auth.currentUser;
  if (!user) throw new Error("Not signed in.");
  const token = await user.getIdToken(true);
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch {}
    const map = { 401: "Session expired — sign out and back in.", 402: detail || "Your plan doesn't include this yet.", 429: detail || "Limit reached — try again shortly." };
    throw new Error(map[res.status] || detail || `Request failed (${res.status}).`);
  }
  return res.json();
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
