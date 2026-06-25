import React, { useEffect, useState } from "react";
import { apiPost } from "../lib/api.js";
import { track } from "../lib/analytics.js";
import CityPicker from "../components/CityPicker.jsx";
import { tzOffsetForDate } from "../lib/geo.js";

const DEFAULT_CITY = { label: "New Delhi, India", lat: 28.6139, lon: 77.2090, tz: "Asia/Kolkata" };

// Daily Vedic almanac (Panchang) for a chosen place. Place uses the same worldwide
// city search + manual coordinates as the Natal / Matching forms. Deterministic,
// free for all signed-in users; no LLM, no credits.
export default function PanchangTab() {
  const [city, setCity] = useState(DEFAULT_CITY);
  const [manual, setManual] = useState(false);
  const [lat, setLat] = useState(""); const [lon, setLon] = useState(""); const [tz, setTz] = useState("+05:30");
  const [place, setPlace] = useState(DEFAULT_CITY.label);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = (req, label) => {
    setBusy(true); setErr(""); setPlace(label);
    apiPost("/v1/panchang", req).then((d) => { setData(d); track("panchang"); }).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  const today = () => new Date().toISOString().slice(0, 10);
  const loadCity = (c) => load({ lat: c.lat, lon: c.lon, tz: tzOffsetForDate(c.tz, today(), "12:00") }, c.label);
  const loadManual = () => {
    if (Number.isNaN(parseFloat(lat)) || Number.isNaN(parseFloat(lon)) || !tz) {
      setErr("Enter latitude, longitude and UTC offset."); return;
    }
    load({ lat: parseFloat(lat), lon: parseFloat(lon), tz }, `${lat}, ${lon}`);
  };
  useEffect(() => { loadCity(DEFAULT_CITY); /* eslint-disable-next-line */ }, []);

  const Row = ({ label, value }) => value ? <tr><td>{label}</td><td>{value}</td></tr> : null;
  const p = data || {};
  const nm = (x) => (x && typeof x === "object") ? (x.name || x.lord || "") : x;

  return (
    <div className="sheet">
      <p className="kicker">Panchang · daily almanac</p>
      <div className="grid">
        {!manual ? (
          <div className="full"><label className="fld">Place</label>
            <CityPicker value={city?.label} onSelect={(c) => { setCity(c); loadCity(c); }} placeholder="Search any city worldwide…" /></div>
        ) : (
          <>
            <div><label className="fld">Latitude</label>
              <input value={lat} onChange={(e) => setLat(e.target.value)} placeholder="e.g. 28.6139" /></div>
            <div><label className="fld">Longitude</label>
              <input value={lon} onChange={(e) => setLon(e.target.value)} placeholder="e.g. 77.2090" /></div>
            <div><label className="fld">UTC offset</label>
              <input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="+05:30" /></div>
          </>
        )}
      </div>
      <div className="actions">
        {manual && <button onClick={loadManual} disabled={busy}>Show Panchang</button>}
        <button className="ghost" type="button" onClick={() => { setManual(!manual); setErr(""); }}>
          {manual ? "Search a city instead" : "Enter coordinates"}
        </button>
        {busy && <span className="loader">Computing…</span>}
      </div>
      {err && <p className="err">{err}</p>}
      {data && (
        <div className="data-block">
          <p className="data-h">{place} · {data.date}</p>
          <table className="data-tbl"><tbody>
            <Row label="Vara (weekday)" value={p.vara ? `${nm(p.vara)}${p.vara.lord ? ` · lord ${p.vara.lord}` : ""}` : null} />
            <Row label="Tithi" value={p.tithi ? `${nm(p.tithi)}${p.tithi.paksha ? ` · ${p.tithi.paksha}` : ""}` : null} />
            <Row label="Nakshatra" value={p.nakshatra ? `${nm(p.nakshatra)}${p.nakshatra.pada ? ` · pada ${p.nakshatra.pada}` : ""}${p.nakshatra.lord ? ` · lord ${p.nakshatra.lord}` : ""}` : null} />
            <Row label="Yoga" value={nm(p.yoga)} />
            <Row label="Karana" value={nm(p.karana)} />
            <Row label="Moon phase" value={p.moon_phase ? `${p.moon_phase.phase_name || ""}${p.moon_phase.illumination_pct != null ? ` · ${Math.round(p.moon_phase.illumination_pct)}% lit` : ""}` : null} />
            <Row label="Hora (now)" value={p.hora ? `${p.hora.hora_lord || ""}` : null} />
          </tbody></table>
          <p className="note">A daily snapshot of the lunar day, asterism and yoga for the chosen place.</p>
        </div>
      )}
    </div>
  );
}
