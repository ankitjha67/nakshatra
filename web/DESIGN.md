# web/DESIGN.md — Nakshatra design system (binding)

This is the visual contract for everything in `web/`. Follow it from the first frontend commit.
`web/src/styles.css` is the live source of the tokens; this file explains the *intent* and the rules so
the look stays coherent. **Do not introduce a different aesthetic.** When unsure, match the existing
`web/src/styles.css` and the reference assets in `web/public/`.

## The brand, in one line

Nakshatra is **antiquarian-celestial editorial luxury** for Vedic astrology — a quiet, scholarly,
sacred-but-never-kitsch feel, like a finely printed old star atlas. It is *not* a generic SaaS dashboard,
not a "mystical app" of neon purple gradients and crystal-ball clip-art, not a startup landing page.

Mood words: antiquarian, celestial, editorial, contemplative, literate, warm, restrained.

## Hard rules (do / don't)

**Never:**
- ❌ No emoji used as icons or decoration anywhere in the UI (no 🔮 ✨ 🌟 🔒 as graphics). Emoji are a tell
  of generic AI design. *(Known fix: `App.jsx` currently uses a 🔒 emoji on locked tabs — replace it with
  the hand-drawn SVG lock below.)*
- ❌ No "AI-sparkle" motifs, no generic purple→blue gradient blobs, no glassmorphism, no neon glow.
- ❌ No stock clip-art, cartoon planets, or zodiac-cartoon mascots.
- ❌ Do not change the type pairing or the palette. Do not add new fonts or new accent colors.
- ❌ No generic SaaS/startup tropes (rounded-everything pill buttons in bright blue, hero with a laptop
  mockup, "trusted by" logo walls).

**Always:**
- ✅ Use the established type pairing and palette (below).
- ✅ Hand-crafted inline **SVG** icons — thin, single-weight line icons (see the Google "G" in
  `SignIn.jsx` for the level of craft). Geometric, celestial-leaning where natural (rings, orbits, stars
  as fine strokes — not emoji stars).
- ✅ Real **photography** when imagery is needed — astronomy/observatory/manuscript/night-sky textures,
  not illustration. Source from Unsplash; prefer dark, grainy, archival-feeling images. Reuse the
  project's own assets first (the planet plates and poster in `web/public/`).
- ✅ Film **grain** + subtle **vignette** on full-bleed/hero surfaces (the `body::before/::after` pattern
  already in `styles.css`).
- ✅ Fine **hairline rules** (1px, `--line`), generous whitespace, large serif headlines.
- ✅ **₹ (INR)** for all pricing.
- ✅ UI copy: warm, literate, second person, never breathless or salesy; no pet names; no exclamation
  spam. Readings are "for reflection, not fixed prediction."

## Tokens (authoritative — mirror of `styles.css`)

**Color** (CSS variables; never hardcode hexes — use the vars):
| var | hex | role |
|-----|-----|------|
| `--ink` | `#0c0c16` | primary text; near-black blue-black |
| `--ink-soft` | `#2a2a38` | secondary text, body inside sections |
| `--cream` | `#f4ecdb` | page background |
| `--paper` | `#fbf7ec` | raised surfaces (cards) |
| `--brass` | `#b48a4c` | accents, kickers, links (used sparingly), focus ring |
| `--marigold` | `#c4682b` | rare hot accent / link hover — use lightly |
| `--line` | `#d9cdb0` | hairline borders & dividers |
| `--muted` | `#7a735d` | meta text, captions, mono labels |

Usage: ink/ink-soft for text on cream/paper; brass for small accents and the focus ring; marigold only
as an occasional emphasis. Brass/marigold must **not** be used for body text (contrast). A dark mode is
out of scope unless explicitly requested — the identity is the warm cream/ink "printed page".

**Type:**
- Display / headings → **Cormorant Garamond** (serif), weights 400/500/600. Headlines are large and
  set in 500–600.
