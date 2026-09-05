# Deploying Fridge to Fork

Backend (FastAPI, `app.py`) → **Render**. Frontend (Next.js, `frontend/`) →
**Vercel**. Both have free tiers with no payment method required at signup.
(Railway was the original plan; its no-card free trial expired mid-setup, so
the backend moved to Render — `render.yaml` at the repo root is a Render
Blueprint, unrelated to the `Dockerfile` it also happens to use.)

## Current live deployment

- Backend: `https://fridge-to-fork-j584.onrender.com` (Render, Singapore region, free plan)
- Frontend: `https://fridge-to-fork-cyan.vercel.app` (Vercel, auto-assigned production alias)
  - `https://fridgetofork-app.vercel.app` also points here, but sits behind
    Vercel's account-wide Deployment Protection (redirects to a Vercel
    login) until you disable it: **dashboard → fridge-to-fork project →
    Settings → Deployment Protection → set to "Only Preview Deployments"**.

## 1. Backend on Render

Render Blueprint deploy (what was actually used): **dashboard.render.com →
New → Blueprint → connect the GitHub repo → branch
`feat/nextjs-frontend-migration`** → Render reads `render.yaml` and creates
the `fridge-to-fork` web service (Docker, `./Dockerfile`, Singapore, free
plan). This step needs your own GitHub App authorization click — not
scriptable.

### Environment variables (Render → service → Environment, not committed anywhere)

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | your Gemini key |
| `GEMINI_SUGGESTIONS_API_KEY` | your Gemini key |
| `YOUTUBE_API_KEY` | your YouTube Data API key |
| `UNSPLASH_ACCESS_KEY` | your Unsplash key |
| `SWIGGY_CLIENT_ID` | your Swiggy OAuth client ID |
| `SECRET_KEY` | fresh random value — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DELIVERY_ADDRESS` | e.g. `Mumbai, India` |
| `APP_BASE_URL` | the Vercel frontend URL, e.g. `https://fridge-to-fork-cyan.vercel.app` |
| `FRONTEND_ORIGIN` | same Vercel frontend URL |

Render injects `PORT` itself; the `Dockerfile`'s `CMD` already reads it.

**Free tier note:** Render's free web services **spin down after ~15
minutes of no inbound traffic** and take roughly 30-50s to cold-start back
up on the next request — this, stacked with the real 15-60s scan time, is
what produced the "taking longer than usual" false alarm on a live scan.
See §3 below for the mitigation.

## 2. Frontend on Vercel

**Dashboard (recommended — also gets auto-deploy on push):**
1. [vercel.com](https://vercel.com) → Add New → Project → import this
   GitHub repo.
2. **Root Directory must be set to `frontend`** — Vercel defaults to the
   repo root, which has no `package.json` and will fail to detect Next.js.
3. Settings → Environment Variables:
   - `BACKEND_URL` = the Render backend URL — used server-side, by
     `next.config.js`'s rewrite proxy for `/auth/*` and the non-streaming
     `/api/*` routes (dish-image, youtube, ingredient-image, dish-suggestions).
   - `NEXT_PUBLIC_BACKEND_URL` = **the same Render URL** — used client-side,
     by `useScanStream.ts`, to call `/api/scan` and `/api/order` directly
     instead of through the proxy (see §3). Must carry the `NEXT_PUBLIC_`
     prefix or Next.js won't bundle it into the browser build. Currently:
     **`https://fridge-to-fork-j584.onrender.com`**
4. Redeploy after adding/changing env vars — Vercel doesn't hot-reload them
   into an already-built deployment.

**CLI equivalent** (run from `frontend/`):
```bash
cd frontend
vercel env add NEXT_PUBLIC_BACKEND_URL production   # paste the Render URL when prompted
vercel --prod
```

Locally, both env vars are optional — `next.config.js` and
`useScanStream.ts` both default to `http://localhost:8000` /
same-origin-via-proxy when unset, so `npm run dev` needs no setup.

## 3. Fixed: SSE calls no longer go through Vercel's proxy

**The problem:** `/api/scan` and `/api/order` are long-running SSE streams
(15-60s: Gemini's two-pass vision + meal planning, worse right after a
Render cold start). Routing them through `next.config.js`'s rewrite proxy
risked hitting Vercel Hobby's serverless function execution limit (as short
as 10s) well before the real response finished — this is what a live user
hit: the "taking longer than usual" warning fired, then results actually
arrived 10-15s later once the (already-completed) response got through.

