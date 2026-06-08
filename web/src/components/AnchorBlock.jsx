import React from "react";

// Maha-Jyotish Anchor Verification Block. Shown after birth details are entered
// and BEFORE the full Maha-Kundali, the user verifies the Tropical vs Sidereal
// Ascendant & Moon and the Nakshatra lock against an external panchang
// (DrikPanchang / AstroSage), then confirms or re-enters. This is the protocol's
// "verify before you read" gate.
export default function AnchorBlock({ anchor, busy, onConfirm, onReject }) {
  if (!anchor) return null;
  const a = anchor;
  const tz = a.timezone || {};
  const sid = a.sidereal || {};
  const tro = a.tropical || {};
  const nak = a.nakshatra || {};

  const fmt = (x) => (x && x.fmt) || "—";

  return (
    <div className="sheet anchor">
      <p className="kicker">Anchor verification</p>
      <h3 className="anchor-title">{a.name} · chart anchor</h3>
      <p className="note" style={{ marginTop: 4 }}>
        The Maha-Jyotish protocol verifies the anchor before the full reading. Please check the
        Ascendant, Moon, and Nakshatra below against DrikPanchang or AstroSage, then confirm.
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

      <div className="actions">
        <button onClick={onConfirm} disabled={busy}>
          {busy ? "Building the report…" : "Yes, this matches, proceed"}
        </button>
        <button className="ghost" onClick={onReject} disabled={busy}>
          No, re-enter details
        </button>
      </div>
      <p className="note" style={{ marginTop: 8 }}>
        If a value is off, the birth time is the usual cause. Re-enter details to re-anchor.
      </p>
    </div>
  );
}
