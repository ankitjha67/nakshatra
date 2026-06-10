import React, { useState } from "react";

// Code-rendered birth charts: North Indian (diamond), South Indian (grid), Western
// (wheel). Whole-sign, from the engine chart JSON. One large chart with a style
// toggle and a Symbols/Letters toggle. Each house auto-fits its contents (house
// number + sign + grahas), shrinking and wrapping so conjunctions never spill over.
const SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
  "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"];
const ABBR = { Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju", Venus: "Ve", Saturn: "Sa", Rahu: "Ra", Ketu: "Ke" };
// ︎ = text/monochrome variation selector, stops the OS rendering these as
// colored emoji (zodiac signs especially default to emoji on many platforms).
const TXT = "︎";
const PLANET_GLYPH = { Su: "☉" + TXT, Mo: "☾" + TXT, Ma: "♂" + TXT, Me: "☿" + TXT, Ju: "♃" + TXT, Ve: "♀" + TXT, Sa: "♄" + TXT, Ra: "☊" + TXT, Ke: "☋" + TXT };
const SIGN_GLYPH = ["♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓"].map((g) => g + TXT);
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
    if (i >= 0 && ABBR[name]) bySign[i].push(ABBR[name]);   // store abbr; mapped to glyph at render
  });
  return { ascIdx, bySign };
}

function availableVargas(chart) {
  const v = (chart && (chart.vargas || (chart.chart && chart.chart.vargas))) || {};
  return ["D1", ...["D9", "D10", "D24"].filter((k) => v[k])];
}

// Adaptive sizing so any number of conjunct planets fits the cell.
function planetLayout(n) {
  if (n <= 1) return { fs: 13, lh: 14, perRow: 1 };
  if (n <= 2) return { fs: 12, lh: 13, perRow: 2 };
  if (n <= 4) return { fs: 10, lh: 11, perRow: 2 };
  if (n <= 6) return { fs: 8.6, lh: 9.6, perRow: 3 };
  return { fs: 7.6, lh: 8.6, perRow: 3 };
}
const show = (abbr, glyphs) => (glyphs ? (PLANET_GLYPH[abbr] || abbr) : abbr);
const signLabel = (i, glyphs) => (glyphs ? SIGN_GLYPH[i] : i + 1);

// A vertically-centered stack: header line (house# + sign) then wrapped planet rows.
function Stack({ cx, cy, house, signIdx, planets, asc, glyphs }) {
  const list = (planets || []).map((a) => show(a, glyphs));
  const { fs, lh, perRow } = planetLayout(list.length);
  const rows = [];
  for (let i = 0; i < list.length; i += perRow) rows.push(list.slice(i, i + perRow).join(" "));
  const hfs = 8.5;
  const lines = 1 + rows.length;
  const total = (lines - 1) * lh + hfs;
  let y = cy - total / 2 + hfs * 0.85;
  return (
    <g>
      <text x={cx} y={y} className="hsl" textAnchor="middle" style={{ fontSize: hfs }}>
        <tspan className={asc ? "hnum asc" : "hnum"}>{house}</tspan>
        <tspan className="snum">{" " + signLabel(signIdx, glyphs)}</tspan>
      </text>
      {rows.map((r, i) => (
        <text key={i} x={cx} y={y + (i + 1) * lh} className="pl" style={{ fontSize: fs }} textAnchor="middle">{r}</text>
      ))}
    </g>
  );
}

// ---- North Indian: fixed diamond; houses fixed (1 = top-centre), signs rotate ----
const NORTH = [[50, 25], [25, 13], [13, 25], [25, 50], [13, 75], [25, 87], [50, 75], [75, 87], [87, 75], [75, 50], [87, 25], [75, 13]];
function North({ ascIdx, bySign, S, glyphs }) {
  const k = S / 100;
  const L = (a, b, c, d) => <line x1={a * k} y1={b * k} x2={c * k} y2={d * k} className="cl" />;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="North Indian chart">
      <rect x="0.7" y="0.7" width={S - 1.4} height={S - 1.4} className="cl" fill="none" />
      {L(0, 0, 100, 100)}{L(100, 0, 0, 100)}
      {L(50, 0, 100, 50)}{L(100, 50, 50, 100)}{L(50, 100, 0, 50)}{L(0, 50, 50, 0)}
      {NORTH.map(([x, y], h0) => {
        const house = h0 + 1, signIdx = (ascIdx + h0) % 12;
        return <Stack key={h0} cx={x * k} cy={y * k} house={house} signIdx={signIdx}
                      planets={bySign[signIdx]} asc={house === 1} glyphs={glyphs} />;
      })}
    </svg>
  );
}

