import React from "react";

// Placeholder for tabs Claude Code builds in later phases (see docs/BUILD_PLAN.md).
export default function Stub({ title, phase, summary }) {
  return (
    <div className="card">
      <p className="kicker">{title}</p>
      <h2 style={{ marginTop: 0 }}>Coming in {phase}</h2>
      <p className="note">{summary}</p>
    </div>
  );
}
