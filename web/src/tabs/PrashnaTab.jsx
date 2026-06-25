import React, { useState } from "react";
import Reading from "../components/Reading.jsx";
import CityPicker from "../components/CityPicker.jsx";
import { apiPost } from "../lib/api.js";
import { track } from "../lib/analytics.js";
import { tzOffsetForDate } from "../lib/geo.js";

// Prashna / KP horary, a chart is cast for the moment of asking (not a birth time).
// One clear question + where you're asking from; the verdict is grounded and premise-neutral.
export default function PrashnaTab() {
  const [q, setQ] = useState("");
  const [city, setCity] = useState(null);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    if (!city) { setErr("Search and select where you are asking from."); return; }
    setErr(""); setBusy(true); setData(null);
    try {
      const now = new Date();
      const tz = tzOffsetForDate(city.tz, now.toISOString().slice(0, 10), now.toTimeString().slice(0, 5));
      const resp = await apiPost("/v1/prashna", { question, lat: city.lat, lon: city.lon, tz });
      setData(resp);
      track("prashna");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div>
      <p className="note lead" style={{ marginTop: 0, marginBottom: 16 }}>
        KP horary, a chart is cast for the moment you ask. Pose one clear question; the verdict is read
        from the relevant house's cuspal sub-lord, with a neutral “if-not” branch. No premise is assumed true.
      </p>
      <div className="card glass">
        <p className="kicker">Your question</p>
        <div className="grid">
          <div className="full">
            <label className="fld">Question</label>
            <input value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
                   placeholder="e.g. Will the new role come through this year?" />
          </div>
          <div className="full">
            <label className="fld">Where you are asking from</label>
            <CityPicker value={city?.label} onSelect={setCity} />
          </div>
        </div>
        <div className="actions">
          <button onClick={ask} disabled={busy || !q.trim()}>{busy ? "Casting…" : "Ask"}</button>
          {busy && <span className="loader">Casting the prashna chart…</span>}
        </div>
      </div>
      <p className="err">{err}</p>
      <Reading data={data} />
    </div>
  );
}
