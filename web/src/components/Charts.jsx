import React, { useState } from "react";

// Original, code-rendered birth-chart diagrams (no images): North Indian (diamond),
// South Indian (grid), and Western (wheel). All whole-sign, computed from the
// engine chart JSON (ascendant + planet signs). Supports the D1 Rashi chart and
// the divisional vargas (D9 Navamsa, D10 Dasamsa, ...) when the engine supplies them.
const SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
  "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"];
const ABBR = { Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju", Venus: "Ve", Saturn: "Sa", Rahu: "Ra", Ketu: "Ke" };
const VARGA_LABEL = { D1: "D1 Rashi", D9: "D9 Navamsa", D10: "D10 Dasamsa", D24: "D24 Chaturvimsamsa" };
const sidx = (s) => SIGNS.indexOf(s);

// Source signs for a varga: D1 reads chart.asc + chart.planets; Dxx reads
// chart.vargas[Dxx] = {Lagna:{sign}, NAME:{sign}}.
function placements(chart, varga = "D1") {
  const cb = (chart && chart.chart) || chart || {};
  let ascSign, planets;
  if (varga === "D1") {
    ascSign = (cb.asc && cb.asc.sign) || cb.ascendant || "Aries";
    planets = cb.planets || {};
  } else {
    const v = ((chart && chart.vargas) || cb.vargas || {})[varga] || {};
    ascSign = (v.Lagna && v.Lagna.sign) || "Aries";
    planets = v;
  }
  const ascIdx = Math.max(0, sidx(ascSign));
  const bySign = Array.from({ length: 12 }, () => []);
  Object.keys(planets).forEach((name) => {
    if (name === "Lagna") return;
    const s = planets[name] && planets[name].sign;
    const i = sidx(s);
    if (i >= 0 && ABBR[name]) bySign[i].push(ABBR[name]);
  });
  return { ascIdx, bySign };
}

function availableVargas(chart) {
  const v = (chart && (chart.vargas || (chart.chart && chart.chart.vargas))) || {};
  return ["D1", ...["D9", "D10", "D24"].filter((k) => v[k])];
}
const houseOfSign = (signIdx, ascIdx) => (((signIdx - ascIdx) % 12) + 12) % 12 + 1;

// Planet labels wrapped into short centered rows so they never spill out of a
// house/cell, no matter how many grahas share it. Centered on (cx, cy).
function PlanetText({ cx, cy, list, perRow = 2, fs = 10, lh = 11 }) {
  if (!list || !list.length) return null;
  const rows = [];
  for (let i = 0; i < list.length; i += perRow) rows.push(list.slice(i, i + perRow).join(" "));
  const y0 = cy - ((rows.length - 1) * lh) / 2 + fs * 0.34;
  return rows.map((r, i) => (
    <text key={i} x={cx} y={y0 + i * lh} className="pl" style={{ fontSize: fs }}>{r}</text>
  ));
}

// ---- South Indian: fixed 4x4 grid, signs in fixed cells (Aries..Pisces) ----
const SOUTH = [[0, 1], [0, 2], [0, 3], [1, 3], [2, 3], [3, 3], [3, 2], [3, 1], [3, 0], [2, 0], [1, 0], [0, 0]];
function South({ ascIdx, bySign, S = 240 }) {
  const cs = S / 4;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="South Indian chart">
      {[0, 1, 2, 3, 4].map((i) => <line key={"h" + i} x1={0} y1={i * cs} x2={S} y2={i * cs} className="cl" />)}
      {[0, 1, 2, 3, 4].map((i) => <line key={"v" + i} x1={i * cs} y1={0} x2={i * cs} y2={S} className="cl" />)}
      <text x={S / 2} y={S / 2} className="cmid">South</text>
      {SOUTH.map(([r, c], si) => {
        const x = c * cs, y = r * cs, asc = si === ascIdx;
        return (
          <g key={si}>
            {asc && <line x1={x} y1={y} x2={x + cs * 0.5} y2={y + cs * 0.5} className="ascd" />}
            <text x={x + 5} y={y + 13} className="snum">{si + 1}</text>
            <PlanetText cx={x + cs / 2} cy={y + cs / 2 + 6} list={bySign[si]} perRow={2} fs={11} lh={12} />
          </g>
        );
      })}
    </svg>
  );
}

