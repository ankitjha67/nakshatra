import React, { useState } from "react";

// Code-rendered birth-chart diagrams (no images): North Indian (diamond), South
// Indian (grid) and Western (wheel). Whole-sign, from the engine chart JSON
// (ascendant + planet signs). One large chart at a time via a style toggle; each
// house shows its HOUSE number (brass) + the rashi/SIGN number (muted) + the grahas,
// with the Ascendant clearly marked. Supports D1 + divisional vargas.
const SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
  "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"];
const ABBR = { Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju", Venus: "Ve", Saturn: "Sa", Rahu: "Ra", Ketu: "Ke" };
const VARGA_LABEL = { D1: "D1 Rashi", D9: "D9 Navamsa", D10: "D10 Dasamsa", D24: "D24 Chaturvimsamsa" };
const sidx = (s) => SIGNS.indexOf(s);
const houseOfSign = (signIdx, ascIdx) => (((signIdx - ascIdx) % 12) + 12) % 12 + 1;

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

// Planet labels wrapped into short centered rows so they never spill out of a cell.
function PlanetText({ cx, cy, list, perRow = 3, fs = 11, lh = 12 }) {
  if (!list || !list.length) return null;
  const rows = [];
  for (let i = 0; i < list.length; i += perRow) rows.push(list.slice(i, i + perRow).join(" "));
  const y0 = cy - ((rows.length - 1) * lh) / 2 + fs * 0.34;
  return rows.map((r, i) => (
    <text key={i} x={cx} y={y0 + i * lh} className="pl" style={{ fontSize: fs }}>{r}</text>
  ));
}

// label set for one house cell: house number (brass), sign number (muted), planets
function Cell({ hx, hy, sx, sy, px, py, house, signIdx, planets, asc, perRow = 3, fs = 11 }) {
  return (
    <g>
      <text x={hx} y={hy} className={`hnum${asc ? " asc" : ""}`}>{asc ? `${house}·Asc` : house}</text>
      <text x={sx} y={sy} className="snum">{signIdx + 1}</text>
      <PlanetText cx={px} cy={py} list={planets} perRow={perRow} fs={fs} />
    </g>
  );
}

// ---- South Indian: fixed 4x4 grid, signs in fixed cells (Aries..Pisces) ----
const SOUTH = [[0, 1], [0, 2], [0, 3], [1, 3], [2, 3], [3, 3], [3, 2], [3, 1], [3, 0], [2, 0], [1, 0], [0, 0]];
function South({ ascIdx, bySign, S }) {
  const cs = S / 4;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="South Indian chart">
      {[0, 1, 2, 3, 4].map((i) => <line key={"h" + i} x1={0} y1={i * cs} x2={S} y2={i * cs} className="cl" />)}
      {[0, 1, 2, 3, 4].map((i) => <line key={"v" + i} x1={i * cs} y1={0} x2={i * cs} y2={S} className="cl" />)}
      {SOUTH.map(([r, c], si) => {
        const x = c * cs, y = r * cs, asc = si === ascIdx, house = houseOfSign(si, ascIdx);
        return (
          <g key={si}>
            {asc && <line x1={x + 3} y1={y + 3} x2={x + cs * 0.40} y2={y + cs * 0.40} className="ascd" />}
            <Cell hx={x + cs - 6} hy={y + 15} sx={x + 7} sy={y + 15} px={x + cs / 2} py={y + cs / 2 + 10}
                  house={house} signIdx={si} planets={bySign[si]} asc={asc} perRow={3} fs={12} />
          </g>
        );
      })}
    </svg>
  );
}

