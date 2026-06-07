import React, { useState } from "react";
import { CITIES } from "../lib/api.js";

export default function BirthForm({ onSubmit, busy, extra }) {
  const [name, setName] = useState(""); const [date, setDate] = useState("1990-08-15"); const [time, setTime] = useState("14:30");
  const [cityIdx, setCityIdx] = useState("0"); const [lat, setLat] = useState(""); const [lon, setLon] = useState(""); const [tz, setTz] = useState("");
  const custom = cityIdx === "custom";
  const place = () => custom
    ? (Number.isNaN(parseFloat(lat)) || Number.isNaN(parseFloat(lon)) || !tz ? null : { lat: parseFloat(lat), lon: parseFloat(lon), tz })
    : (() => { const c = CITIES[parseInt(cityIdx, 10)]; return { lat: c[1], lon: c[2], tz: c[3] }; })();
  const submit = () => { const p = place(); if (!p) return; onSubmit({ name: name.trim() || "Friend", date, time, lat: p.lat, lon: p.lon, tz: p.tz }); };
  return (
    <div className="card">
      <p className="kicker">Birth details</p>
      <div className="grid">
        <div className="full"><label className="fld">Name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" /></div>
        <div><label className="fld">Date of birth</label><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div><label className="fld">Time of birth</label><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></div>
        <div className="full"><label className="fld">Place of birth</label>
          <select value={cityIdx} onChange={(e) => setCityIdx(e.target.value)}>
            {CITIES.map((c, i) => <option key={i} value={i}>{c[0]}</option>)}
            <option value="custom">Custom coordinates…</option>
          </select>
        </div>
        {custom && <div className="full"><div className="grid">
          <div><label className="fld">Latitude</label><input type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} /></div>
          <div><label className="fld">Longitude</label><input type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} /></div>
          <div className="full"><label className="fld">UTC offset</label><input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="+05:30" /></div>
        </div></div>}
        {extra}
      </div>
      <div className="actions">
        <button onClick={submit} disabled={busy}>{busy ? "Casting…" : "Cast reading"}</button>
        {busy && <span className="loader">Casting the chart…</span>}
      </div>
    </div>
  );
}
