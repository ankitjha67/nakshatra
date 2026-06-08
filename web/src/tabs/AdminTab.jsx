import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../lib/api.js";

// Admin dashboard, platform health + analytics + flagged users with ban controls.
// Authorized by the admin's Firebase `admin` custom claim (or X-Admin-Key in dev).
const TIERS = ["free", "basic", "pro", "enterprise"];
// How a tier was assigned (NOT a role). "admin" = set manually by an admin.
const SRC = { payment: "paid", beta: "beta", admin: "manual", revoked: "revoked" };
const srcLabel = (s) => (s ? ` · ${SRC[s] || s}` : "");

// Tiny inline bar chart for a daily series.
function MiniBars({ data, k }) {
  const max = Math.max(1, ...data.map((d) => d[k] || 0));
  return (
    <div className="spark">
      {data.map((d, i) => (
        <span key={i} className="spark-bar" title={`${d.date}: ${(d[k] || 0).toLocaleString()}`}
              style={{ height: `${Math.max(2, Math.round(100 * (d[k] || 0) / max))}%` }} />
      ))}
    </div>
  );
}

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
  const [codes, setCodes] = useState([]);
  const [changeReqs, setChangeReqs] = useState([]);
  const [refunds, setRefunds] = useState([]);
  const [audit, setAudit] = useState([]);
  const [users, setUsers] = useState([]);
  const [detail, setDetail] = useState(null);
  const [ov, setOv] = useState(null);          // /admin/overview analytics
  const [analytics, setAnalytics] = useState(null);
  const [range, setRange] = useState(30);
  const [q, setQ] = useState("");              // users search
  const [tierFilter, setTierFilter] = useState("all");
  const [sortKey, setSortKey] = useState("last_seen");
  const [generated, setGenerated] = useState([]);     // plaintext, shown once
  const [cKind, setCKind] = useState("beta");
  const [cCount, setCCount] = useState(20);
  const [cTier, setCTier] = useState("enterprise");
  const [cDiscount, setCDiscount] = useState(20);
  const [cUses, setCUses] = useState(1);
  const [cExpiry, setCExpiry] = useState(30);
  const [feedback, setFeedback] = useState([]);
  const [fraudData, setFraudData] = useState(null);

  const load = () => {
    setErr("");
    apiGet("/admin/stats").then(setStats).catch((e) => setErr(e.message));
    apiGet("/admin/anomalies").then((d) => setFlagged(d.flagged || [])).catch(() => {});
    apiGet("/admin/beta").then(setBeta).catch(() => {});
    apiGet("/admin/codes").then((d) => setCodes(d.codes || [])).catch(() => {});
    apiGet("/admin/birth-change-requests").then((d) => setChangeReqs(d.requests || [])).catch(() => {});
    apiGet("/admin/refunds").then((d) => setRefunds(d.requests || [])).catch(() => {});
    apiGet("/admin/audit?limit=50").then((d) => setAudit(d.entries || [])).catch(() => {});
    apiGet("/admin/users").then((d) => setUsers(d.users || [])).catch(() => {});
    apiGet("/admin/overview").then(setOv).catch(() => {});
    apiGet("/admin/feedback").then((d) => setFeedback(d.feedback || [])).catch(() => {});
    apiGet("/admin/fraud").then(setFraudData).catch(() => {});
  };
  useEffect(load, []);
  useEffect(() => { apiGet(`/admin/analytics?days=${range}`).then(setAnalytics).catch(() => {}); }, [range]);

  const exportUsersCsv = () => {
    const cols = ["uid", "email", "tier", "tier_source", "banned", "last_seen", "tokens_today", "has_subscription", "discount_pct", "birth_locked"];
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const lines = [cols.join(","), ...users.map((u) => cols.map((c) => esc(u[c])).join(","))];
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `nakshatra-users-${new Date().toISOString().slice(0, 10)}.csv`; a.click();
  };

  const openUser = (uid) => { setDetail(null); apiGet(`/admin/users/${uid}`).then(setDetail).catch((e) => setErr(e.message)); };
  const refreshDetail = (uid) => apiGet(`/admin/users/${uid}`).then(setDetail).catch(() => {});

  const act = async (fn, ok) => {
    setBusy(true); setMsg("");
    try { const r = await fn(); if (ok) setMsg(ok(r)); load(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const userAction = async (uid, path, body, okMsg, after) => {
    setBusy(true); setMsg(""); setErr("");
    try { await apiPost(path, body || {}); setMsg(okMsg); if (after) after(); else await refreshDetail(uid); load(); }
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
  const approveRefund = (rid) => act(() => apiPost(`/admin/refunds/${rid}/approve`, {}), () => "Refund approved.");
  const rejectRefund = (rid) => act(() => apiPost(`/admin/refunds/${rid}/reject`, {}), () => "Refund rejected.");
  const approveChange = (rid) => act(() => apiPost(`/admin/birth-change-requests/${rid}/approve`, {}), () => "Approved, the user can re-enter their details.");
  const rejectChange = (rid) => act(() => apiPost(`/admin/birth-change-requests/${rid}/reject`, {}), () => "Request rejected.");
  const deactivateCode = (id) => act(() => apiPost(`/admin/codes/${id}/deactivate`, {}), () => "Code deactivated.");
  const reactivateCode = (id) => act(() => apiPost(`/admin/codes/${id}/reactivate`, {}), () => "Code reactivated.");
  const genCodes = () => act(async () => {
    const body = { kind: cKind, count: Number(cCount), max_uses: Number(cUses) };
    if (cExpiry) body.expires_days = Number(cExpiry);
    if (cKind === "beta") body.tier = cTier; else body.discount_pct = Number(cDiscount);
    const r = await apiPost("/admin/codes/generate", body);
    setGenerated(r.codes || []);
    return r;
  }, (r) => `Generated ${r.count} ${r.kind} code(s) — copy them now.`);

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

  const inr = (n) => "₹" + Number(n || 0).toLocaleString();
  const o = ov || {}; const ou = o.users || {}; const orev = o.revenue || {};
  const ocd = o.codes || {}; const orq = o.requests || {};
  const cost = o.platform_cost || stats.platform_cost || {};
  const cards = [
    ["Users", (ou.total ?? stats.users_total ?? 0).toLocaleString()],
    ["Paid", `${ou.paid ?? 0}${ou.conversion_pct != null ? ` · ${ou.conversion_pct}%` : ""}`],
    ["Active 7d", ou.active_7d ?? "—"],
    ["Active 30d", ou.active_30d ?? "—"],
    ["MRR", inr(orev.mrr_inr)],
    ["Net revenue", inr(orev.net_inr ?? stats.net_inr)],
    ["Tokens today", ((o.tokens || {}).today ?? stats.tokens_today ?? 0).toLocaleString()],
    ["Run cost / mo", inr(cost.total_inr)],
    ["Codes redeemed", `${ocd.redemptions ?? 0} / ${ocd.total ?? 0}`],
    ["Pending refunds", orq.refunds_pending ?? 0],
    ["Pending changes", orq.birth_changes_pending ?? 0],
    ["Jailbreak flags", ou.jailbreakers ?? 0],
    ["Banned", stats.banned ?? 0],
  ];
  const byTier = ou.by_tier || {};
  const series = (o.tokens || {}).series || [];
  const maxTok = Math.max(1, ...series.map((s) => s.tokens));
  const ql = q.trim().toLowerCase();
  const shownUsers = users
    .filter((u) => tierFilter === "all" || u.tier === tierFilter)
    .filter((u) => !ql || (u.email || "").toLowerCase().includes(ql) || (u.uid || "").toLowerCase().includes(ql))
    .slice()
    .sort((a, b) => {
      if (sortKey === "tokens_today") return (b.tokens_today || 0) - (a.tokens_today || 0);
      if (sortKey === "tier") return (a.tier || "").localeCompare(b.tier || "");
      if (sortKey === "email") return (a.email || a.uid || "").localeCompare(b.email || b.uid || "");
      return String(b.last_seen || "").localeCompare(String(a.last_seen || ""));
    });

  return (
    <div className="sheet">
      <p className="kicker">Admin · platform health</p>
      <div className="stat-grid">
        {cards.map(([k, v]) => (
          <div className="stat" key={k}><div className="stat-v">{v}</div><div className="stat-k">{k}</div></div>
        ))}
      </div>

      {ov && (
        <div className="admin-panels" style={{ marginTop: 16 }}>
          <div className="admin-panel">
            <p className="data-h">Tier distribution</p>
            {["free", "basic", "pro", "enterprise"].map((t) => {
              const n = byTier[t] || 0; const pct = Math.round(100 * n / Math.max(ou.total || 1, 1));
              return (
                <div key={t} className="bar-row">
                  <span className="bar-label">{t}</span>
                  <span className="bar-track"><span className="bar-fill" style={{ width: `${pct}%` }} /></span>
                  <span className="bar-val">{n}</span>
                </div>
              );
            })}
            <p className="note">{ou.with_subscription || 0} active subscriptions · {ou.birth_locked || 0} charts locked</p>
          </div>
          <div className="admin-panel">
            <p className="data-h">Tokens / day (14d)</p>
            <div className="spark">
              {series.map((s) => (
                <span key={s.date} className="spark-bar" title={`${s.date}: ${s.tokens.toLocaleString()}`}
                      style={{ height: `${Math.max(2, Math.round(100 * s.tokens / maxTok))}%` }} />
              ))}
            </div>
            <p className="note">peak {maxTok.toLocaleString()} · today {((o.tokens || {}).today || 0).toLocaleString()}</p>
          </div>
        </div>
      )}

      {analytics && (
        <div style={{ marginTop: 16 }}>
          <div className="sec-head">
            <p className="data-h" style={{ marginTop: 0 }}>Trends & funnel</p>
            <select value={range} onChange={(e) => setRange(+e.target.value)}>
              <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
            </select>
          </div>
          <div className="admin-panels">
            <div className="admin-panel">
              <p className="data-h">Signups / day</p>
              <MiniBars data={analytics.signups_by_day} k="count" />
              <p className="note">{analytics.signups_by_day.reduce((s, d) => s + d.count, 0)} new in {range}d</p>
            </div>
            <div className="admin-panel">
              <p className="data-h">Revenue / day</p>
              <MiniBars data={analytics.revenue_by_day} k="inr" />
              <p className="note">₹{analytics.revenue_by_day.reduce((s, d) => s + d.inr, 0).toLocaleString()} in {range}d</p>
            </div>
          </div>
          <div className="admin-panels" style={{ marginTop: 16 }}>
            <div className="admin-panel">
              <p className="data-h">Conversion funnel</p>
              {analytics.funnel.map((st, i) => {
                const top = analytics.funnel[0].count || 1;
                return (
                  <div key={i} className="bar-row">
                    <span className="bar-label" style={{ flexBasis: 110 }}>{st.stage}</span>
                    <span className="bar-track"><span className="bar-fill" style={{ width: `${Math.round(100 * st.count / top)}%` }} /></span>
                    <span className="bar-val">{st.count}</span>
                  </div>
                );
              })}
            </div>
            <div className="admin-panel">
              <p className="data-h">Top token consumers</p>
              {analytics.top_consumers.length ? (
                <table className="data-tbl"><tbody>
                  {analytics.top_consumers.map((u, i) => (
                    <tr key={i}><td>{u.email || <span className="mono">{u.uid}</span>}</td><td>{u.tier}</td><td>{u.tokens_total.toLocaleString()}</td></tr>
                  ))}
                </tbody></table>
              ) : <p className="note">No token usage yet.</p>}
            </div>
          </div>
        </div>
      )}

      {msg && <p className="note" style={{ color: "var(--brass)", marginTop: 18 }}>{msg}</p>}

      <p className="kicker" style={{ marginTop: 26 }}>Users ({users.length}) · click a row for details</p>
      <div className="admin-row" style={{ marginBottom: 10 }}>
        <input placeholder="Search email or uid" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: "1 1 200px" }} />
        <select value={tierFilter} onChange={(e) => setTierFilter(e.target.value)}>
          <option value="all">all tiers</option>{TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
          <option value="last_seen">recent</option>
          <option value="tokens_today">tokens today</option>
          <option value="tier">tier</option>
          <option value="email">email</option>
        </select>
        <button className="ghost sm" onClick={exportUsersCsv} disabled={!users.length}>Export CSV</button>
      </div>
      {shownUsers.length === 0 ? (
        <p className="note">{users.length ? "No users match the filter." : "No users yet."}</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>User</th><th>Tier</th><th>Last seen</th><th>Tokens today</th><th>Status</th></tr></thead>
          <tbody>
            {shownUsers.map((u) => (
              <tr key={u.uid} className="rowlink" onClick={() => openUser(u.uid)}>
                <td>{u.email || <span className="mono">{u.uid}</span>}</td>
                <td>{u.tier}<span className="mono" style={{ color: "var(--muted)" }}>{srcLabel(u.tier_source)}</span></td>
                <td className="mono">{u.last_seen ? new Date(u.last_seen).toLocaleString() : "—"}</td>
                <td>{(u.tokens_today || 0).toLocaleString()}</td>
                <td>{u.banned ? "banned" : u.birth_locked ? "active · locked" : "active"}
                  {u.jailbreak_count > 0 && <span style={{ color: "var(--danger, #c0392b)", fontWeight: 600 }}> · ⚑{u.jailbreak_count}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {detail && (
        <div className="user-detail">
          <div className="sec-head">
            <p className="data-h" style={{ marginTop: 0 }}>{detail.email || detail.uid}</p>
            <button className="ghost sm" onClick={() => setDetail(null)}>Close</button>
          </div>
          <table className="data-tbl"><tbody>
            <tr><td>UID</td><td className="mono">{detail.uid}</td></tr>
            <tr><td>Tier</td><td>{detail.tier}{srcLabel(detail.tier_source)}</td></tr>
            <tr><td>AI credits</td><td>{(detail.balance?.available ?? 0).toLocaleString()} available</td></tr>
            <tr><td>Tokens today</td><td>{(detail.tokens_today || 0).toLocaleString()}</td></tr>
            <tr><td>Discount</td><td>{detail.discount_pct ? `${detail.discount_pct}%` : "—"}</td></tr>
            <tr><td>Subscription</td><td>{detail.has_subscription ? (detail.subscription_id || "active") : "—"}</td></tr>
            <tr><td>Last activity</td><td className="mono">{detail.activity?.last_seen ? new Date(detail.activity.last_seen).toLocaleString() : "—"} · {detail.activity?.last_ip || "no ip"}</td></tr>
            <tr><td>Birth lock</td><td>{detail.birth_lock ? `${detail.birth_lock.name || "—"} · ${detail.birth_lock.date} · ${detail.birth_lock.place || ""}` : "none"}</td></tr>
            <tr><td>Banned</td><td>{detail.ban ? `${detail.ban.kind} · ${detail.ban.reason || ""}` : "no"}</td></tr>
            <tr><td>Fraud risk</td><td>{detail.risk
              ? <span style={{ fontWeight: 700, color: detail.risk.band === "high" ? "var(--danger,#c0392b)" : detail.risk.band === "watch" ? "var(--brass)" : "inherit" }}>{detail.risk.band.toUpperCase()} · {detail.risk.score}{(detail.risk.signals || []).length ? ` · ${detail.risk.signals.map((s) => s.signal).join(", ")}` : ""}</span>
              : "—"}</td></tr>
            <tr><td>Jailbreak attempts</td><td>{detail.jailbreak_count
              ? <b style={{ color: "var(--danger, #c0392b)" }}>⚑ {detail.jailbreak_count}{detail.jailbreak_last ? ` · last ${new Date(detail.jailbreak_last).toLocaleString()}` : ""}</b>
              : "none"}</td></tr>
            <tr><td>Payments</td><td>{(detail.payments || []).length} · Refund requests {(detail.refunds || []).length}</td></tr>
          </tbody></table>
          <div className="actions">
            {detail.ban
              ? <button className="ghost sm" disabled={busy} onClick={() => userAction(detail.uid, `/admin/users/${detail.uid}/unban`, {}, "Unbanned.")}>Unban</button>
              : <button className="ghost sm" disabled={busy} onClick={() => userAction(detail.uid, `/admin/users/${detail.uid}/ban`, { kind: "temporary", reason: "admin", days: 7 }, "Banned 7d.")}>Ban 7d</button>}
            {detail.birth_lock && <button className="ghost sm" disabled={busy} onClick={() => userAction(detail.uid, `/admin/users/${detail.uid}/reset-birth`, {}, "Birth lock cleared.")}>Reset birth lock</button>}
            <button className="ghost sm" disabled={busy} onClick={() => { if (window.confirm(`Delete user ${detail.email || detail.uid}? This removes their profile, keys and chats.`)) userAction(detail.uid, `/admin/users/${detail.uid}/delete`, {}, "User deleted.", () => { setDetail(null); load(); }); }}>Delete user</button>
          </div>
          {(detail.jailbreaks || []).length > 0 && (
            <>
              <p className="data-h" style={{ marginTop: 16 }}>Jailbreak / injection attempts</p>
              <table className="data-tbl"><tbody>
                {detail.jailbreaks.map((j, i) => (
                  <tr key={i}>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}>{j.ts ? new Date(j.ts).toLocaleString() : ""}<br /><span style={{ color: "var(--muted)" }}>{j.kind}</span></td>
                    <td style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{j.text}</td>
                  </tr>
                ))}
              </tbody></table>
            </>
          )}
          {(detail.audit || []).length > 0 && (
            <>
              <p className="data-h" style={{ marginTop: 16 }}>Recent admin actions on this user</p>
              <table className="data-tbl"><tbody>
                {detail.audit.map((a, i) => (
                  <tr key={i}><td className="mono">{a.ts ? new Date(a.ts).toLocaleString() : ""}</td><td>{a.action}</td></tr>
                ))}
              </tbody></table>
            </>
          )}
        </div>
      )}

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
          <p className="note">Manual grant (tagged “manual”), this assigns a tier, it does NOT make the user an admin. Use for support/comps; beta uses the panel beside this.</p>
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

      <p className="kicker" style={{ marginTop: 26 }}>Refund requests ({refunds.length})</p>
      {refunds.length === 0 ? (
        <p className="note">No pending refund requests.</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>User</th><th>Payment</th><th>Reason</th><th></th></tr></thead>
          <tbody>
            {refunds.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.uid}</td>
                <td className="mono">{r.payment_id}</td>
                <td>{r.reason || "—"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="sm" disabled={busy} onClick={() => approveRefund(r.id)}>Approve</button>{" "}
                  <button className="ghost sm" disabled={busy} onClick={() => rejectRefund(r.id)}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="kicker" style={{ marginTop: 26 }}>Birth-detail change requests ({changeReqs.length})</p>
      {changeReqs.length === 0 ? (
        <p className="note">No pending requests.</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>User</th><th>Current</th><th>Reason</th><th></th></tr></thead>
          <tbody>
            {changeReqs.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.uid}</td>
                <td>{r.current ? `${r.current.name || "—"} · ${r.current.date} · ${r.current.place || ""}` : "—"}</td>
                <td>{r.reason}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="sm" disabled={busy} onClick={() => approveChange(r.id)}>Approve</button>{" "}
                  <button className="ghost sm" disabled={busy} onClick={() => rejectChange(r.id)}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="kicker" style={{ marginTop: 26 }}>Access codes</p>
      <div className="admin-panel">
        <p className="data-h">Generate codes (beta = unlock a tier, discount = % off)</p>
        <div className="admin-row">
          <select value={cKind} onChange={(e) => setCKind(e.target.value)}>
            <option value="beta">beta</option><option value="discount">discount</option>
          </select>
          {cKind === "beta" ? (
            <select value={cTier} onChange={(e) => setCTier(e.target.value)}>
              {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          ) : (
            <input type="number" min="1" max="100" value={cDiscount} onChange={(e) => setCDiscount(e.target.value)} title="discount %" style={{ maxWidth: 90 }} />
          )}
          <input type="number" min="1" max="200" value={cCount} onChange={(e) => setCCount(e.target.value)} title="how many" style={{ maxWidth: 90 }} />
          <input type="number" min="1" max="100000" value={cUses} onChange={(e) => setCUses(e.target.value)} title="uses per code" style={{ maxWidth: 90 }} />
          <input type="number" min="1" max="3650" value={cExpiry} onChange={(e) => setCExpiry(e.target.value)} title="expires in days" style={{ maxWidth: 110 }} />
          <button className="sm" disabled={busy} onClick={genCodes}>Generate</button>
        </div>
        <p className="note">count · uses/code · expiry(days). Codes are shown once below; only salted hashes are stored.</p>
        {generated.length > 0 && (
          <>
            <p className="note" style={{ color: "var(--brass)" }}>Copy & share now — these won't be shown again:</p>
            <textarea readOnly rows={Math.min(10, generated.length)} className="mono"
                      style={{ width: "100%" }} value={generated.join("\n")} onFocus={(e) => e.target.select()} />
          </>
        )}
        {codes.length > 0 && (
          <table className="admin-tbl" style={{ marginTop: 12 }}>
            <thead><tr><th>Code id</th><th>Kind</th><th>Grants</th><th>Uses</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {codes.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.id.slice(0, 10)}…</td>
                  <td>{c.kind}</td>
                  <td>{c.kind === "discount" ? `${c.discount_pct}% off` : c.tier}</td>
                  <td>{c.uses}/{c.max_uses}</td>
                  <td>{!c.active ? "inactive" : c.uses >= c.max_uses ? "spent" : "active"}</td>
                  <td>{c.active
                    ? <button className="ghost sm" disabled={busy} onClick={() => deactivateCode(c.id)}>Deactivate</button>
                    : <button className="ghost sm" disabled={busy} onClick={() => reactivateCode(c.id)}>Reactivate</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <p className="kicker" style={{ marginTop: 26 }}>Fraud monitoring · risk{fraudData ? ` (${fraudData.high} high · ${fraudData.watch} watch)` : ""}</p>
      {!fraudData || (fraudData.flagged || []).length === 0 ? (
        <p className="note">No elevated-risk users. Continuous scan scores every user on signals (malicious intent, injection attempts, refund abuse, token velocity, shared IPs).</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>User</th><th>Risk</th><th>Score</th><th>Signals</th><th></th></tr></thead>
          <tbody>
            {fraudData.flagged.map((f) => (
              <tr key={f.uid} className="rowlink" onClick={() => openUser(f.uid)}>
                <td>{f.email || <span className="mono">{f.uid}</span>}</td>
                <td><span style={{ fontWeight: 700, color: f.band === "high" ? "var(--danger,#c0392b)" : "var(--brass)" }}>{f.band.toUpperCase()}</span></td>
                <td>{f.score}</td>
                <td style={{ fontSize: 12 }}>{(f.signals || []).map((s) => `${s.signal} (+${s.points})`).join(", ")}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  {f.banned ? <span className="mono" style={{ color: "var(--muted)" }}>banned</span>
                    : <button className="sm" disabled={busy} onClick={(e) => { e.stopPropagation(); ban(f.uid); }}>Ban 7d</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

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

      <p className="kicker" style={{ marginTop: 26 }}>Feedback ({feedback.length})</p>
      {feedback.length === 0 ? (
        <p className="note">No feedback yet.</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>When</th><th>User</th><th>Type</th><th>Message</th></tr></thead>
          <tbody>
            {feedback.map((f, i) => (
              <tr key={i}>
                <td className="mono">{f.ts ? new Date(f.ts).toLocaleString() : "—"}</td>
                <td>{f.email || <span className="mono">{f.uid}</span>}<span className="mono" style={{ color: "var(--muted)" }}> · {f.tier}</span></td>
                <td>{f.category}{f.rating ? ` · ${f.rating}★` : ""}</td>
                <td style={{ whiteSpace: "pre-wrap" }}>{f.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="kicker" style={{ marginTop: 26 }}>Audit log (recent)</p>
      {audit.length === 0 ? (
        <p className="note">No admin actions recorded yet.</p>
      ) : (
        <table className="admin-tbl">
          <thead><tr><th>When</th><th>Admin</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
          <tbody>
            {audit.map((a, i) => (
              <tr key={i}>
                <td className="mono">{a.ts ? new Date(a.ts).toLocaleString() : "—"}</td>
                <td className="mono">{a.admin || "—"}</td>
                <td>{a.action}</td>
                <td className="mono">{a.target || "—"}</td>
                <td className="mono">{a.details ? Object.entries(a.details).filter(([, v]) => v != null).map(([k, v]) => `${k}=${v}`).join(", ") : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
