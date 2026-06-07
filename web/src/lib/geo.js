// Worldwide city search via the Open-Meteo geocoding API (free, no key, CORS-enabled).
// Returns lat/lon + the IANA timezone for any city on earth.
export async function searchCities(q) {
  const query = (q || "").trim();
  if (query.length < 2) return [];
  const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(query)}&count=8&language=en&format=json`;
  try {
    const r = await fetch(url);
    if (!r.ok) return [];
    const d = await r.json();
    return (d.results || []).map((c) => ({
      id: c.id,
      name: c.name,
      lat: c.latitude,
      lon: c.longitude,
      tz: c.timezone,                 // IANA, e.g. "Asia/Kolkata"
      label: [c.name, c.admin1, c.country].filter(Boolean).join(", "),
    }));
  } catch {
    return [];
  }
}

// Resolve an IANA timezone to a fixed UTC offset ("+05:30") for the given birth
// date/time, so historical DST is handled. Falls back to UTC on any failure.
export function tzOffsetForDate(ianaTz, dateStr, timeStr) {
  try {
    const d = new Date(`${dateStr}T${timeStr || "12:00"}:00`);
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: ianaTz, timeZoneName: "longOffset" }).formatToParts(d);
    const name = (parts.find((p) => p.type === "timeZoneName") || {}).value || "GMT+00:00";
    const m = name.match(/GMT([+-])(\d{1,2})(?::?(\d{2}))?/);
    if (!m) return "+00:00";
    return `${m[1]}${m[2].padStart(2, "0")}:${m[3] || "00"}`;
  } catch {
    return "+00:00";
  }
}