- Body / UI → **Hanken Grotesk** (sans), 400/500/600.
- Labels / kickers / meta / numbers → **IBM Plex Mono**, 400/500, UPPERCASE, letter-spacing ~0.12–0.28em.
- Kicker pattern: small mono, uppercase, wide tracking, `--brass`, sits above a headline.

**Shape & depth:**
- Cards: `--paper` bg, `1px solid --line`, radius **14px**, shadow `0 14px 40px rgba(12,12,22,.05)`,
  padding ~24px.
- Inputs/buttons: radius **10px**. Focus ring: `0 0 0 3px rgba(180,138,76,.18)` + `--brass` border.
- Primary button: solid `--ink` bg, `--cream` text. Ghost button: transparent, `--ink` text/border.
- Section dividers and the reading's "Drawn from" footer use `--line` + mono.

## Component patterns to reuse (don't reinvent)

- **Kicker + headline**: `<p class="kicker">…</p>` then an `<h1/h2>` in Cormorant. Use on every panel.
- **Card**: the `.card` surface for forms, paywalls, stubs.
- **Birth form**: the `BirthForm` layout (2-col grid, mono field labels, city `<select>` + custom
  coords). Keep it.
- **Reading**: `Reading.jsx` — Cormorant summary with a left brass rule, each section as serif H3 + body,
  and the mono **"Drawn from: …"** footer listing cited finding titles in brass. This footer is a core
  brand signal (it's how we *show* the anti-slop grounding) — keep it on every reading-type tab.
- **Tabs**: mono uppercase tab labels; active tab = paper surface with a hairline top border.
- **Paywall card** (locked tab): kicker + Cormorant "Unlocks on a higher plan" + muted explanation +
  (later) a ₹-priced upgrade affordance. Calm, not pushy.
- **Lock indicator**: replace the 🔒 emoji with a hand-drawn SVG, e.g.
  `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="5" y="11" width="14" height="9" rx="1.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>`
  rendered in `--muted`.

## Imagery & the reference assets

In `web/public/` (treat as the tone reference and reuse them):
- `nakshatra-orrery.html` — the 3D Three.js orrery; this is the reference for a **hero/landing** moment
  and the overall celestial mood. It can be embedded/linked as a landing route.
- `planet-plates/*.png` — photoreal planet portraits (from NASA textures). Use as section/tab imagery
  (e.g., a Saturn plate beside the Saturn-heavy timing section). Don't redraw planets — use these.
- `the-wandering-lights-poster.png` — the editorial poster; reference for layout/typographic rhythm.

When a surface needs new imagery and these don't fit, use real Unsplash photography matching the mood
(observatories, star fields, old star charts, brass instruments) — dark, grainy, archival. Always favor
photography or the existing plates over any illustration.

## Per-tab visual intent

Keep one coherent system; vary tone subtly, not structure.
- **Natal / Maha-Kundali** — the editorial reading layout (kicker, summary, sections, "Drawn from").
  Maha is the "complete report" — it can feel a touch grander (more sections), same language.
- **Yearly** — same reading layout + a restrained year picker; a forward/temporal feel.
- **Prashna** — single question + location; quieter, oracular, focused; a clear verdict block.
- **Chat** — a calm reading-room conversation; message bubbles must stay on-brand (paper/cream, hairline,
  serif for the model's voice is fine, mono for meta); a small mono credits indicator, not a loud meter.
- **Birth-Time Rectification** — instrument-like, precise; a confidence meter rendered as a fine
  hairline/brass scale, never a chunky progress bar.

## Accessibility

- Body text in `--ink`/`--ink-soft` on `--cream`/`--paper` (high contrast). Don't set body copy in brass
  or marigold. Keep the focus ring visible. Respect `prefers-reduced-motion` for the orrery/animations.

## A limit worth knowing

Claude Code can **match and extend** this system (reuse the tokens, the plates, the orrery, these rules)
but it cannot regenerate the photoreal planet art or a new 3D scene from scratch — those were made in a
dedicated design session. If a phase needs *new* hero art or imagery, generate it in such a session and
drop the output into `web/public/` for wiring in. Don't substitute generic AI-generated gradients/clip-art.
