import React, { useState } from "react";
import BirthForm from "../components/BirthForm.jsx";
import Reading from "../components/Reading.jsx";
import Charts from "../components/Charts.jsx";
import ChartData from "../components/ChartData.jsx";
import VarshphalData from "../components/VarshphalData.jsx";
import AnchorBlock from "../components/AnchorBlock.jsx";
import Locked from "../components/Locked.jsx";
import { apiPost } from "../lib/api.js";

const NOW_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => NOW_YEAR - 1 + i); // last year .. +6

// Natal / Maha-Kundali / Yearly. They differ only by the report_type they send;
// Yearly also sends a `year` (Varshphal) chosen from a small picker in the form.
// Flow follows the Maha-Jyotish protocol: enter details -> ANCHOR verification
// (Tropical vs Sidereal Asc/Moon + Nakshatra lock) -> confirm -> full report.
export default function ReadingTab({ reportType, blurb, extra, onCast, features = [] }) {
  const isYearly = reportType === "yearly";
  const has = (f) => features.includes(f);
  const [year, setYear] = useState(NOW_YEAR);
  const [data, setData] = useState(null); const [birth, setBirth] = useState(null);
  const [chart, setChart] = useState(null);
  const [anchor, setAnchor] = useState(null);   // informational header (engine-computed)
  const [readingLocked, setReadingLocked] = useState(false);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");

  // The engine is authoritative, so there is no external verify step: casting
  // computes the anchor, charts, and full reading together and shows them all.
  // The reading itself is tier-gated; a free user still gets the chart + anchor,
  // with an upgrade nudge where the written reading would be (402 from the API).
  const cast = async (b) => {
    setErr(""); setBusy(true); setData(null); setChart(null); setAnchor(null); setReadingLocked(false);
    try {
      const body = { ...b, report_type: reportType };
      if (isYearly) body.year = year;
      const [resp, chartResp, ancResp] = await Promise.all([
        apiPost("/v1/reading", body).catch((e) => ({ __err: e })),
        apiPost("/v1/chart", b).catch(() => null),
        apiPost("/v1/anchor", b).catch(() => null),
      ]);
      if (resp && resp.__err) {
        if (resp.__err.status === 402) setReadingLocked(true);
        else throw resp.__err;
      } else { setData(resp); }
      if (chartResp) setChart(chartResp.chart);
      if (ancResp) setAnchor(ancResp.anchor);
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
      {anchor && <AnchorBlock anchor={anchor} />}
      <Charts chart={chart} features={features} />
      <ChartData chart={chart} features={features} />
      {data?.varshphal && <VarshphalData varshphal={data.varshphal} />}
      {readingLocked && (
        <div className="sheet">
          <Locked title="The written reading" tier="Basic"
                  note="Your chart and anchor are shown above. Upgrade to Basic or higher for the grounded, sectioned reading with Light and Shadow." />
        </div>
      )}
      <Reading data={data} birth={birth} />
    </div>
  );
}
