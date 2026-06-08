import React from "react";

// Tajik Varshphal (annual) data block, shown for the Yearly report. Renders the
// Varsha Pravesha core, Muntha, Varsheshwara (year lord), and the Mudda dasha
// timeline. Reads ReadingResponse.varshphal (computed server-side).
function date(s) {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d) ? s : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function VarshphalData({ varshphal }) {
  if (!varshphal) return null;
  const v = varshphal;
  const mudda = v.mudda_dasha || [];
  return (
    <div className="sheet">
      <p className="kicker">Varshphal {v.year}</p>

      <div className="data-block">
        <p className="data-h">Varsha Pravesha core</p>
        <table className="data-tbl">
          <tbody>
            {v.pravesha_date && <tr><td>Varsha Pravesha</td><td>{date(v.pravesha_date)}{v.vara_lord ? ` · ${v.vara_lord}` : ""}</td></tr>}
            {v.varsha_lagna && <tr><td>Varsha Lagna</td><td>{v.varsha_lagna}</td></tr>}
            {v.varsha_moon && <tr><td>Varsha Moon</td><td>{v.varsha_moon}</td></tr>}
            {v.muntha_sign && <tr><td>Muntha</td><td>{v.muntha_sign}</td></tr>}
            {v.varsheshwara && <tr><td>Varsheshwara (year lord)</td><td>{v.varsheshwara}</td></tr>}
            {v.completed_age != null && <tr><td>Age at varsha</td><td>{v.completed_age} completed · {v.running_age} running</td></tr>}
          </tbody>
        </table>
        {v.approx_positions && (
          <p className="note" style={{ marginTop: 8 }}>
            Varsha Lagna and Moon are illustrative here; the production engine computes the exact
            solar-return positions. Muntha, Varsheshwara, age, and the Mudda timeline are exact.
          </p>
        )}
      </div>

      {mudda.length > 0 && (
        <div className="data-block">
          <p className="data-h">Mudda dasha timeline</p>
          <table className="data-tbl">
            <thead><tr><th>Lord</th><th>Window</th></tr></thead>
            <tbody>
              {mudda.map((m, i) => (
                <tr key={i}><td>{m.lord}</td><td>{date(m.start)} – {date(m.end)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
