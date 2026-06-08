import React from "react";

// The full Navagraha orrery rendered behind the whole app (login + all tabs).
// `?bg` hides the marketing chrome but keeps it INTERACTIVE: the iframe sits at
// z-index:0 (content .wrap is above at z:1), so planets are clickable wherever
// the content column doesn't cover. Picking a planet postMessages the graha to
// the app, which renders the info card (GrahaCard) above everything.
export default function OrreryBg() {
  return (
    <iframe
      className="celestial"
      src={`${import.meta.env.BASE_URL || "/"}orrery.html?bg`}
      title="Nakshatra orrery — drag to orbit, click a planet"
      tabIndex={-1}
      loading="eager"
    />
  );
}
