import React, { useEffect, useState } from "react";
import { auth, firebaseReady, PREVIEW } from "./lib/firebase.js";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { getTiers, apiGet } from "./lib/api.js";
import SignIn from "./components/SignIn.jsx";
import CreditsWidget from "./components/CreditsWidget.jsx";
import ReadingTab from "./tabs/ReadingTab.jsx";
import ChatTab from "./tabs/ChatTab.jsx";
import PrashnaTab from "./tabs/PrashnaTab.jsx";
import BtrTab from "./tabs/BtrTab.jsx";

const RANK = { free: 0, basic: 1, pro: 2, enterprise: 3 };

// TODO(Phase 1/4): read the signed-in user's real tier from the user doc / a /v1/me endpoint.
// The deploy currently sets DEFAULT_USER_TIER=pro, so we assume pro for the shell.
const USER_TIER = "pro";

// render(ctx) receives shared app state: { onCast, lastBirth, setBalance }.
const TABS = [
  { key: "natal", label: "Natal", min: "basic",
    render: (ctx) => <ReadingTab reportType="natal" onCast={ctx.onCast} blurb="A focused natal reading — essence, mind, relationships, work, and timing." /> },
  { key: "maha", label: "Maha-Kundali", min: "pro",
    render: (ctx) => <ReadingTab reportType="maha_kundali" onCast={ctx.onCast} blurb="The complete report — all sections, grounded and cited." /> },
  { key: "yearly", label: "Yearly", min: "pro",
    render: (ctx) => <ReadingTab reportType="yearly" onCast={ctx.onCast} blurb="A year-scoped forecast (Varshphal) — your dashas across the chosen year, with its timing and sensitive points." /> },
  { key: "prashna", label: "Prashna", min: "pro",
    render: () => <PrashnaTab /> },
  { key: "chat", label: "Chat", min: "basic",
    render: (ctx) => <ChatTab lastBirth={ctx.lastBirth} onBalance={ctx.setBalance} /> },
  { key: "btr", label: "Birth-Time Fix", min: "enterprise",
    render: () => <BtrTab /> },
];

export default function App() {
  const [user, setUser] = useState(undefined);
  const [tab, setTab] = useState("natal");
  const [tiers, setTiers] = useState([]);
  const [lastBirth, setLastBirth] = useState(null);   // last cast chart → grounds Chat
  const [balance, setBalance] = useState(null);       // chat credit balance (CreditsWidget)

  useEffect(() => {
    if (PREVIEW) { setUser({ email: "preview@local" }); return; }
    if (!firebaseReady) { setUser(null); return; }
    return onAuthStateChanged(auth, setUser);
  }, []);

  // Tier catalog (pricing + per-tier sections) drives the paywall cards.
  useEffect(() => { getTiers().then((r) => setTiers(r?.tiers || [])).catch(() => {}); }, []);

  // Load the credit balance once signed in (chat turns then keep it live).
  useEffect(() => { if (user) apiGet("/v1/credits").then(setBalance).catch(() => {}); }, [user]);

  if (user === undefined) return <div className="wrap"><p className="loader" style={{ paddingTop: 40 }}>Loading…</p></div>;

  const ctx = { onCast: setLastBirth, lastBirth, setBalance };

  const locked = (min) => RANK[USER_TIER] < RANK[min];
  const active = TABS.find((t) => t.key === tab) || TABS[0];

  return (
    <div className="wrap">
      <header className="site">
        <div className="brand">Nakshatra</div>
        {user && (
          <div className="who">
            <CreditsWidget balance={balance} />
            <span style={{ marginLeft: 10 }}>{user.email || user.displayName || "signed in"}</span>
            {firebaseReady && (
              <button className="ghost" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => signOut(auth)}>Sign out</button>
            )}
          </div>
        )}
      </header>

      {PREVIEW && (
        <p className="devbar">
          Dev preview — no Firebase configured. Readings call the local API (<b>{USER_TIER}</b> tier). Add <b>web/.env</b> for real sign-in.
        </p>
      )}

      {!firebaseReady && !PREVIEW ? (
        <div className="card">
          <p className="kicker">Configuration needed</p>
          <h2 style={{ marginTop: 0 }}>Firebase web config missing</h2>
          <p className="note">Set VITE_FB_API_KEY / VITE_FB_AUTH_DOMAIN / VITE_FB_PROJECT_ID in <b>web/.env</b> to enable sign-in.</p>
        </div>
      ) : !user ? (
        <SignIn />
      ) : (
        <>
          <nav className="tabs">
            {TABS.map((t) => (
              <button key={t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
                {t.label}{locked(t.min) ? <span className="lock"><LockIcon /></span> : null}
              </button>
            ))}
          </nav>

          {locked(active.min) ? <Paywall tab={active} tiers={tiers} /> : active.render(ctx)}
        </>
      )}

      <footer className="site">Nakshatra · readings are for reflection, not fixed prediction.</footer>
    </div>
  );
}

// Hand-drawn hairline lock (per DESIGN.md) — replaces the 🔒 emoji on locked tabs. Inherits --muted.
function LockIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="5" y="11" width="14" height="9" rx="1.5" />
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

// Paywall card for a locked tab — pricing and included sections come from /v1/tiers.
function Paywall({ tab, tiers }) {
  const t = tiers.find((x) => x.key === tab.min);
  const name = t ? t.label : tab.min;
  return (
    <div className="card">
      <p className="kicker">{tab.label}</p>
      <h2 style={{ marginTop: 0 }}>Unlocks on {name}</h2>
      <p className="note">
        This feature is available on the {name} tier{t && t.price_inr_month ? ` (₹${t.price_inr_month}/mo)` : ""} and above. Upgrade to access it.
      </p>
      {t && t.sections && t.sections.length > 0 && (
        <p className="note">{name} includes: {t.sections.join(" · ")}</p>
      )}
    </div>
  );
}
