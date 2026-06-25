import React, { useState } from "react";
import BirthForm from "../components/BirthForm.jsx";
import Reading from "../components/Reading.jsx";
import Charts from "../components/Charts.jsx";
import ChartData from "../components/ChartData.jsx";
import VarshphalData from "../components/VarshphalData.jsx";
import AnchorBlock from "../components/AnchorBlock.jsx";
import Locked from "../components/Locked.jsx";
import CheckoutButton from "../components/CheckoutButton.jsx";
import { apiPost } from "../lib/api.js";
import { track } from "../lib/analytics.js";

const NOW_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => NOW_YEAR - 1 + i); // last year .. +6

// Natal / Maha-Kundali / Yearly. They differ only by the report_type they send.
// The cast RESULT (data/chart/anchor) is lifted to App via result/onResult, so it
// persists across tab switches and a re-cast never blanks the screen.
export default function ReadingTab({ reportType, blurb, extra, onCast, features = [], locked,
                                    consented, onConsent, refresh, result, onResult }) {
  const isYearly = reportType === "yearly";
  const [year, setYear] = useState(NOW_YEAR);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const r = result || {};

  // Casting computes the anchor, charts and reading together. The reading is
  // tier-gated (free still gets chart + anchor). We DON'T clear the old result up
  // front: each block is only replaced when its request succeeds, so a transient
  // failure (e.g. a brief rate-limit) can't wipe the charts already on screen.
  const cast = async (b) => {
    setErr(""); setBusy(true);
    try {
      const body = { ...b, report_type: reportType };
      if (isYearly) body.year = year;
      const [resp, chartResp, ancResp] = await Promise.all([
        apiPost("/v1/reading", body).catch((e) => ({ __err: e })),
        apiPost("/v1/chart", b).catch(() => null),
        apiPost("/v1/anchor", b).catch(() => null),
      ]);
      const out = { data: r.data || null, chart: r.chart || null, anchor: r.anchor || null,
                    readingLocked: false, birth: b };
      if (resp && resp.__err) {
        if (resp.__err.status === 402) { out.readingLocked = true; out.data = null; }
        else throw resp.__err;
      } else { out.data = resp; }
      if (chartResp) out.chart = chartResp.chart;
      if (ancResp) out.anchor = ancResp.anchor;
      onResult && onResult(out);
      onCast && onCast(b);
      track("reading", { type: reportType, locked: !!out.readingLocked });   // activation event
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
      {blurb && <p className="note lead" style={{ marginTop: 0, marginBottom: 16 }}>{blurb}</p>}
      <BirthForm onSubmit={cast} busy={busy} extra={isYearly ? yearPicker : extra} locked={locked} consented={consented} onConsent={onConsent} />
      <p className="err">{err}</p>
      {r.anchor && <AnchorBlock anchor={r.anchor} />}
      <Charts chart={r.chart} features={features} />
      <ChartData chart={r.chart} features={features} />
      {r.data?.varshphal && <VarshphalData varshphal={r.data.varshphal} />}
      {r.readingLocked && (
        <div className="sheet">
          <Locked title="The written reading" tier="Basic"
                  note="Your chart and anchor are shown above. Upgrade to Basic or higher for the grounded, sectioned reading with Light and Shadow."
                  cta={<CheckoutButton tier="basic" label="Basic" onPaid={refresh} />} />
        </div>
      )}
      <Reading data={r.data} birth={r.birth} />
    </div>
  );
}
