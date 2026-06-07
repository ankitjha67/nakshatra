import React from "react";

// STUB until Phase 4–5 (credit ledger). Will read users/{uid} balance or the /v1/chat response.
export default function CreditsWidget({ balance }) {
  const available = balance?.available;
  return <span className="credits">credits: {available == null ? "—" : available.toLocaleString()}</span>;
}
