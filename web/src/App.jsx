import React, { useEffect, useState } from "react";
import { auth } from "./lib/firebase.js";
import { onAuthStateChanged, signOut } from "firebase/auth";
import SignIn from "./components/SignIn.jsx";
import CreditsWidget from "./components/CreditsWidget.jsx";
import ReadingTab from "./tabs/ReadingTab.jsx";
import Stub from "./tabs/Stub.jsx";

const RANK = { free: 0, basic: 1, pro: 2, enterprise: 3 };

// TODO(Phase 1/4): read the signed-in user's real tier from the user doc / a /v1/me endpoint.
// The deploy currently sets DEFAULT_USER_TIER=pro, so we assume pro for the shell.
const USER_TIER = "pro";

const TABS = [
  { key: "natal", label: "Natal", min: "basic",
    render: () => <ReadingTab reportType="natal" blurb="A focused natal reading — essence, mind, relationships, work, and timing." /> },
  { key: "maha", label: "Maha-Kundali", min: "pro",
    render: () => <ReadingTab reportType="maha_kundali" blurb="The complete report — all sections, grounded and cited. (report_type varies output from Phase 2.)" /> },
  { key: "yearly", label: "Yearly", min: "pro",
    render: () => <Stub title="Yearly · Varshphal" phase="Phase 3" summary="Year-scoped forecast from your dashas and the live double-transit. Built next." /> },
  { key: "prashna", label: "Prashna", min: "pro",
    render: () => <Stub title="Prashna · KP Horary" phase="Phase 6" summary="Ask a question now; answered by KP cuspal sub-lords with premise-neutrality." /> },
  { key: "chat", label: "Chat", min: "basic",
    render: () => <Stub title="Chat" phase="Phase 5" summary="Ask follow-ups about your cast chart — grounded in your findings, metered by token credits." /> },
  { key: "btr", label: "Birth-Time Fix", min: "enterprise",
    render: () => <Stub title="Birth-Time Rectification" phase="Phase 7" summary="Narrow an uncertain birth time from life events. Enterprise mode." /> },
];

export default function App() {
  const [user, setUser] = useState(undefined);
  const [tab, setTab] = useState("natal");
  useEffect(() => onAuthStateChanged(auth, setUser), []);

  if (user === undefined) return <div className="wrap"><p className="loader" style={{ paddingTop: 40 }}>Loading…</p></div>;

  const locked = (min) => RANK[USER_TIER] < RANK[min];
  const active = TABS.find((t) => t.key === tab) || TABS[0];

  return (
    <div className="wrap">
      <header className="site">
        <div className="brand">Nakshatra</div>
        {user && (
          <div className="who">
            <CreditsWidget />
            <span style={{ marginLeft: 10 }}>{user.email || user.displayName || "signed in"}</span>
            <button className="ghost" style={{ padding: "6px 12px", fontSize: 12 }} onClick={() => signOut(auth)}>Sign out</button>
          </div>
        )}
      </header>

      {!user ? (
        <SignIn />
      ) : (
        <>
          <nav className="tabs">
            {TABS.map((t) => (
              <button key={t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
                {t.label}{locked(t.min) ? <span className="lock">🔒</span> : null}
              </button>
            ))}
          </nav>

          {locked(active.min) ? (
            <div className="card">
              <p className="kicker">{active.label}</p>
              <h2 style={{ marginTop: 0 }}>Unlocks on a higher plan</h2>
              <p className="note">This feature is available on the {active.min} tier and above. Upgrade to access it.</p>
            </div>
          ) : (
            active.render()
          )}
        </>
      )}

      <footer className="site">Nakshatra · readings are for reflection, not fixed prediction.</footer>
    </div>
  );
}
