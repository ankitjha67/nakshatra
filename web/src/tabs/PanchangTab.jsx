import React, { useEffect, useState } from "react";
import { apiPost, CITIES } from "../lib/api.js";

// Daily Vedic almanac (Panchang) for a chosen place. Deterministic, free for all
// signed-in users; no LLM, no credits. A daily engagement surface every Vedic app has.
export default function PanchangTab() {
  const [cityIdx, setCityIdx] = useState(0);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = (idx) => {
    const c = CITIES[idx];
    setBusy(true); setErr("");
    apiPost("/v1/panchang", { lat: c[1], lon: c[2], tz: c[3] })
      .then(setData).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  useEffect(() => { load(cityIdx); /* eslint-disable-next-line */ }, [cityIdx]);

  const Row = ({ label, value }) => value ? (
    <tr><td>{label}</td><td>{value}</td></tr>
  ) : null;
  const p = data || {};
  const nm = (x) => (x && typeof x === "object") ? (x.name || x.lord || JSON.stringify(x)) : x;

  return (
    <div className="sheet">
      <p className="kicker">Panchang · daily almanac</p>
      <div className="admin-row" style={{ marginBottom: 12 }}>
        <label className="fld" style={{ marginRight: 8 }}>Place</label>
        <select value={cityIdx} onChange={(e) => setCityIdx(+e.target.value)}>
          {CITIES.map((c, i) => <option key={i} value={i}>{c[0]}</option>)}
        </select>
        {busy && <span className="loader" style={{ marginLeft: 10 }}>Computing…</span>}
      </div>
      {err && <p className="err">{err}</p>}
      {data && (
        <div className="data-block">
          <p className="data-h">{CITIES[cityIdx][0]} · {data.date}</p>
          <table className="data-tbl"><tbody>
            <Row label="Vara (weekday)" value={p.vara ? `${nm(p.vara)}${p.vara.lord ? ` · lord ${p.vara.lord}` : ""}` : null} />
            <Row label="Tithi" value={p.tithi ? `${nm(p.tithi)}${p.tithi.paksha ? ` · ${p.tithi.paksha}` : ""}` : null} />
            <Row label="Nakshatra" value={p.nakshatra ? `${nm(p.nakshatra)}${p.nakshatra.pada ? ` · pada ${p.nakshatra.pada}` : ""}${p.nakshatra.lord ? ` · lord ${p.nakshatra.lord}` : ""}` : null} />
            <Row label="Yoga" value={nm(p.yoga)} />
            <Row label="Karana" value={nm(p.karana)} />
            <Row label="Moon phase" value={p.moon_phase ? `${p.moon_phase.phase_name || ""}${p.moon_phase.illumination_pct != null ? ` · ${Math.round(p.moon_phase.illumination_pct)}% lit` : ""}` : null} />
            <Row label="Hora (now)" value={p.hora ? `${p.hora.hora_lord || ""}` : null} />
          </tbody></table>
          <p className="note">A daily snapshot of the lunar day, asterism and yoga for the chosen place. Recompute by switching place.</p>
        </div>
      )}
    </div>
  );
}
