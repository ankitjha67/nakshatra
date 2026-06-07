import React, { useEffect, useRef } from "react";

// Original, code-rendered interstellar backdrop: a layered starfield with gentle
// parallax drift and twinkle over a deep-space nebula gradient. No images, no
// dependencies. Honors prefers-reduced-motion (renders one static frame).
export default function CelestialBackground() {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const LAYERS = [
      { n: 110, sp: 0.05, r: [0.35, 0.9], a: 0.45 },
      { n: 70, sp: 0.13, r: [0.6, 1.3], a: 0.7 },
      { n: 26, sp: 0.24, r: [0.9, 1.9], a: 0.95 },
    ];
    let w = 0, h = 0, stars = [], raf = 0, running = true, t0 = performance.now();
    const rand = (a, b) => a + Math.random() * (b - a);

    function build() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = Math.max(1, w * dpr); canvas.height = Math.max(1, h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      stars = [];
      for (const L of LAYERS) {
        for (let i = 0; i < L.n; i++) {
          const warm = Math.random() < 0.16;
          stars.push({
            x: Math.random() * w, y: Math.random() * h, r: rand(L.r[0], L.r[1]),
            a: L.a * rand(0.5, 1), tw: rand(0, Math.PI * 2), tws: rand(0.5, 1.6),
            sp: L.sp, hue: warm ? rand(36, 46) : 44, sat: warm ? 45 : 10,
          });
        }
      }
    }

    function paintNebula() {
      ctx.fillStyle = "#05050b"; ctx.fillRect(0, 0, w, h);
      const big = Math.max(w, h);
      const g1 = ctx.createRadialGradient(w * 0.74, h * 0.26, 0, w * 0.74, h * 0.26, big * 0.75);
      g1.addColorStop(0, "rgba(180,138,76,0.11)"); g1.addColorStop(0.5, "rgba(120,90,50,0.04)"); g1.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g1; ctx.fillRect(0, 0, w, h);
      const g2 = ctx.createRadialGradient(w * 0.16, h * 0.82, 0, w * 0.16, h * 0.82, big * 0.65);
      g2.addColorStop(0, "rgba(42,62,112,0.13)"); g2.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g2; ctx.fillRect(0, 0, w, h);
    }

    function frame(now) {
      const t = (now - t0) / 1000;
      paintNebula();
      for (const s of stars) {
        if (!reduced) { s.x -= s.sp; if (s.x < -2) s.x = w + 2; }
        const tw = reduced ? 1 : 0.7 + 0.3 * Math.sin(s.tw + t * s.tws);
        ctx.beginPath();
        ctx.fillStyle = `hsla(${s.hue},${s.sat}%,90%,${Math.min(1, s.a * tw)})`;
        ctx.arc(s.x, s.y, s.r, 0, 7);
        ctx.fill();
      }
      if (!reduced && running) raf = requestAnimationFrame(frame);
    }

    build();
    frame(performance.now());

    const onResize = () => { build(); if (reduced) frame(performance.now()); };
    const onVis = () => {
      running = !document.hidden;
      if (running && !reduced) { t0 = performance.now(); raf = requestAnimationFrame(frame); }
    };
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  return <canvas ref={ref} className="celestial" aria-hidden="true" />;
}