// ---- North Indian: fixed diamond; houses fixed, signs rotate with ascendant ----
const NORTH = [[50, 30], [25, 18], [18, 25], [30, 50], [18, 75], [25, 82], [50, 70], [75, 82], [82, 75], [70, 50], [82, 25], [75, 18]];
function North({ ascIdx, bySign, S = 240 }) {
  const k = S / 100;
  const L = (a, b, c, d, cls) => <line x1={a * k} y1={b * k} x2={c * k} y2={d * k} className={cls} />;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="North Indian chart">
      <rect x="0" y="0" width={S} height={S} className="cl" fill="none" />
      {L(0, 0, 100, 100, "cl")}{L(100, 0, 0, 100, "cl")}
      {L(50, 0, 100, 50, "cl")}{L(100, 50, 50, 100, "cl")}{L(50, 100, 0, 50, "cl")}{L(0, 50, 50, 0, "cl")}
      {NORTH.map(([x, y], h0) => {
        const house = h0 + 1, signIdx = (ascIdx + h0) % 12;
        return (
          <g key={h0}>
            <text x={x * k} y={(y - 8) * k} className="snum">{signIdx + 1}</text>
            <PlanetText cx={x * k} cy={(y + 4) * k} list={bySign[signIdx]} perRow={2} fs={9} lh={10} />
            {house === 1 && <text x={x * k} y={(y + 16) * k} className="ascl">Asc</text>}
          </g>
        );
      })}
    </svg>
  );
}

// ---- Western: circular wheel, houses counterclockwise from the ascendant (left) ----
function Western({ ascIdx, bySign, S = 240 }) {
  const cx = S / 2, cy = S / 2, R = S * 0.46, ri = S * 0.30, rp = (R + ri) / 2, rs = R * 0.9;
  const pt = (ang, r) => [cx + r * Math.cos(ang * Math.PI / 180), cy - r * Math.sin(ang * Math.PI / 180)];
  const spokes = [], cells = [];
  for (let h = 1; h <= 12; h++) {
    const a0 = 180 + (h - 1) * 30;
    const [sx, sy] = pt(a0, ri), [ex, ey] = pt(a0, R);
    spokes.push(<line key={"s" + h} x1={sx} y1={sy} x2={ex} y2={ey} className="cl" />);
    const mid = a0 + 15, signIdx = (ascIdx + h - 1) % 12;
    const [px, py] = pt(mid, rp), [snx, sny] = pt(mid, rs);
    cells.push(
      <g key={"c" + h}>
        <text x={snx} y={sny + 3} className="snum">{signIdx + 1}</text>
        <PlanetText cx={px} cy={py} list={bySign[signIdx]} perRow={2} fs={9} lh={10} />
      </g>
    );
  }
  const [ax, ay] = pt(180, R);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="Western chart">
      <circle cx={cx} cy={cy} r={R} className="cl" fill="none" />
      <circle cx={cx} cy={cy} r={ri} className="cl" fill="none" />
      {spokes}{cells}
      <text x={ax - 4} y={ay - 6} className="ascl">Asc</text>
    </svg>
  );
}

export default function Charts({ chart, features = [] }) {
  if (!chart) return null;
  // Divisional charts (D9/D10/D24) are a Pro feature; without it, only D1 shows.
  const canDivisional = features.length === 0 || features.includes("divisional");
  const vargas = canDivisional ? availableVargas(chart) : ["D1"];
  const [varga, setVarga] = useState("D1");
  const active = vargas.includes(varga) ? varga : "D1";
  const { ascIdx, bySign } = placements(chart, active);
  return (
    <div className="sheet">
      <div className="sec-head">
        <p className="kicker" style={{ marginBottom: 0 }}>Birth charts</p>
        {vargas.length > 1 && (
          <div className="varga-tabs">
            {vargas.map((v) => (
              <button key={v} className={`varga-tab${v === active ? " on" : ""}`} onClick={() => setVarga(v)}>
                {VARGA_LABEL[v] || v}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="charts" style={{ marginTop: 16 }}>
        <figure><North ascIdx={ascIdx} bySign={bySign} /><figcaption>North Indian</figcaption></figure>
        <figure><South ascIdx={ascIdx} bySign={bySign} /><figcaption>South Indian</figcaption></figure>
        <figure><Western ascIdx={ascIdx} bySign={bySign} /><figcaption>Western</figcaption></figure>
      </div>
      <p className="note">
        {VARGA_LABEL[active] || active} · whole-sign houses from a {SIGNS[ascIdx]} {active === "D1" ? "ascendant" : "varga lagna"}.
        Su Mo Ma Me Ju Ve Sa Ra Ke = the grahas; the number is the sign (1 = Aries … 12 = Pisces).
      </p>
      {!canDivisional && features.length > 0 && (
        <p className="note">Divisional charts (D9 Navamsa / D10 Dasamsa / D24) unlock on Pro.</p>
      )}
    </div>
  );
}
