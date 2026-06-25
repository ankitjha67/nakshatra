import React, { useState } from "react";
import { apiPost, apiGet, apiDelete } from "../lib/api.js";
import RedeemCode from "../components/RedeemCode.jsx";

const TIER_LABEL = { free: "Free", basic: "Basic", pro: "Pro", enterprise: "Enterprise" };

// Account / billing: current plan, AI-credit balance, any active discount, the
// locked birth details, and self-serve subscription cancel.
export default function AccountTab({ me, refresh }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [reqOpen, setReqOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!me) return <p className="loader" style={{ paddingTop: 20 }}>Loading account…</p>;

  const submitChange = async () => {
    if (reason.trim().length < 5) { setErr("Please give a brief reason (5+ characters)."); return; }
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await apiPost("/v1/birth-change-request", { reason: reason.trim() });
      setMsg(r.message || "Request submitted."); setReqOpen(false); setReason(""); refresh && refresh();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const bal = me.balance || {};
  const lock = me.birth_lock;
  const cancel = async () => {
    if (!window.confirm("Cancel your subscription at the end of the current cycle?")) return;
    setBusy(true); setErr(""); setMsg("");
    try { const r = await apiPost("/v1/subscription/cancel", {}); setMsg(r.message || "Cancellation requested."); refresh && refresh(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="sheet">
      <p className="kicker">Account</p>

      <div className="data-block">
        <p className="data-h">Plan</p>
        <table className="data-tbl"><tbody>
          <tr><td>Current plan</td><td>{TIER_LABEL[me.tier] || me.tier}</td></tr>
          {me.discount_pct > 0 && (
            <tr><td>Discount</td><td><b style={{ color: "var(--brass)" }}>{me.discount_pct}% off</b> applies at checkout</td></tr>
          )}
          <tr><td>AI credits</td><td>{(bal.available ?? 0).toLocaleString()} available
            {bal.topup ? ` (incl. ${bal.topup.toLocaleString()} top-up)` : ""}</td></tr>
        </tbody></table>
        {me.has_subscription ? (
          <div className="actions">
            <button className="ghost sm" disabled={busy} onClick={cancel}>Cancel subscription</button>
          </div>
        ) : (
          <p className="note">No active recurring subscription. {me.tier === "free" ? "Subscribe from any locked tab." : ""}</p>
        )}
        {msg && <p className="note" style={{ color: "var(--brass)" }}>{msg}</p>}
        {err && <p className="err">{err}</p>}
      </div>

      <div className="data-block">
        <p className="data-h">Saved birth details</p>
        {lock && lock.date ? (
          <>
            <table className="data-tbl"><tbody>
              <tr><td>Name</td><td>{lock.name || "—"}</td></tr>
              <tr><td>Born</td><td>{lock.date} · {lock.time} · UTC {lock.tz}</td></tr>
              <tr><td>Place</td><td>{lock.place || `${Number(lock.lat).toFixed(2)}, ${Number(lock.lon).toFixed(2)}`}</td></tr>
            </tbody></table>
            <p className="note">Locked to your account (one chart per account).</p>
            {me.birth_change_pending ? (
              <p className="note" style={{ color: "var(--brass)" }}>A change request is pending admin review.</p>
            ) : !reqOpen ? (
              <div className="actions"><button className="ghost sm" onClick={() => { setReqOpen(true); setMsg(""); }}>Request a change</button></div>
            ) : (
              <div style={{ marginTop: 10 }}>
                <label className="fld">Why do you need to change your birth details?</label>
                <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                          placeholder="e.g. I mistyped my birth date / wrong city selected" style={{ width: "100%" }} />
                <div className="actions">
                  <button className="sm" disabled={busy} onClick={submitChange}>Submit request</button>
                  <button className="ghost sm" disabled={busy} onClick={() => { setReqOpen(false); setReason(""); }}>Cancel</button>
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="note">No birth details saved yet. They lock to your account on your first reading.</p>
        )}
      </div>

      <PrivacyBlock me={me} refresh={refresh} />

      {me.tier !== "enterprise" && (
        <div className="data-block">
          <p className="data-h">Have an access code?</p>
          <RedeemCode onRedeemed={refresh} />
        </div>
      )}
    </div>
  );
}

// Privacy & your data (DPDP/GDPR rights): export, delete, withdraw consent, file a
// grievance, and nominate someone to act for you. Withdrawal must be as easy as consent.
function PrivacyBlock({ me, refresh }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [griev, setGriev] = useState("");
  const [nom, setNom] = useState(me.nominee || { name: "", email: "", relationship: "" });
  const officer = me.grievance_officer || {};

  const run = async (fn, ok) => {
    setBusy(true); setErr(""); setMsg("");
    try { await fn(); setMsg(ok); refresh && refresh(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const exportData = async () => {
    const data = await apiGet("/v1/me/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "nakshatra-my-data.json"; a.click();
    URL.revokeObjectURL(a.href);
  };
  const withdraw = () => {
    if (!window.confirm("Withdraw consent? We'll stop processing your birth data until you consent again.")) return;
    return run(() => apiPost("/v1/consent/withdraw", {}), "Consent withdrawn.");
  };
  const del = () => {
    if (!window.confirm("Delete your account and all your data permanently? This cannot be undone.")) return;
    return run(() => apiDelete("/v1/me"), "Account deletion requested.");
  };
  const fileGrievance = () => {
    if (griev.trim().length < 5) { setErr("Please describe your grievance (5+ characters)."); return; }
    return run(async () => { await apiPost("/v1/grievance", { message: griev.trim() }); setGriev(""); },
              "Grievance filed. We'll respond within the timeframe the law requires.");
  };
  const saveNominee = () => {
    if (!nom.name.trim()) { setErr("Enter your nominee's name."); return; }
    return run(() => apiPost("/v1/nominee", nom), "Nominee saved.");
  };

  return (
    <div className="data-block">
      <p className="data-h">Privacy & your data</p>
      <p className="note">Your rights under the DPDP Act 2023 and (if applicable) the GDPR.</p>
      <div className="actions" style={{ flexWrap: "wrap", gap: 8 }}>
        <button className="ghost sm" disabled={busy} onClick={() => run(exportData, "Your data was downloaded.")}>Export my data</button>
        <button className="ghost sm" disabled={busy} onClick={withdraw}>Withdraw consent</button>
        <button className="ghost sm" disabled={busy} onClick={del} style={{ color: "var(--danger, #d66)" }}>Delete my account</button>
      </div>

      <label className="fld" style={{ marginTop: 14 }}>File a privacy grievance</label>
      <textarea rows={2} value={griev} onChange={(e) => setGriev(e.target.value)}
                placeholder="e.g. please correct/erase X" style={{ width: "100%" }} />
      <div className="actions"><button className="sm" disabled={busy} onClick={fileGrievance}>Submit grievance</button></div>
      {(officer.name || officer.email) && (
        <p className="note">Grievance Officer: {officer.name || ""} {officer.email ? `· ${officer.email}` : ""}</p>
      )}

      <label className="fld" style={{ marginTop: 14 }}>Nominee (who may act for you on death/incapacity)</label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input placeholder="Name" value={nom.name} onChange={(e) => setNom({ ...nom, name: e.target.value })} />
        <input placeholder="Email" value={nom.email || ""} onChange={(e) => setNom({ ...nom, email: e.target.value })} />
        <input placeholder="Relationship" value={nom.relationship || ""} onChange={(e) => setNom({ ...nom, relationship: e.target.value })} />
      </div>
      <div className="actions"><button className="sm" disabled={busy} onClick={saveNominee}>Save nominee</button></div>

      {msg && <p className="note" style={{ color: "var(--brass)" }}>{msg}</p>}
      {err && <p className="err">{err}</p>}
    </div>
  );
}
