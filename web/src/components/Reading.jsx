import React from "react";

// Renders a ReadingResponse: summary, sections, and the cited-finding "Drawn from" footer.
export default function Reading({ data, birth }) {
  if (!data) return null;
  const titleByCode = {};
  (data.findings || []).forEach((f) => { titleByCode[f.code] = f.title; });
  const m = data.meta || {};
  return (
    <div className="sheet">
      <p className="kicker">Your reading</p>
      {birth && <p className="note" style={{ marginTop: 0 }}>{birth.name} · {birth.date} {birth.time} · {Number(birth.lat).toFixed(2)}, {Number(birth.lon).toFixed(2)} · UTC {birth.tz}</p>}
      {data.summary && <p className="summary">{data.summary}</p>}
      {(data.sections || []).map((s) => {
        const cites = (s.citations || []).map((c) => titleByCode[c]).filter(Boolean);
        const hasLS = s.light || s.shadow;
        const vClass = s.verdict === "Supported" ? "v-ok" : s.verdict === "Needs care" ? "v-care" : "v-mixed";
        return (
          <div className="sec" key={s.key}>
            <div className="sec-head">
              <h3>{s.title}</h3>
              {s.verdict && (
                <span className={`verdict ${vClass}`}>
                  {s.verdict}{s.confidence ? ` · ${s.confidence} confidence` : ""}
                </span>
              )}
            </div>
            {hasLS ? (
              <>
                {s.light && <p className="ls light"><span className="ls-tag">Light</span>{s.light}</p>}
                {s.shadow && <p className="ls shadow"><span className="ls-tag">Shadow</span>{s.shadow}</p>}
              </>
            ) : (
              <p>{s.body}</p>
            )}
            {cites.length > 0 && <div className="drawn">Drawn from: {cites.map((t, i) => <b key={i}>{t}{i < cites.length - 1 ? " · " : ""}</b>)}</div>}
          </div>
        );
      })}
      {(data.disclaimers || []).map((d, i) => <p className="note" key={i}>{d}</p>)}
      <p className="note" style={{ fontFamily: "IBM Plex Mono, monospace" }}>Computed by {m.engine_version || "the engine"} · rendered by {m.model || "the writer"}</p>
    </div>
  );
}
