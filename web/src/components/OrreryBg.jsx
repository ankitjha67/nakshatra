import React from "react";

// The full Navagraha orrery rendered quietly behind the whole app (login + all
// tabs). `?bg` hides its overlay and disables interaction, so planets simply
// drift in the background while the app's content floats on top. Non-interactive
// (pointer-events:none via .celestial) so it never intercepts clicks.
export default function OrreryBg() {
  return (
    <iframe
      className="celestial"
      src={`${import.meta.env.BASE_URL || "/"}orrery.html?bg`}
      title="Nakshatra orrery"
      aria-hidden="true"
      tabIndex={-1}
      loading="eager"
    />
  );
}
