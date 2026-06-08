import React from "react";
import Locked from "./Locked.jsx";

// Factual chart-data tables shown alongside the reading (like the birth charts,
// these are raw computed facts for trust, not interpretation, that stays in the
// reading). Reads the engine chart JSON defensively; each block hides itself if
// its data isn't present, so it works with the mock and the real engine alike.
const GRAHA_ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"];
const KP_HIGHLIGHT = ["H1", "H6", "H7", "H10", "H11", "H12"];

function fmtStatus(st) {
  if (!st) return "Normal";
  const bits = [];
  const dig = st.dignity || "Normal";
  if (dig && dig !== "Normal") bits.push(dig);
  if (st.retrograde) bits.push("Retrograde");
  if (st.combust) bits.push("Combust");
  if (st.gandanta) bits.push("Gandanta");
  if (st.mrityu_bhaga) bits.push("Mrityu Bhaga");
  return bits.length ? bits.join(", ") : "Normal";
}

function date(s) {
  if (!s) return "";
  const d = new Date(s);
  return isNaN(d) ? s : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function ChartData({ chart, features = [] }) {
  if (!chart) return null;
  // tier capabilities: tables_basic = planetary + Vimshottari dasha; tables_full = the rest.
  // When features is empty (preview / pre-load) fall back to data presence (no gating).
  const unknown = features.length === 0;
  const hasBasic = unknown || features.includes("tables_basic");
  const hasFull = unknown || features.includes("tables_full");
  const cb = chart.chart || chart;
  const planets = cb.planets || {};
  const asc = cb.asc || {};
  const karakas = chart.jaimini_karakas || {};
  const ds = chart.dasha_systems || {};
  const vim = (ds.vimshottari || {}).current || {};
  const yog = (ds.yogini || {}).current || {};
  const jc = (ds.jaimini_chara || {}).current || {};
  const cusps = (chart.kp_significators || {}).cusps || {};
  const num = chart.numerology || {};
  const ya = chart.yogi_avayogi || {};
  const bb = chart.bhrigu_bindu || {};
  const dt = chart.double_transit || {};
  const ss = chart.sade_sati || {};

  const hasPlanets = Object.keys(planets).length > 0;
  const hasKarakas = Object.keys(karakas).length > 0;
  const hasDasha = vim.mahadasha || yog.yogini || jc.sign;
  const hasKp = Object.keys(cusps).length > 0;
  const hasNum = num.psychic != null || num.destiny != null;
  const ak = karakas.Atmakaraka, amk = karakas.Amatyakaraka;
  const hasNadi = ya.yogi_lord || bb.sign || ak || amk;
  const hasTransit = dt.saturn_sign || dt.jupiter_sign || ss.active != null;

  return (
    <div className="sheet">
      <p className="kicker">Chart data</p>

      {!hasBasic && (
        <Locked title="Chart data tables" tier="Basic"
                note="Planetary positions and dashas unlock on Basic; the full Jaimini karakas, Siddha Nadi points, KP cusps, transits and numerology unlock on Pro." />
      )}

      {hasPlanets && hasBasic && (
        <div className="data-block">
          <p className="data-h">Planetary positions</p>
          <table className="data-tbl">
            <thead><tr><th>Body</th><th>Sign</th><th>Nakshatra</th><th>Status</th></tr></thead>
            <tbody>
              {asc.sign && (
                <tr><td>Ascendant</td><td>{asc.sign}</td><td>{asc.nakshatra || ""}</td><td>—</td></tr>
              )}
              {GRAHA_ORDER.filter((g) => planets[g]).map((g) => {
                const p = planets[g];
                return (
                  <tr key={g}>
                    <td>{g}</td><td>{p.sign}</td>
                    <td>{p.nakshatra || ""}{p.pada ? ` (${p.pada})` : ""}</td>
                    <td>{fmtStatus(p.status)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {hasDasha && hasBasic && (
        <div className="data-block">
          <p className="data-h">Dasha periods</p>
          <table className="data-tbl">
            <thead><tr><th>System</th><th>Running</th><th>Window</th></tr></thead>
            <tbody>
              {vim.balance && (
                <tr><td>Birth balance</td><td>{vim.balance}</td><td>at birth</td></tr>
              )}
              {vim.mahadasha && (
                <tr><td>Vimshottari Maha</td><td>{vim.mahadasha}</td><td>{date(vim.md_start)} – {date(vim.md_end)}</td></tr>
              )}
              {vim.antardasha && (
                <tr><td>Vimshottari Antar</td><td>{vim.mahadasha} / {vim.antardasha}</td><td>{date(vim.ad_start)} – {date(vim.ad_end)}</td></tr>
              )}
              {vim.next_antardasha && (
                <tr><td>Next Antar</td><td>{vim.mahadasha} / {vim.next_antardasha}</td><td>{date(vim.next_ad_start)} – {date(vim.next_ad_end)}</td></tr>
              )}
              {yog.yogini && (
                <tr><td>Yogini</td><td>{yog.yogini}{yog.lord ? ` (${yog.lord})` : ""}</td><td>{date(yog.start)} – {date(yog.end)}</td></tr>
              )}
              {jc.sign && (
                <tr><td>Jaimini Chara</td><td>{jc.sign}</td><td>{date(jc.start)} – {date(jc.end)}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {hasBasic && !hasFull && (
        <Locked title="Full chart data" tier="Pro"
                note="Jaimini karakas, Siddha Nadi points, the current transit snapshot, KP cusp highlights and Chaldean numerology unlock on Pro." />
      )}

      {hasFull && hasKarakas && (
        <div className="data-block">
          <p className="data-h">Jaimini karakas</p>
          <table className="data-tbl">
            <thead><tr><th>Karaka</th><th>Planet</th><th>Sign</th></tr></thead>
            <tbody>
              {Object.keys(karakas).map((k) => (
                <tr key={k}><td>{k}</td><td>{karakas[k].planet}</td><td>{karakas[k].sign}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasFull && hasNadi && (
        <div className="data-block">
          <p className="data-h">Siddha Nadi points</p>
          <table className="data-tbl">
            <tbody>
              {ya.yogi_lord && <tr><td>Yogi lord</td><td>{ya.yogi_lord}{ya.yogi_nakshatra ? ` · ${ya.yogi_nakshatra}` : ""}</td></tr>}
              {ya.avayogi_lord && <tr><td>Avayogi lord</td><td>{ya.avayogi_lord}{ya.avayogi_nakshatra ? ` · ${ya.avayogi_nakshatra}` : ""}</td></tr>}
              {bb.sign && <tr><td>Bhrigu Bindu</td><td>{bb.sign}{bb.nakshatra ? ` · ${bb.nakshatra}` : ""}</td></tr>}
              {ak && <tr><td>Atmakaraka</td><td>{ak.planet}{ak.sign ? ` in ${ak.sign}` : ""}</td></tr>}
              {amk && <tr><td>Amatyakaraka</td><td>{amk.planet}{amk.sign ? ` in ${amk.sign}` : ""}</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {hasFull && hasTransit && (
        <div className="data-block">
          <p className="data-h">Current transit snapshot</p>
          <table className="data-tbl">
            <tbody>
              <tr><td>Sade Sati</td><td>{ss.active ? (ss.phase || "Active") : "Not active"}</td></tr>
              {dt.saturn_sign && <tr><td>Saturn transit</td><td>{dt.saturn_sign}</td></tr>}
              {dt.jupiter_sign && <tr><td>Jupiter transit</td><td>{dt.jupiter_sign}</td></tr>}
              {Array.isArray(dt.houses) && dt.houses.length > 0 && (
                <tr><td>Double transit focus</td><td>{dt.houses.map((h) => `${h}th house`).join(", ")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {hasFull && hasKp && (
        <div className="data-block">
          <p className="data-h">KP cusp highlights</p>
          <table className="data-tbl">
            <thead><tr><th>House</th><th>Sign</th><th>Star</th><th>Sub</th><th>SSL</th></tr></thead>
            <tbody>
              {KP_HIGHLIGHT.filter((h) => cusps[h]).map((h) => {
                const c = cusps[h];
                return <tr key={h}><td>{h}</td><td>{c.sign || ""}</td><td>{c.star || ""}</td><td>{c.sub || ""}</td><td>{c.ssl || ""}</td></tr>;
              })}
            </tbody>
          </table>
        </div>
      )}

      {hasFull && hasNum && (
        <div className="data-block">
          <p className="data-h">Chaldean numerology</p>
          <table className="data-tbl">
            <tbody>
              {num.psychic != null && <tr><td>Psychic number</td><td>{num.psychic}</td></tr>}
              {num.destiny != null && <tr><td>Destiny number</td><td>{num.destiny}</td></tr>}
              {num.name_compound != null && <tr><td>Name compound</td><td>{num.name_compound}{num.name_reduced ? ` → ${num.name_reduced}` : ""}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
