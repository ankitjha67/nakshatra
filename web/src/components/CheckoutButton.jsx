import React, { useState } from "react";
import { apiPost } from "../lib/api.js";

// Lazy-load Razorpay's widget only when checkout is actually started.
function loadRazorpay() {
  return new Promise((resolve) => {
    if (window.Razorpay) return resolve(true);
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });
}

// "Subscribe" button. Calls /v1/checkout (which applies any redeemed discount).
// When live keys are configured the API returns a Razorpay order and we open the
// widget; otherwise it returns the priced intent and we show the amount + note.
export default function CheckoutButton({ tier, label, onPaid }) {
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState("");

  const start = async () => {
    setBusy(true); setErr("");
    try {
      const r = await apiPost("/v1/checkout", { tier });
      setInfo(r);
      if (r.enabled && r.provider === "razorpay" && r.order_id) {
        const ok = await loadRazorpay();
        if (!ok) { setErr("Could not load the payment window."); return; }
        const rzp = new window.Razorpay({
          key: r.key_id, order_id: r.order_id, amount: r.amount_inr * 100,
          currency: r.currency || "INR", name: r.name || "Nakshatra",
          description: `${r.tier_label || tier} subscription`,
          handler: () => { if (onPaid) setTimeout(onPaid, 1500); },
        });
        rzp.open();
      }
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="checkout">
      <button onClick={start} disabled={busy}>{busy ? "…" : `Subscribe to ${label || tier}`}</button>
      {info && !info.enabled && (
        <p className="note" style={{ marginTop: 8 }}>
          {info.discount_pct > 0 ? (
            <>Your price: <b>₹{info.amount_inr}</b>/mo <span style={{ textDecoration: "line-through" }}>₹{info.original_inr}</span> ({info.discount_pct}% off). </>
          ) : (<>Price: <b>₹{info.amount_inr}</b>/mo. </>)}
          {info.message}
        </p>
      )}
      {err && <p className="err" style={{ marginTop: 8 }}>{err}</p>}
    </div>
  );
}
