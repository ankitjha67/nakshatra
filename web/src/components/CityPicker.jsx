import React, { useRef, useState } from "react";
import { searchCities } from "../lib/geo.js";

// Type-to-search any city worldwide; onSelect gets {name, lat, lon, tz(IANA), label}.
export default function CityPicker({ value, onSelect, placeholder = "Search any city worldwide…" }) {
  const [q, setQ] = useState(value || "");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const tmr = useRef();

  const onChange = (e) => {
    const v = e.target.value;
    setQ(v); setOpen(true);
    clearTimeout(tmr.current);
    if (v.trim().length < 2) { setResults([]); return; }
    setBusy(true);
    tmr.current = setTimeout(async () => {
      try { setResults(await searchCities(v)); } finally { setBusy(false); }
    }, 280);
  };
  const pick = (c) => { setQ(c.label); setResults([]); setOpen(false); onSelect(c); };

  return (
    <div className="city">
      <input value={q} onChange={onChange} onFocus={() => q && setOpen(true)}
             onBlur={() => setTimeout(() => setOpen(false), 150)}
             placeholder={placeholder} autoComplete="off" spellCheck="false" />
      {open && q.trim().length >= 2 && (
        <div className="city-pop">
          {busy && <div className="city-opt muted">Searching…</div>}
          {!busy && results.length === 0 && <div className="city-opt muted">No matches</div>}
          {results.map((c) => (
            <div key={c.id} className="city-opt" onMouseDown={() => pick(c)}>{c.label}</div>
          ))}
        </div>
      )}
    </div>
  );
}
