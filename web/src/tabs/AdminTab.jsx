import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../lib/api.js";

// Admin dashboard, platform health + analytics + flagged users with ban controls.
// Authorized by the admin's Firebase `admin` custom claim (or X-Admin-Key in dev).
const TIERS = ["free", "basic", "pro", "enterprise"];

export default function AdminTab() {
  const [stats, setStats] = useState(null);
  const [flagged, setFlagged] = useState([]);
  const [beta, setBeta] = useState({ count: 0, users: [] });
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [tierUid, setTierUid] = useState("");
  const [tierVal, setTierVal] = useState("enterprise");
  const [betaUid, setBetaUid] = useState("");

  const load = () => {
    setErr("");
    apiGet("/admin/stats").then(setStats).catch((e) => setErr(e.message));
    apiGet("/admin/anomalies").then((d) => setFlagged(d.flagged || [])).catch(() => {});
    apiGet("/admin/beta").then(setBeta).catch(() => {});
  };
  useEffect(load, []);

  const act = async (fn, ok) => {
    setBusy(true); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); load(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const ban = (uid) => act(() => apiPost(`/admin/users/${uid}/ban`, { kind: "temporary", reason: "flagged by admin", days: 7 }));
  const unban = (uid) => act(() => apiPost(`/admin/users/${uid}/unban`, {}));
  const setTier = () => { if (!tierUid.trim()) return;
    act(() => apiPost("/admin/users/tier", { uid: tierUid.trim(), tier: tierVal, source: "admin" }),
        (r) => `Set ${r.uid} → ${r.tier}.`); };
  const grantBeta = () => { if (!betaUid.trim()) return;
    act(() => apiPost("/admin/beta/grant", { uid: betaUid.trim() }),
        (r) => `Granted beta (${r.tier}) to ${r.uid}.`); setBetaUid(""); };
  const revokeBeta = () => {
    if (!window.confirm(`Revoke ALL ${beta.count} beta users back to free? Paying users are not affected.`)) return;
    act(() => apiPost("/admin/beta/revoke", {}), (r) => `Revoked ${r.revoked} beta user(s).`);
  };

  if (err) {
    return (
      <div className="card">
        <p className="kicker">Admin</p>
        <h2 style={{ marginTop: 0 }}>Admin access required</h2>
        <p className="note">{err} - sign in with an account that has the <b>admin</b> claim.</p>
      </div>
    );
  }
  if (!stats) return <p className="loader" style={{ paddingTop: 20 }}>Loading admin…</p>;

  const cost = stats.platform_cost || {};
  const inr = (n) => "₹" + Number(n || 0).toLocaleString();
  const cards = [
    ["Users", (stats.users_total || 0).toLocaleString()],
    ["Banned", stats.banned || 0],
    ["Flagged", stats.flagged || 0],
    ["Tokens today", (stats.tokens_today || 0).toLocaleString()],
    ["Revenue", inr(stats.revenue_inr)],
    ["Refunded", inr(stats.refunded_inr)],
    ["Net", inr(stats.net_inr)],
    ["Run cost / mo", inr(cost.total_inr)],
  ];

  return (
    <div>
      <p className="kicker">Admin · platform health</p>
      <div className="stat-grid">
        {cards.map(([k, v]) => (
          <div className="stat" key={k}><div className="stat-v">{v}</div><div className="stat-k">{k}</div></div>
        ))}
      </div>

      {msg && <p className="note" style={{ color: "var(--brass)", marginTop: 18 }}>{msg}</p>}

      <p className="kicker" style={{ marginTop: 26 }}>Subscriptions & beta cohort</p>
      <div className="admin-panels">
        <div className="admin-panel">
          <p className="data-h">Set a user's tier</p>
          <div className="admin-row">
            <input className="mono" placeholder="Firebase uid" value={tierUid} onChange={(e) => setTierUid(e.target.value)} />
            <select value={tierVal} onChange={(e) => setTierVal(e.target.value)}>
              {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <button className="sm" disabled={busy || !tierUid.trim()} onClick={setTier}>Set tier</button>
          </div>
          <p className="note">Manual grant (tagged “admin”). Use for support/comps; not the beta program.</p>
        </div>

        <div className="admin-panel">
          <p className="data-h">Beta access ({beta.count})</p>
          <div className="admin-row">
            <input className="mono" placeholder="Firebase uid" value={betaUid} onChange={(e) => setBetaUid(e.target.value)} />
            <button className="sm" disabled={busy || !betaUid.trim()} onClick={grantBeta}>Grant enterprise (beta)</button>
            <button className="ghost sm" disabled={busy || !beta.count} onClick={revokeBeta}>Revoke all beta</button>
          </div>
          {beta.users && beta.users.length > 0 ? (
            <table className="admin-tbl">
              <thead><tr><th>User</th><th>Email</th><th>Tier</th></tr></thead>
              <tbody>
                {beta.users.map((u) => (
                  <tr key={u.uid}><td className="mono">{u.uid}</td><td>{u.email || "-"}</td><td>{u.tier}</td></tr>
                ))}
              </tbody>
            </table>
          ) : <p className="note">No beta users yet. Grant access by Firebase uid; revoke all in one click before going live.</p>}
        </div>
      </div>

      <p className="kicker" style={{ marginTop: 26 }}>Flagged users ({flagged.length})</p>
      {flagged.length === 0 ? (
        <p className="note">No anomalies detected.</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>User</th><th>Last IP</th><th>Reasons</th><th>State</th><th></th></tr></thead>
          <tbody>
            {flagged.map((f) => (
              <tr key={f.uid}>
                <td className="mono">{f.uid}</td>
                <td className="mono">{f.last_ip || "-"}</td>
                <td>{(f.reasons || []).join("; ")}</td>
                <td>{f.banned ? "banned" : "active"}</td>
                <td>
                  {f.banned
                    ? <button className="ghost sm" disabled={busy} onClick={() => unban(f.uid)}>Unban</button>
                    : <button className="sm" disabled={busy} onClick={() => ban(f.uid)}>Ban 7d</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
