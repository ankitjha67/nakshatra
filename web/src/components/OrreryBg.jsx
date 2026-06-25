import React from "react";

// The full Navagraha orrery rendered behind the whole app (login + all tabs).
// `?bg` hides the marketing chrome but keeps it INTERACTIVE: the iframe sits at
// z-index:0 (content .wrap is above at z:1), so planets are clickable wherever
// the content column doesn't cover. Picking a planet postMessages the graha to
// the app, which renders the info card (GrahaCard) above everything.
// Skip the heavy (~6.6 MB textures + WebGL) orrery on constrained devices/networks:
// Save-Data, slow connections, or very low memory. Keeps mid-range Androids on weak
// signal fast — the decorative background isn't worth the load there.
function isConstrained() {
  if (typeof navigator === "undefined") return false;
  const c = navigator.connection || {};
  if (c.saveData) return true;
  if (["slow-2g", "2g"].includes(c.effectiveType)) return true;
  if (typeof navigator.deviceMemory === "number" && navigator.deviceMemory <= 1) return true;
  return false;
}

export default function OrreryBg() {
  if (isConstrained()) return null;   // graceful: app renders fine without the background orrery
  return (
    <iframe
      className="celestial"
      src={`${import.meta.env.BASE_URL || "/"}orrery.html?bg`}
      title="Nakshatra orrery — drag to orbit, click a planet"
      tabIndex={-1}
      loading="lazy"
    />
  );
}
