# Fridge to Fork — Next.js frontend

Next.js (App Router + TypeScript) port of the vanilla `templates/index.html`
UI. It has no backend of its own: the dev server proxies `/api/*` and
`/auth/*` to the FastAPI app in the repo root (`app.py`) on port 8000, so
both must be running.

## Running locally

### 1. Backend (repo root)

Install the project's dependencies (see `pyproject.toml`) into a venv, copy
`.env.example` to `.env` and fill it in, then:

```bash
APP_BASE_URL=http://localhost:3000 uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

On Windows PowerShell:

```powershell
$env:APP_BASE_URL = "http://localhost:3000"
.\.venv\Scripts\uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend (this directory)

```bash
npm install
npm run dev
```

Open <http://localhost:3000>. Do **not** use <http://localhost:8000> — that
serves the old vanilla frontend.

## Required: `APP_BASE_URL=http://localhost:3000`

The Swiggy OAuth `redirect_uri` is built from the backend's `APP_BASE_URL`,
which defaults to `http://localhost:8000`. With the default, signing in to
Swiggy sends the browser to `localhost:8000/auth/callback` — bypassing this
frontend's proxy — and the backend's post-auth redirect to `/` then lands
the user on the **old vanilla UI on :8000**, with the in-progress scan lost.

So when you run this frontend, set `APP_BASE_URL=http://localhost:3000` in
the backend's environment (shell export as above, or in the root `.env`).
Leave the committed default at `:8000` — that is correct for anyone using
the vanilla frontend directly. This is a per-developer override.

## Scripts

- `npm run dev` — dev server on :3000 with the `/api` + `/auth` proxy (see `next.config.js`)
- `npm run build` — production build
- `npx tsc --noEmit` — type check
- `npm run lint` — ESLint
