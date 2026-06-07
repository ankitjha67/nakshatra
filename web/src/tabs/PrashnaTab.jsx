import React, { useState } from "react";
import Reading from "../components/Reading.jsx";
import { apiPost, CITIES } from "../lib/api.js";

// Prashna / KP horary, a chart is cast for the moment of asking (not a birth time).
// One clear question + where you're asking from; the verdict is grounded and premise-neutral.
export default function PrashnaTab() {
  const [q, setQ] = useState("");
  const [cityIdx, setCityIdx] = useState("0");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const ask = async () => {
    const question = q.trim();
    if (!question || busy) return;
    setErr(""); setBusy(true); setData(null);
    try {
      const c = CITIES[parseInt(cityIdx, 10)];
      const resp = await apiPost("/v1/prashna", { question, lat: c[1], lon: c[2], tz: c[3] });
      setData(resp);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div>
      <p className="note" style={{ marginTop: 0, marginBottom: 16 }}>
        KP horary, a chart is cast for the moment you ask. Pose one clear question; the verdict is read
        from the relevant house's cuspal sub-lord, with a neutral “if-not” branch. No premise is assumed true.
      </p>
      <div className="card">
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
            <select value={cityIdx} onChange={(e) => setCityIdx(e.target.value)}>
              {CITIES.map((c, i) => <option key={i} value={i}>{c[0]}</option>)}
            </select>
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
