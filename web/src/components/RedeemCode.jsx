import React, { useState } from "react";
import { apiPost } from "../lib/api.js";

// "Have an access code?" redeem box. Beta codes unlock a tier; discount codes
// attach a % off for checkout. On success it triggers a refresh of entitlements.
export default function RedeemCode({ onRedeemed }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const submit = async () => {
    const c = code.trim();
    if (!c || busy) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await apiPost("/v1/redeem", { code: c });
      setMsg(r.message || (r.kind === "discount" ? `${r.discount_pct}% discount applied.` : "Unlocked."));
      setCode("");
      if (r.kind !== "discount" && onRedeemed) setTimeout(onRedeemed, 600);
    } catch (e) { setErr(e.message || "Could not redeem that code."); }
    finally { setBusy(false); }
  };

  return (
    <div className="redeem">
      <p className="redeem-label">Have an access code?</p>
      <div className="redeem-row">
        <input value={code} onChange={(e) => setCode(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
               placeholder="e.g. NK-ABCD-EFGH-JKLM" autoComplete="off" spellCheck={false} />
        <button className="sm" onClick={submit} disabled={busy || !code.trim()}>{busy ? "…" : "Redeem"}</button>
      </div>
      {msg && <p className="note" style={{ color: "var(--brass)", marginTop: 8 }}>{msg}</p>}
      {err && <p className="err" style={{ marginTop: 8 }}>{err}</p>}
    </div>
  );
}
