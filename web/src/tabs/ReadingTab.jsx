import React, { useState } from "react";
import BirthForm from "../components/BirthForm.jsx";
import Reading from "../components/Reading.jsx";
import { apiPost } from "../lib/api.js";

// Natal / Maha-Kundali / (Yearly via `extra` year picker). Differ only by report_type sent.
export default function ReadingTab({ reportType, blurb, extra }) {
  const [data, setData] = useState(null); const [birth, setBirth] = useState(null);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const cast = async (b) => {
    setErr(""); setBusy(true); setData(null);
    try {
      const resp = await apiPost("/v1/reading", { ...b, report_type: reportType });
      setBirth(b); setData(resp);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div>
      {blurb && <p className="note" style={{ marginTop: 0, marginBottom: 16 }}>{blurb}</p>}
      <BirthForm onSubmit={cast} busy={busy} extra={extra} />
      <p className="err">{err}</p>
      <Reading data={data} birth={birth} />
    </div>
  );
}
