import React, { useState } from "react";
import CityPicker from "./CityPicker.jsx";
import { tzOffsetForDate } from "../lib/geo.js";

// Birth details, rendered as a transparent "glass" panel so the celestial field
// shows through. Place of birth is any city worldwide (geocoded), with a manual
// coordinates fallback.
export default function BirthForm({ onSubmit, busy, extra, locked }) {
  const [name, setName] = useState("");
  const [date, setDate] = useState("1990-08-15");
  const [time, setTime] = useState("14:30");
  const [city, setCity] = useState(null);
  const [manual, setManual] = useState(false);
  const [lat, setLat] = useState(""); const [lon, setLon] = useState(""); const [tz, setTz] = useState("+05:30");
  const [err, setErr] = useState("");

  const submit = () => {
    let p;
    if (manual) {
      if (Number.isNaN(parseFloat(lat)) || Number.isNaN(parseFloat(lon)) || !tz) {
        setErr("Enter latitude, longitude and UTC offset."); return;
      }
      p = { lat: parseFloat(lat), lon: parseFloat(lon), tz, place: "Custom coordinates" };
    } else {
      if (!city) { setErr("Search and select your place of birth."); return; }
      p = { lat: city.lat, lon: city.lon, tz: tzOffsetForDate(city.tz, date, time), place: city.label };
    }
    setErr("");
    onSubmit({ name: name.trim() || "Friend", date, time, lat: p.lat, lon: p.lon, tz: p.tz, place: p.place });
  };

  // Locked mode: birth details saved to the account (one native per account).
  if (locked && locked.date) {
    const castLocked = () => onSubmit({
      name: locked.name || "Friend", date: locked.date, time: locked.time,
      lat: locked.lat, lon: locked.lon, tz: locked.tz, place: locked.place,
    });
    return (
      <div className="card glass">
        <p className="kicker">Birth details · locked</p>
        <div className="locked-birth">
          <div className="lb-name">{locked.name || "Your chart"}</div>
          <div>{locked.date} · {locked.time} · UTC {locked.tz}</div>
          <div>{locked.place || `${Number(locked.lat).toFixed(2)}, ${Number(locked.lon).toFixed(2)}`}</div>
        </div>
        <p className="note">Saved and locked to your account (one chart per account). Contact support to change them.</p>
        <div className="grid">{extra}</div>
        <div className="actions">
          <button onClick={castLocked} disabled={busy}>{busy ? "Casting…" : "Cast reading"}</button>
          {busy && <span className="loader">Casting the chart…</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="card glass">
      <p className="kicker">Birth details</p>
      <div className="grid">
        <div className="full"><label className="fld">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" /></div>
        <div><label className="fld">Date of birth</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div><label className="fld">Time of birth</label>
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></div>
        {!manual ? (
          <div className="full"><label className="fld">Place of birth</label>
            <CityPicker value={city?.label} onSelect={setCity} /></div>
        ) : (
          <div className="full"><div className="grid">
            <div><label className="fld">Latitude</label><input type="number" step="0.0001" value={lat} onChange={(e) => setLat(e.target.value)} /></div>
            <div><label className="fld">Longitude</label><input type="number" step="0.0001" value={lon} onChange={(e) => setLon(e.target.value)} /></div>
            <div className="full"><label className="fld">UTC offset</label><input value={tz} onChange={(e) => setTz(e.target.value)} placeholder="+05:30" /></div>
          </div></div>
        )}
        {extra}
      </div>
      <div className="actions">
        <button onClick={submit} disabled={busy}>{busy ? "Casting…" : "Cast reading"}</button>
        <button className="ghost" type="button" onClick={() => { setManual(!manual); setErr(""); }}>
          {manual ? "Search a city instead" : "Enter coordinates"}
        </button>
        {busy && <span className="loader">Casting the chart…</span>}
      </div>
      {err && <p className="err">{err}</p>}
    </div>
  );
}
