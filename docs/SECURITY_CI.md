# Security scanning — results & CI automation

**Date:** 2026-06-25. Covers the scan run on this codebase + the automated pipeline.

## Local scan results (run 2026-06-25)
| Scanner | Scope | Result |
|---|---|---|
| **pip-audit** | Python deps (installed env) | **5 CVEs found → FIXED.** cryptography 48.0.0→48.0.1, msgpack 1.1.2→1.2.1, pydantic-settings 2.14.1→2.14.2, starlette 1.2.1→1.3.1 (CVE-2026-54282/54283). Secure floors pinned in `api/requirements.txt`; re-audit clean; 100 tests pass. |
| **npm audit** | web deps | **0 vulnerabilities** (post React 19 / Firebase 12 / Vite 8 upgrade). |
| **detect-secrets** | working tree | 8 hits, **all false positives** (gitignored `.env`/pytest cache, runtime key *generators* `secrets.token_urlsafe`, the code alphabet, env-var *names* in deploy scripts, test dummy secret). No real secret committed. |
| **git history** | all commits | **Clean** — no `.env`, service-account JSON, `.pem`/`.key`, or the proprietary engine was ever committed. |

## CI pipeline (`.github/workflows/`)
No CI existed before (only `dependabot.yml`). Added:

| Workflow | Tool | What it does | Account needed |
|---|---|---|---|
| `ci.yml` | pytest + vite | Runs the API test suite (mock engine, no GCP creds) and the web build on every push/PR | none |
| `codeql.yml` | **GitHub CodeQL** | SAST for Python + JS/TS (`security-extended`); alerts under Security → Code scanning; weekly + on PR | none (free, public repo) |
| `security.yml` | **TruffleHog** + **pip-audit** + **npm audit** | Secret scan over full git history; dependency CVE audits; weekly + on push/PR | none |
| `zap-dast.yml` | **OWASP ZAP** baseline | Passive DAST (spider + passive rules) against the live URL; files an issue with findings; manual + weekly | none |
| `optional-scanners.yml` | **Snyk** + **GitGuardian** | Dormant until opted in (named tools, redundant with the free set above) | yes (tokens) |

This satisfies the requested choices with zero-account options: **"Snyk *or* GitHub code scanning" → CodeQL**, **"GitGuardian *or* TruffleHog" → TruffleHog**. Snyk + GitGuardian are also wired, dormant.

### Enabling the optional scanners
- **Snyk:** add secret `SNYK_TOKEN` + repo variable `ENABLE_SNYK=true`.
- **GitGuardian:** add secret `GITGUARDIAN_API_KEY` + repo variable `ENABLE_GITGUARDIAN=true`.
- (Settings → Secrets and variables → Actions.)

### GitHub native settings to flip on (one-time, in repo Settings → Code security)
- **Secret scanning** + **push protection** (free for public repos) — blocks secret pushes.
- **Dependabot alerts** + **security updates** (Dependabot config already present for version PRs).
- **CodeQL** results require nothing extra — the workflow uploads to code scanning automatically.

## DAST / pen-test tooling — honest status
- **OWASP ZAP**: automated in CI as a **baseline (passive)** scan (`zap-dast.yml`). A full **active**
  scan (attack payloads) should be run against a **staging** environment, not prod — point the
  `target` input at staging and switch to `zaproxy/action-full-scan` when you have one.
- **Burp Suite**: an interactive, commercial GUI proxy — **not headless-automatable** in CI. Its
  manual-testing ground (auth bypass, IDOR, request tampering, fuzzing) is covered by the manual API
  audits already done (`SECURITY_AUDIT_RACE_INJECTION_IDOR.md`, `PRELAUNCH_CHECKLIST.md`) and by ZAP +
  CodeQL. If you want a true human pen-test with Burp, that's an external engagement.

## ZAP baseline scan — first run (2026-06-25, issue #17)
Ran against the live site. **No high/critical findings** — every alert was a missing security
**HTTP header**. Remediated by adding headers in `web/firebase.json` (verified live):
`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` (anti-clickjacking; still lets the
app frame its own orrery), `Referrer-Policy`, `Permissions-Policy` (camera/mic/geo off),
`Cross-Origin-Opener-Policy: same-origin-allow-popups` (keeps Google OAuth popups working), `HSTS`.

**Deliberately NOT added** (would break the live app — do via report-only + staging):
- **CSP** — needs a per-origin policy allowing Firebase/Google/Vertex/the Cloud Run API + the orrery;
  add as `Content-Security-Policy-Report-Only` first, watch reports, then enforce.
- **COEP `require-corp` / CORP** — would block cross-origin Firebase/Vertex resources.
- **SRI** — low value for same-origin Vite-built assets.
- Cache-control tuning + "Base64 disclosure" (false positive: base64 data inside the JS bundle).

(The ZAP workflow run shows "failure" only due to an artifact-upload API quirk in the action; the
scan completes and files the report regardless.)

## Owner to-dos
1. Merge this so the workflows activate, then check the first runs under the **Actions** tab.
2. Flip on the GitHub native settings above.
3. Rotate any secret ever pasted into an external AI chat/tool (transcripts are outside our control).
4. (Optional) add Snyk/GitGuardian tokens; stand up a staging env for ZAP **active** scans.