// ---- South Indian: fixed 4x4 grid, signs in fixed cells (Aries..Pisces) ----
const SOUTH = [[0, 1], [0, 2], [0, 3], [1, 3], [2, 3], [3, 3], [3, 2], [3, 1], [3, 0], [2, 0], [1, 0], [0, 0]];
function South({ ascIdx, bySign, S, glyphs }) {
  const cs = S / 4;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="South Indian chart">
      {[0, 1, 2, 3, 4].map((i) => <line key={"h" + i} x1={0} y1={i * cs} x2={S} y2={i * cs} className="cl" />)}
      {[0, 1, 2, 3, 4].map((i) => <line key={"v" + i} x1={i * cs} y1={0} x2={i * cs} y2={S} className="cl" />)}
      {SOUTH.map(([r, c], si) => {
        const x = c * cs, y = r * cs, asc = si === ascIdx;
        return (
          <g key={si}>
            {asc && <line x1={x + 3} y1={y + 3} x2={x + cs * 0.36} y2={y + cs * 0.36} className="ascd" />}
            <Stack cx={x + cs / 2} cy={y + cs / 2} house={houseOfSign(si, ascIdx)} signIdx={si}
                   planets={bySign[si]} asc={asc} glyphs={glyphs} />
          </g>
        );
      })}
    </svg>
  );
}

// ---- Western: circular wheel, houses counterclockwise from the ascendant (left) ----
function Western({ ascIdx, bySign, S, glyphs }) {
  const cx = S / 2, cy = S / 2, R = S * 0.47, ri = S * 0.30, rMid = (R + ri) / 2;
  const pt = (ang, r) => [cx + r * Math.cos(ang * Math.PI / 180), cy - r * Math.sin(ang * Math.PI / 180)];
  const spokes = [], cells = [];
  for (let h = 1; h <= 12; h++) {
    const a0 = 180 + (h - 1) * 30, mid = a0 + 15, signIdx = (ascIdx + h - 1) % 12, asc = h === 1;
    const [sx, sy] = pt(a0, ri), [ex, ey] = pt(a0, R);
    spokes.push(<line key={"s" + h} x1={sx} y1={sy} x2={ex} y2={ey} className="cl" />);
    const [mx, my] = pt(mid, rMid);
    cells.push(<Stack key={"c" + h} cx={mx} cy={my} house={h} signIdx={signIdx}
                      planets={bySign[signIdx]} asc={asc} glyphs={glyphs} />);
  }
  // Ascendant (Rising) marker at 9 o'clock — the 1st-house cusp, highlighted
  const [aix, aiy] = pt(180, ri), [aox, aoy] = pt(180, R);
  return (
    <svg viewBox={`0 0 ${S} ${S}`} className="chart-svg" role="img" aria-label="Western chart">
      <circle cx={cx} cy={cy} r={R} className="cl" fill="none" />
      <circle cx={cx} cy={cy} r={ri} className="cl" fill="none" />
      {spokes}{cells}
      <line x1={aix} y1={aiy} x2={aox - 6} y2={aoy} className="ascd" />
      <text x={aox - 4} y={aoy - 5} className="ascl" style={{ textAnchor: "start" }}>ASC ▸</text>
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
  const [glyphs, setGlyphs] = useState(true);
  const active = vargas.includes(varga) ? varga : "D1";
  const { ascIdx, bySign } = placements(chart, active);
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
        <button className="varga-tab" style={{ marginLeft: "auto" }} onClick={() => setGlyphs((g) => !g)}>
          {glyphs ? "Letters" : "Symbols"}
        </button>
      </div>
      <div className="chart-single">
        <View ascIdx={ascIdx} bySign={bySign} S={360} glyphs={glyphs} />
      </div>
      {style === "western" ? (
        <p className="note">
          Whole-sign houses with a {SIGNS[ascIdx]} Rising (Ascendant). The Ascendant is at the left
          (marked <b style={{ color: "var(--marigold)" }}>ASC</b>); houses run counter-clockwise. In each
          house: the <b style={{ color: "var(--brass)" }}>brass number is the house</b> (1 = Rising),
          then the sign{glyphs ? " glyph" : " number (1 = Aries … 12 = Pisces)"}, then the planets
          ({glyphs ? "☉☾♂☿♃♀♄☊☋" : "Su Mo Ma Me Ju Ve Sa Ra Ke"}). Note: this uses the sidereal
          (Vedic) zodiac, so signs differ from Western tropical software.
        </p>
      ) : (
        <p className="note">
          {VARGA_LABEL[active] || active} · whole-sign houses from a {SIGNS[ascIdx]} {active === "D1" ? "ascendant" : "varga lagna"}.
          In each house: the <b style={{ color: "var(--brass)" }}>brass number is the house</b> (1 = Ascendant, in orange),
          then the sign{glyphs ? " glyph" : " number (1 = Aries … 12 = Pisces)"} (rashi), then the grahas
          ({glyphs ? "☉☾♂☿♃♀♄☊☋" : "Su Mo Ma Me Ju Ve Sa Ra Ke"}).
        </p>
      )}
      {!canDivisional && features.length > 0 && (
        <p className="note">Divisional charts (D9 Navamsa / D10 Dasamsa / D24) unlock on Pro.</p>
      )}
    </div>
  );
}
