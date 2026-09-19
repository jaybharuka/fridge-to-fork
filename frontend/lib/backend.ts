// Direct Render origin for the long-running/authenticated /api calls; empty
// falls back to the same-origin next.config.js proxy (local dev). See the
// comment in useScanStream.ts for why these bypass the Vercel proxy.
export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '';
