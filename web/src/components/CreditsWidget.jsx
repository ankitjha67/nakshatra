import React from "react";

// Small mono credits indicator (DESIGN.md). Shows available tokens; grant/topup
// breakdown on hover. Balance is lifted in App (from /v1/credits + chat responses).
export default function CreditsWidget({ balance }) {
  const available = balance?.available;
  const title = balance
    ? `AI tokens for readings & chat — grant ${(balance.grant ?? 0).toLocaleString()} · top-up ${(balance.topup ?? 0).toLocaleString()}`
    : "";
  return (
    <span className="credits" title={title}>
      credits: {available == null ? "—" : available.toLocaleString()}
    </span>
  );
}
