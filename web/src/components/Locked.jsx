import React from "react";

// Inline lock/upgrade prompt shown where a feature isn't in the user's tier.
// Keeps the feature visible (so the user knows it exists) behind a clear upgrade
// nudge, instead of silently hiding it.
export default function Locked({ title, tier = "Pro", note }) {
  return (
    <div className="locked">
      <span className="locked-badge" aria-hidden="true">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="5" y="11" width="14" height="9" rx="1.5" />
          <path d="M8 11V8a4 4 0 0 1 8 0v3" />
        </svg>
      </span>
      <div>
        <b>{title}</b>
        <p className="note" style={{ margin: "3px 0 0" }}>{note || `Upgrade to ${tier} to unlock.`}</p>
      </div>
    </div>
  );
}
