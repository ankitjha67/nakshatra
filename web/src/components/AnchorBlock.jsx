import React from "react";

// Anchor Block. An informational header shown above every reading: the Western
// Tropical vs Vedic Sidereal Ascendant & Moon, the Nakshatra lock, and the
// preliminary danger-zone flags. The cloud engine computes all of this precisely
// (Lahiri ayanamsa, Placidus-KP), so there is no external "verify" step.
export default function AnchorBlock({ anchor }) {
  if (!anchor) return null;
  const a = anchor;
  const tz = a.timezone || {};
  const sid = a.sidereal || {};
  const tro = a.tropical || {};
  const nak = a.nakshatra || {};

  const fmt = (x) => (x && x.fmt) || "—";

  return (
    <div className="sheet anchor">
      <p className="kicker">Chart anchor</p>
      <h3 className="anchor-title">{a.name} · chart anchor</h3>
      <p className="note" style={{ marginTop: 4 }}>
        Computed precisely by the engine ({a.ayanamsa} ayanamsa, {a.house_system} houses). The
        Western Tropical and Vedic Sidereal Ascendant and Moon, with the Nakshatra lock, are shown
        for transparency.
      </p>

      <div className="anchor-meta">
        <span><b>Born</b> {a.input?.date} · {a.input?.time}</span>
        {a.input?.place && <span><b>Place</b> {a.input.place}</span>}
        <span><b>Coords</b> {a.input?.lat}, {a.input?.lon}</span>
        <span><b>Timezone</b> UTC{tz.offset}</span>
        <span><b>Ayanamsa</b> {a.ayanamsa} ({a.ayanamsa_deg}&deg;)</span>
        <span><b>Houses</b> {a.house_system}</span>
      </div>

      <table className="anchor-tbl">
        <thead>
          <tr><th>System</th><th>Ascendant</th><th>Moon</th></tr>
        </thead>
        <tbody>
          <tr><td>Western Tropical</td><td>{fmt(tro.asc)}</td><td>{fmt(tro.moon)}</td></tr>
          <tr><td>Vedic Sidereal</td><td>{fmt(sid.asc)}</td><td>{fmt(sid.moon)}</td></tr>
        </tbody>
      </table>

      {nak.name && (
        <p className="anchor-nak">
          <b>Nakshatra lock:</b> {nak.name}{nak.pada ? `, Pada ${nak.pada}` : ""}
          {nak.lord ? ` · Lord ${nak.lord}` : ""}
        </p>
      )}

      {(a.danger_flags?.length > 0 || a.checks?.length > 0) && (
        <div className="anchor-flags">
          <p className="kicker">Preliminary danger-zone flags</p>
          <table className="anchor-tbl">
            <tbody>
              {(a.danger_flags || []).map((f, i) => (
                <tr key={`f${i}`}><td>{f.factor}</td><td>{f.status}</td></tr>
              ))}
              {(a.checks || []).map((c, i) => (
                <tr key={`c${i}`}><td>{c.label}</td><td>{c.value}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </div>
  );
}
