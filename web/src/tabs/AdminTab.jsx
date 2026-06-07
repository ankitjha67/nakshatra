import React, { useEffect, useState } from "react";
import { apiGet, apiPost } from "../lib/api.js";

// Admin dashboard — platform health + analytics + flagged users with ban controls.
// Authorized by the admin's Firebase `admin` custom claim (or X-Admin-Key in dev).
export default function AdminTab() {
  const [stats, setStats] = useState(null);
  const [flagged, setFlagged] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    setErr("");
    apiGet("/admin/stats").then(setStats).catch((e) => setErr(e.message));
    apiGet("/admin/anomalies").then((d) => setFlagged(d.flagged || [])).catch(() => {});
  };
  useEffect(load, []);

  const act = async (fn) => { setBusy(true); try { await fn(); load(); } catch (e) { setErr(e.message); } finally { setBusy(false); } };
  const ban = (uid) => act(() => apiPost(`/admin/users/${uid}/ban`, { kind: "temporary", reason: "flagged by admin", days: 7 }));
  const unban = (uid) => act(() => apiPost(`/admin/users/${uid}/unban`, {}));

  if (err) {
    return (
      <div className="card">
        <p className="kicker">Admin</p>
        <h2 style={{ marginTop: 0 }}>Admin access required</h2>
        <p className="note">{err} — sign in with an account that has the <b>admin</b> claim.</p>
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
                <td className="mono">{f.last_ip || "—"}</td>
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