**The fix:** `useScanStream.ts`'s `startScan` and `placeOrder` now fetch
`${NEXT_PUBLIC_BACKEND_URL}/api/scan` / `/api/order` directly against
Render, bypassing the Vercel proxy entirely for these two calls.
`credentials: 'include'` (already in place) plus the CORS/`SessionMiddleware`
config in `app.py` (`FRONTEND_ORIGIN`, `same_site="none"`, `https_only=True`)
already support this cross-origin call — no backend change was needed.

Left on the proxy, deliberately: `/auth/*` (needs the cookie to land on the
frontend's origin — see the `APP_BASE_URL` note below), `/api/dish-image`
(5s backend timeout), `/api/ingredient-image` (4s), `/api/dish-suggestions`.
`/api/youtube` is borderline — 4 parallel calls at a 10s httpx timeout each,
so a slow one could theoretically brush against Vercel's 10s Hobby limit —
not the reported bug, left as-is, worth revisiting if it ever surfaces.

**Why `APP_BASE_URL` = the frontend's URL, not the backend's:** the Swiggy
OAuth `redirect_uri` is built from `APP_BASE_URL`. Setting it to the
frontend origin means Swiggy redirects the browser to the frontend, which
Next.js proxies to the backend for `/auth/*` — so the session cookie lands
on the frontend's origin, and the post-login relative redirect
(`RedirectResponse("/")`) resolves back to the frontend. Same pattern as
local dev (`APP_BASE_URL=http://localhost:3000`, see `frontend/README.md`).

## 4. Reducing Render cold starts (mitigates, doesn't eliminate)

Render's free tier sleeps the service after ~15 min idle regardless of
anything below — there is no way to fully disable that on the free plan.
Pinging `/health` (already a trivial `{"status": "ok", ...}` handler, no
heavy logic) every ~10 minutes during hours you expect real traffic keeps
it warm through that window; it will still cold-start overnight or whenever
nobody's pinged it recently.

**Set up one of these — needs your own account, not scriptable from here:**

- **cron-job.org** (simplest): free account → Create Cronjob → URL
  `https://fridge-to-fork-j584.onrender.com/health` → schedule "every 10
  minutes" → save. No code, no repo changes.
- **GitHub Actions**, if you'd rather keep it in-repo — add
  `.github/workflows/keep-warm.yml`:
  ```yaml
  name: keep-warm
  on:
    schedule:
      - cron: '*/10 * * * *'
  jobs:
    ping:
      runs-on: ubuntu-latest
      steps:
        - run: curl -sf https://fridge-to-fork-j584.onrender.com/health
  ```
  (GitHub's schedule trigger is best-effort and can slip by several minutes
  under load — fine for this purpose, not a guarantee.)

Either way: this reduces *how often* a user eats a cold start, it does not
remove the possibility. The soft-notice/hard-notice UI change in
`PhotoScanScreen.tsx` (§5) is what actually makes an occasional slow scan
feel normal instead of broken.

## 5. Loading-screen pacing (UX fix)

`PhotoScanScreen.tsx`'s single 35s "This is taking longer than usual"
warning fired well inside normal scan time on the real deployment (cold
start + two-pass vision routinely lands in 15-60s) and read as a false
alarm. Replaced with two thresholds:

- **60s — soft notice:** "Still scanning, almost there", no warning icon,
  a quiet text-link "Try again" (not a filled button). Sub-status messages
  (now 7 phrases instead of 3, still cycling every 3.5s) keep rotating
  throughout, so the screen never goes quiet waiting for this.
- **90s — hard notice:** the original treatment — `CircleAlert` icon,
  "This is taking longer than usual", filled "Try again" button. Only
  fires once a scan is genuinely long enough to look like a stall.

A real `error` SSE event or network failure is unaffected — that's a
separate code path (`useScanStream`'s `phase === 'error'`), never routed
through this soft/hard notice UI.
