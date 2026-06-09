import React, { useState } from "react";
import { apiPost, CITIES } from "../lib/api.js";

// Kundali Matching (Ashtakoot Guna Milan, 36 points) + Manglik. Your locked chart
// vs a partner's. Deterministic scores from the server; this just collects partner
// details and renders the breakdown.
export default function MatchTab() {
  const [name, setName] = useState("");
  const [date, setDate] = useState("1992-03-21");
  const [time, setTime] = useState("09:15");
  const [cityIdx, setCityIdx] = useState(0);
  const [gender, setGender] = useState("male");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async () => {
    const c = CITIES[cityIdx];
    setBusy(true); setErr(""); setRes(null);
    try {
      const r = await apiPost("/v1/match", {
        partner_name: name.trim() || "Partner", date, time, lat: c[1], lon: c[2], tz: c[3],
        self_gender: gender,
      });
      setRes(r);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const a = res?.ashtakoot;
  const pct = a ? Math.round((a.total / a.max) * 100) : 0;

  return (
    <div className="sheet">
      <p className="kicker">Kundali Matching · Guna Milan</p>
      <p className="note" style={{ marginTop: 0 }}>
        Matches <b>your saved chart</b> against a partner's (Ashtakoot 36-point + Manglik). Cast your own chart on the Natal tab first.
      </p>
      <div className="grid">
        <div className="full"><label className="fld">Partner's name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Partner's name" /></div>
        <div><label className="fld">Partner's date of birth</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div><label className="fld">Partner's time of birth</label>
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></div>
        <div className="full"><label className="fld">Partner's place of birth</label>
          <select value={cityIdx} onChange={(e) => setCityIdx(+e.target.value)}>
            {CITIES.map((c, i) => <option key={i} value={i}>{c[0]}</option>)}
          </select></div>
        <div><label className="fld">You are</label>
          <select value={gender} onChange={(e) => setGender(e.target.value)}>
            <option value="male">male (groom)</option>
            <option value="female">female (bride)</option>
            <option value="other">other</option>
          </select></div>
      </div>
      <div className="actions">
        <button onClick={run} disabled={busy}>{busy ? "Matching…" : "Match kundalis"}</button>
        {busy && <span className="loader">Computing Guna Milan…</span>}
      </div>
      {err && <p className="err">{err}</p>}

      {res && (
        <div className="data-block" style={{ marginTop: 16 }}>
          <div className="sec-head">
            <p className="data-h" style={{ marginTop: 0 }}>{a.total} / 36 · {a.verdict}</p>
            <span className="mono" style={{ color: "var(--muted)" }}>{pct}%</span>
          </div>
          <div className="bar-row">
            <span className="bar-track"><span className="bar-fill" style={{ width: `${pct}%` }} /></span>
          </div>
          {res.ai_summary && <p className="role" style={{ fontStyle: "italic", margin: "4px 0 10px" }}>{res.ai_summary}</p>}
          <p className="note">{res.summary}</p>
          {a.kutas && a.kutas.length ? (
            <table className="data-tbl"><thead>
              <tr><th style={{ textAlign: "left" }}>Koota</th><th>Score</th><th style={{ textAlign: "left" }}>Measures</th></tr>
            </thead><tbody>
              {a.kutas.map((k) => (
                <tr key={k.name}>
                  <td>{k.name}</td>
                  <td style={{ whiteSpace: "nowrap", color: k.score === 0 ? "var(--danger,#c0392b)" : "inherit" }}>{k.score} / {k.max}</td>
                  <td style={{ color: "var(--muted)" }}>{k.of}</td>
                </tr>
              ))}
            </tbody></table>
          ) : (
            <p className="note" style={{ color: "var(--brass)" }}>
              The full 8-koota breakdown (Varna, Vashya, Tara, Yoni, Graha Maitri, Gana, Bhakoot, Nadi) unlocks on Pro.
            </p>
          )}
          <p className="data-h" style={{ marginTop: 14 }}>Manglik</p>
          <table className="data-tbl"><tbody>
            <tr><td>You</td><td>{res.self.manglik ? "Manglik" : "Not Manglik"} · {res.self.rashi} · {res.self.nakshatra}</td></tr>
            <tr><td>Partner</td><td>{res.partner.manglik ? "Manglik" : "Not Manglik"} · {res.partner.rashi} · {res.partner.nakshatra}</td></tr>
            <tr><td>Match</td><td>{res.manglik_match.note}</td></tr>
          </tbody></table>
          {(res.disclaimers || []).map((d, i) => <p key={i} className="note" style={{ fontStyle: "italic" }}>{d}</p>)}
        </div>
      )}
    </div>
  );
}
