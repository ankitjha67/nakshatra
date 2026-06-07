import React, { useState } from "react";
import BirthForm from "../components/BirthForm.jsx";
import Reading from "../components/Reading.jsx";
import { apiPost } from "../lib/api.js";

const NOW_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => NOW_YEAR - 1 + i); // last year .. +6

// Natal / Maha-Kundali / Yearly. They differ only by the report_type they send;
// Yearly also sends a `year` (Varshphal) chosen from a small picker in the form.
export default function ReadingTab({ reportType, blurb, extra, onCast }) {
  const isYearly = reportType === "yearly";
  const [year, setYear] = useState(NOW_YEAR);
  const [data, setData] = useState(null); const [birth, setBirth] = useState(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const cast = async (b) => {
    setErr(""); setBusy(true); setData(null);
    try {
      const body = { ...b, report_type: reportType };
      if (isYearly) body.year = year;
      const resp = await apiPost("/v1/reading", body);
      setBirth(b); setData(resp);
      onCast && onCast(b);          // share the cast chart so Chat can ground on it
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const yearPicker = isYearly ? (
    <div className="full">
      <label className="fld">Year (Varshphal)</label>
      <select value={year} onChange={(e) => setYear(parseInt(e.target.value, 10))}>
        {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
    </div>
  ) : null;
  return (
    <div>
      {blurb && <p className="note" style={{ marginTop: 0, marginBottom: 16 }}>{blurb}</p>}
      <BirthForm onSubmit={cast} busy={busy} extra={isYearly ? yearPicker : extra} />
      <p className="err">{err}</p>
      <Reading data={data} birth={birth} />
    </div>
  );
}
