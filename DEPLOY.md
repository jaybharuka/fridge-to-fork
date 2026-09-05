# Deploying Fridge to Fork

Backend (FastAPI, `app.py`) → **Railway**. Frontend (Next.js, `frontend/`) →
**Vercel**. Both have free tiers with no payment method required at signup —
chosen specifically to avoid GCP's ₹1,000 India prepayment requirement.

Nothing below has been run. Nothing in this repo talks to Railway or Vercel
yet.

## 0. Before running anything here

Tell Claude:
1. Confirm you're logged in to both CLIs (`railway login`, `vercel login`
   open a browser) — or say so and I'll walk you through it first.
2. Confirm the deploy order below is fine, since it's a two-pass process
   (backend first, then frontend, then one backend env-var update).

Nothing that pushes to either platform runs until you've reviewed the exact
command and said go.

## Why Dockerfile over Railway's Nixpacks auto-build

Railway auto-detects a `Dockerfile` at the repo root and uses it instead of
its Nixpacks buildpack when one exists. Kept the `Dockerfile` (originally
written for Cloud Run) as-is rather than letting Nixpacks improvise a build
from `pyproject.toml` — it's already verified to install correctly (`pip
install .`) and import cleanly, and pins the exact base image and system
libs (`libjpeg`, `zlib` for Pillow) instead of leaving that to
auto-detection. `.dockerignore` still applies unchanged (keeps `frontend/`,
`.env`, `.venv/` out of the image). No Railway-specific config file needed —
Dockerfile presence is enough.

## 1. Deploy the backend to Railway

Two ways in; recommending the dashboard for a first deploy since it also
wires up auto-deploy-on-push for free, but the CLI sequence is here too.

**Dashboard (recommended):**
1. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
   → select this repo.
2. Railway will find the root `Dockerfile` and build from it. If it also
   finds `frontend/` and tries to treat this as a monorepo, set the
   service's **Root Directory** to `/` (repo root) explicitly in Settings.
3. Once deployed, Settings → Networking → **Generate Domain** to get the
   public HTTPS URL (Railway doesn't auto-assign one by default — it's a
   toggle, not automatic like the CLI, next section).

**CLI equivalent:**
```bash
railway login
railway init          # creates a new Railway project, run from repo root
railway up            # builds the Dockerfile and deploys
railway domain        # generates/shows the public HTTPS URL
```

### Environment variables (Railway → Settings → Variables, not committed anywhere)

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | your Gemini key |
| `GEMINI_SUGGESTIONS_API_KEY` | your Gemini key |
| `YOUTUBE_API_KEY` | your YouTube Data API key |
| `UNSPLASH_ACCESS_KEY` | your Unsplash key |
| `SWIGGY_CLIENT_ID` | your Swiggy OAuth client ID |
| `SECRET_KEY` | fresh random value — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `APP_BASE_URL` | *(set after step 3 — the Vercel frontend URL)* |
| `FRONTEND_ORIGIN` | *(set after step 3 — same Vercel frontend URL)* |

Railway sets `PORT` itself; the `Dockerfile`'s `CMD` already reads it, don't
add it manually.

**Free tier note:** Railway's free tier is a **monthly usage credit**
(currently $5/month, not unlimited), consumed by compute + egress while the
service is running — it is not scale-to-zero by default the way Cloud Run
is, so an idle service still burns credit unless you enable sleep/idle
settings in the service's Settings. Worth checking Railway's current
pricing page since this changes over time.

## 2. Update the Swiggy OAuth app config

In the Swiggy developer console that issued `SWIGGY_CLIENT_ID`: once you
have the Vercel frontend URL from step 3, register
`https://<your-vercel-url>/auth/callback` as an allowed redirect URI (the
value `app.py`'s `_app_base_url()` + `/auth/callback` will build from
`APP_BASE_URL`). Remove/replace the localhost one if it's the same list.

## 3. Deploy the frontend to Vercel

**Dashboard (recommended — also gets auto-deploy on push):**
1. [vercel.com](https://vercel.com) → Add New → Project → import this
   GitHub repo.
2. **Root Directory must be set to `frontend`** — Vercel defaults to the
   repo root, which has no `package.json` and will fail to detect Next.js.
   This is in the import wizard's "Root Directory" field, or Settings →
   General → Root Directory afterward.
3. Settings → Environment Variables → add `BACKEND_URL` = the Railway
   backend URL from step 1.
4. Deploy. Vercel assigns a `*.vercel.app` URL automatically.

**CLI equivalent** (run from `frontend/`, not the repo root):
```bash
cd frontend
vercel login
vercel                # links + deploys; prompts for env vars or set them after via `vercel env add`
```

## 4. Close the loop — backend needs the frontend's URL

Same chicken-and-egg as any two-service deploy: `APP_BASE_URL` and
`FRONTEND_ORIGIN` on the backend need the Vercel URL, which doesn't exist
until step 3. Once you have it:

```bash
railway variables --set APP_BASE_URL=https://<your-vercel-url> --set FRONTEND_ORIGIN=https://<your-vercel-url>
```

Railway restarts the service automatically when variables change via
`railway variables --set`; via the dashboard, a manual redeploy may be
needed — it'll say so.

**Why `APP_BASE_URL` = the frontend's URL, not the backend's:** the Swiggy
OAuth `redirect_uri` is built from `APP_BASE_URL`. Setting it to the
frontend origin means Swiggy redirects the browser to the frontend, which
Next.js proxies to the backend (`next.config.js` rewrites) — so the session
cookie set by `SessionMiddleware` lands on the frontend's origin, and the
post-login relative redirect (`RedirectResponse("/")`) resolves back to the
frontend. Same pattern already used for local dev (`APP_BASE_URL=http://localhost:3000`,
see `frontend/README.md`).

## Known risk: Vercel function timeouts vs. long SSE streams

`/api/scan` can legitimately run 30–60s (vision + meal-planning calls;
`app.py` itself uses a 60s timeout on the vision step). Vercel's **Hobby
plan caps serverless function execution at 10s** by default. Whether this
bites depends on how Vercel implements `next.config.js`'s external
`rewrites()` — a config-level proxy rule is typically handled at Vercel's
edge/routing layer and isn't subject to the Lambda execution limit the way
an API route handler would be, but I haven't verified this against a live
Vercel deployment and don't want to assert it works. **Test the actual scan
flow against the deployed frontend before trusting it.**

If it does get cut off: the fallback is calling the Railway backend
directly from the browser for `/api/scan` and `/api/order` (absolute URL,
`credentials: 'include'`) instead of routing them through the Vercel
rewrite proxy — the CORS (`FRONTEND_ORIGIN`) and cookie (`same_site="none"`,
`https_only=True`) settings in `app.py` already support this cross-origin
call pattern, so it's a frontend-only change (a `NEXT_PUBLIC_BACKEND_URL`
env var + two `fetch()` call sites in `useScanStream.ts`) if it comes to
that. Not doing this preemptively — no sense adding it before confirming
the proxy actually fails.

## Local dev — unchanged

`frontend/next.config.js` still defaults `BACKEND_URL` to
`http://localhost:8000` when unset, so `npm run dev` needs no new env vars
locally.
