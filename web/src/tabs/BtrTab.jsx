import React, { useState } from "react";
import Reading from "../components/Reading.jsx";
import CityPicker from "../components/CityPicker.jsx";
import { apiPost } from "../lib/api.js";
import { tzOffsetForDate } from "../lib/geo.js";

const EVENT_TYPES = ["marriage", "childbirth", "job change", "relocation", "father's death",
  "mother's death", "accident", "major illness", "promotion", "education milestone"];

// Birth-Time Rectification (Enterprise), narrow an uncertain birth time from
// dated life events. Shows a fine hairline/brass confidence meter (DESIGN.md).
export default function BtrTab() {
  const [name, setName] = useState("");
  const [date, setDate] = useState("1990-08-15");
  const [time, setTime] = useState("14:30");
  const [city, setCity] = useState(null);
  const [gender, setGender] = useState("other");
  const [sunrise, setSunrise] = useState("06:00");
  const [events, setEvents] = useState([{ date: "", type: "" }, { date: "", type: "" }, { date: "", type: "" }]);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const setEv = (i, k, v) => setEvents((es) => es.map((e, j) => (j === i ? { ...e, [k]: v } : e)));
  const addEv = () => setEvents((es) => (es.length < 8 ? [...es, { date: "", type: "" }] : es));
  const rmEv = (i) => setEvents((es) => es.filter((_, j) => j !== i));

  const rectify = async () => {
    const evs = events.filter((e) => e.date && e.type.trim());
    if (evs.length < 1) { setErr("Add at least one dated life event (3-5 ideal)."); return; }
    if (!city) { setErr("Search and select the place of birth."); return; }
    setErr(""); setBusy(true); setData(null);
    try {
      const resp = await apiPost("/v1/btr", {
        name: name.trim() || "Friend", date, time,
        tz: tzOffsetForDate(city.tz, date, time), lat: city.lat, lon: city.lon,
        gender, sunrise_time: sunrise, events: evs,
      });
      setData(resp);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const rec = data?.rectification?.recommended;
  const cands = data?.rectification?.candidates || [];

  return (
    <div>
      <p className="note" style={{ marginTop: 0, marginBottom: 16 }}>
        Birth-Time Rectification, narrow an uncertain birth time from dated life events, triangulated
        across the classical methods. The result is a confident window, not a certainty.
      </p>

      <div className="card glass">
        <p className="kicker">Birth details</p>
        <div className="grid">
          <div className="full"><label className="fld">Name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" /></div>
          <div><label className="fld">Date of birth</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
          <div><label className="fld">Approx. time</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></div>
          <div><label className="fld">Gender</label>
            <select value={gender} onChange={(e) => setGender(e.target.value)}>
              <option value="male">Male</option><option value="female">Female</option><option value="other">Other</option>
            </select></div>
          <div><label className="fld">Sunrise (approx)</label>
            <input type="time" value={sunrise} onChange={(e) => setSunrise(e.target.value)} /></div>
          <div className="full"><label className="fld">Place of birth</label>
            <CityPicker value={city?.label} onSelect={setCity} /></div>
        </div>
      </div>

      <div className="card glass" style={{ marginTop: 16 }}>
        <p className="kicker">Dated life events (3-5 ideal)</p>
        {events.map((e, i) => (
          <div className="grid" key={i} style={{ marginBottom: 10, alignItems: "end" }}>
            <div><label className="fld">Date</label>
              <input type="date" value={e.date} onChange={(ev) => setEv(i, "date", ev.target.value)} /></div>
            <div><label className="fld">What happened</label>
              <input list="btr-types" value={e.type} onChange={(ev) => setEv(i, "type", ev.target.value)} placeholder="e.g. marriage" /></div>
            {events.length > 1 && (
              <div className="full"><button className="ghost" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => rmEv(i)}>Remove</button></div>
            )}
          </div>
        ))}
        <datalist id="btr-types">{EVENT_TYPES.map((t) => <option key={t} value={t} />)}</datalist>
        <div className="actions">
          <button className="ghost" onClick={addEv} disabled={events.length >= 8}>Add event</button>
          <button onClick={rectify} disabled={busy}>{busy ? "Rectifying…" : "Rectify"}</button>
          {busy && <span className="loader">Triangulating the methods…</span>}
        </div>
      </div>

      <p className="err">{err}</p>

      {rec && (
        <div className="sheet">
          <p className="kicker">Most likely birth time</p>
          <div className="meter">
            <div className="meter-track"><div className="meter-fill" style={{ width: `${rec.confidence || 0}%` }} /></div>
            <span className="meter-label">
              <b>{rec.time}</b> · {rec.confidence != null ? `${rec.confidence}% confidence` : "confidence, "}
              {rec.ascendant_sign ? ` · ${rec.ascendant_sign} ascendant` : ""}
            </span>
          </div>
          {cands.length > 0 && (
            <p className="note">Candidates: {cands.map((c) => `${c.time}${c.confidence != null ? ` (${c.confidence}%)` : ""}`).join(" · ")}</p>
          )}
          {(data?.rectification?.confidence_score || data?.rectification?.rating) && (
            <p className="note" style={{ marginTop: 6 }}>
              {data.rectification.confidence_score && <>Score <b>{data.rectification.confidence_score}</b></>}
              {data.rectification.rating && <> · Rating <b>{data.rectification.rating}</b></>}
            </p>
          )}
        </div>
      )}

      {(data?.rectification?.method_rows?.length > 0) && (
        <div className="sheet">
          <p className="kicker">Rectification methods</p>
          <table className="data-tbl">
            <thead><tr><th>Method</th><th>Verdict</th><th>Detail</th></tr></thead>
            <tbody>
              {data.rectification.method_rows.map((m, i) => (
                <tr key={i}><td>{m.method}</td><td>{m.verdict}</td><td>{m.detail}</td></tr>
              ))}
            </tbody>
          </table>
          {data.rectification.events?.length > 0 && (
            <>
              <p className="data-h" style={{ marginTop: 18 }}>Event calibration</p>
              <table className="data-tbl">
                <thead><tr><th>Event</th><th>Date</th></tr></thead>
                <tbody>
                  {data.rectification.events.map((e, i) => (
                    <tr key={i}><td>{e.type}</td><td>{e.date}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      <Reading data={data} />
    </div>
  );
}
