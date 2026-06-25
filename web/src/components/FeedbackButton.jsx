import React, { useState } from "react";
import { apiPost } from "../lib/api.js";
import { track } from "../lib/analytics.js";

const CATS = [
  { key: "idea", label: "Idea" },
  { key: "bug", label: "Bug" },
  { key: "praise", label: "Praise" },
  { key: "other", label: "Other" },
];

// Floating feedback button + panel. Posts to /v1/feedback; stored for later review
// in the Admin dashboard. Lives at the app root so it's available on every tab.
export default function FeedbackButton() {
  const [open, setOpen] = useState(false);
  const [cat, setCat] = useState("idea");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const close = () => { setOpen(false); setSent(false); setErr(""); };
  const send = async () => {
    if (msg.trim().length < 3) { setErr("Please add a little detail."); return; }
    setBusy(true); setErr("");
    try {
      await apiPost("/v1/feedback", { message: msg.trim(), category: cat, page: window.location.hash || "app" });
      track("feedback", { category: cat });
      setSent(true); setMsg("");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <>
      <button className="fab-feedback" onClick={() => { setOpen(true); setSent(false); }} aria-label="Send feedback">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4L3 21l1.1-4A8.4 8.4 0 1 1 21 11.5Z" /></svg>
        Feedback
      </button>
      {open && (
        <div className="fb-overlay" onClick={close}>
          <div className="fb-panel" onClick={(e) => e.stopPropagation()}>
            <button className="fb-x" onClick={close} aria-label="Close">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
            {sent ? (
              <div className="fb-thanks">
                <p className="data-h" style={{ marginTop: 0 }}>Thank you</p>
                <p className="note">Your feedback was recorded. We read every note.</p>
                <div className="actions"><button className="sm" onClick={close}>Done</button></div>
              </div>
            ) : (
              <>
                <p className="data-h" style={{ marginTop: 0 }}>Share feedback</p>
                <p className="note">Tell us what's working, what's broken, or what you'd love to see.</p>
                <div className="fb-cats">
                  {CATS.map((c) => (
                    <button key={c.key} type="button"
                      className={`fb-chip ${cat === c.key ? "on" : ""}`} onClick={() => setCat(c.key)}>{c.label}</button>
                  ))}
                </div>
                <textarea rows={5} value={msg} maxLength={2000}
                  onChange={(e) => setMsg(e.target.value)} placeholder="Your feedback…" style={{ width: "100%" }} />
                {err && <p className="err">{err}</p>}
                <div className="actions">
                  <button className="sm" disabled={busy || msg.trim().length < 3} onClick={send}>{busy ? "Sending…" : "Send feedback"}</button>
                  <button className="ghost sm" onClick={close}>Cancel</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