// ---- North Indian: fixed diamond; houses fixed (1 = top-centre), signs rotate ----
const NORTH = [[50, 28], [25, 16], [16, 25], [28, 50], [16, 75], [25, 84], [50, 72], [75, 84], [84, 75], [72, 50], [84, 25], [75, 16]];
function North({ ascIdx, bySign, S }) {
  const k = S / 100;
  const L = (a, b, c, d) => <line x1={a * k} y1={b * k} x2={c * k} y2={d * k} className="cl" />;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="North Indian chart">
      <rect x="0.6" y="0.6" width={S - 1.2} height={S - 1.2} className="cl" fill="none" />
      {L(0, 0, 100, 100)}{L(100, 0, 0, 100)}
      {L(50, 0, 100, 50)}{L(100, 50, 50, 100)}{L(50, 100, 0, 50)}{L(0, 50, 50, 0)}
      {NORTH.map(([x, y], h0) => {
        const house = h0 + 1, signIdx = (ascIdx + h0) % 12, asc = house === 1;
        const hx = x + (50 - x) * 0.34, hy = y + (50 - y) * 0.34;   // house number toward centre
        return (
          <Cell key={h0} hx={hx * k} hy={hy * k} sx={x * k} sy={(y - 8) * k}
                px={x * k} py={(y + 5) * k} house={house} signIdx={signIdx}
                planets={bySign[signIdx]} asc={asc} perRow={3} fs={10} />
        );
      })}
    </svg>
  );
}

// ---- Western: circular wheel, houses counterclockwise from the ascendant (left) ----
function Western({ ascIdx, bySign, S }) {
  const cx = S / 2, cy = S / 2, R = S * 0.46, ri = S * 0.26;
  const rSign = R * 0.93, rPl = (R + ri) / 2, rHouse = ri * 0.80;
  const pt = (ang, r) => [cx + r * Math.cos(ang * Math.PI / 180), cy - r * Math.sin(ang * Math.PI / 180)];
  const spokes = [], cells = [];
  for (let h = 1; h <= 12; h++) {
    const a0 = 180 + (h - 1) * 30, mid = a0 + 15, signIdx = (ascIdx + h - 1) % 12, asc = h === 1;
    const [sx, sy] = pt(a0, ri), [ex, ey] = pt(a0, R);
    spokes.push(<line key={"s" + h} x1={sx} y1={sy} x2={ex} y2={ey} className="cl" />);
    const [sgx, sgy] = pt(mid, rSign), [px, py] = pt(mid, rPl), [hx, hy] = pt(mid, rHouse);
    cells.push(
      <Cell key={"c" + h} hx={hx} hy={hy + 3} sx={sgx} sy={sgy + 3} px={px} py={py}
            house={h} signIdx={signIdx} planets={bySign[signIdx]} asc={asc} perRow={2} fs={10} />
    );
  }
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="Western chart">
      <circle cx={cx} cy={cy} r={R} className="cl" fill="none" />
      <circle cx={cx} cy={cy} r={ri} className="cl" fill="none" />
      {spokes}{cells}
    </svg>
  );
}

const STYLES = [["north", "North Indian"], ["south", "South Indian"], ["western", "Western"]];

export default function Charts({ chart, features = [] }) {
  if (!chart) return null;
  const canDivisional = features.length === 0 || features.includes("divisional");
  const vargas = canDivisional ? availableVargas(chart) : ["D1"];
  const [varga, setVarga] = useState("D1");
  const [style, setStyle] = useState("north");
  const active = vargas.includes(varga) ? varga : "D1";
  const { ascIdx, bySign } = placements(chart, active);
  const S = 360;
  const View = style === "south" ? South : style === "western" ? Western : North;
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
      <div className="chart-style-tabs">
        {STYLES.map(([k, label]) => (
          <button key={k} className={`varga-tab${style === k ? " on" : ""}`} onClick={() => setStyle(k)}>{label}</button>
        ))}
      </div>
      <div className="chart-single">
        <View ascIdx={ascIdx} bySign={bySign} S={S} />
      </div>
      <p className="note">
        {VARGA_LABEL[active] || active} · whole-sign houses from a {SIGNS[ascIdx]} {active === "D1" ? "ascendant" : "varga lagna"}.
        In each house, the <b style={{ color: "var(--brass)" }}>brass number is the house</b> (1 = Ascendant) and the
        muted number is the sign (1 = Aries … 12 = Pisces). Su Mo Ma Me Ju Ve Sa Ra Ke = the grahas.
      </p>
      {!canDivisional && features.length > 0 && (
        <p className="note">Divisional charts (D9 Navamsa / D10 Dasamsa / D24) unlock on Pro.</p>
      )}
    </div>
  );
}
