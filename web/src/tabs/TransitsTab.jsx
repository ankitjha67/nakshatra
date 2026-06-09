import React, { useEffect, useState } from "react";
import { apiPost } from "../lib/api.js";

const HOUSE_THEME = {
  1: "self & vitality", 2: "money & speech", 3: "effort & siblings", 4: "home & mind",
  5: "creativity & children", 6: "work, health & rivals", 7: "partnership", 8: "change & depth",
  9: "fortune & dharma", 10: "career & status", 11: "gains & networks", 12: "rest & expense",
};

// Gochar: current transits over the user's natal chart. Deterministic; uses the
// saved chart, so no inputs. Basic+.
export default function TransitsTab() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    apiPost("/v1/transits", {}).then(setData).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  }, []);

  if (busy) return <p className="loader" style={{ paddingTop: 20 }}>Reading current transits…</p>;
  if (err) return <div className="sheet"><p className="kicker">Transits · Gochar</p><p className="err">{err}</p></div>;
  const d = data || {};
  const ss = d.sade_sati || {};
  const dt = d.double_transit || {};

  return (
    <div className="sheet">
      <p className="kicker">Transits · Gochar</p>
      <p className="note" style={{ marginTop: 0 }}>Where the planets are moving today, read against your {d.ascendant} ascendant ({d.date}).</p>

      <div className="data-block">
        <p className="data-h">Planets now</p>
        <table className="data-tbl"><thead>
          <tr><th style={{ textAlign: "left" }}>Planet</th><th style={{ textAlign: "left" }}>Sign</th><th>House</th><th style={{ textAlign: "left" }}>Activates</th></tr>
        </thead><tbody>
          {(d.transits || []).map((t) => (
            <tr key={t.planet}>
              <td>{t.planet}{t.retrograde ? " ℞" : ""}</td>
              <td>{t.sign}</td>
              <td>{t.house || "—"}</td>
              <td style={{ color: "var(--muted)" }}>{HOUSE_THEME[t.house] || ""}</td>
            </tr>
          ))}
        </tbody></table>
      </div>

      <div className="data-block">
        <p className="data-h">Key periods now</p>
        <table className="data-tbl"><tbody>
          {d.current_dasha?.mahadasha && (
            <tr><td>Dasha</td><td>{d.current_dasha.mahadasha} Mahadasha{d.current_dasha.antardasha ? ` · ${d.current_dasha.antardasha} Antardasha` : ""}</td></tr>
          )}
          <tr><td>Sade Sati</td><td>{ss.active ? `Active · ${ss.phase || ""} (Saturn in ${ss.saturn_sign || "?"})` : "Not active"}</td></tr>
          {dt.active && <tr><td>Double transit</td><td>Saturn + Jupiter active over house(s) {(dt.houses || []).join(", ")}</td></tr>}
        </tbody></table>
        <p className="note">Transits show the current sky over your birth chart, the prevailing influences, not fixed daily events.</p>
      </div>
    </div>
  );
}
