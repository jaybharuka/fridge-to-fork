import { readFileSync } from 'fs';
import { join } from 'path';
import { ImageResponse } from 'next/og';

export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

// Generated programmatically at build/request time — no fetched or
// fabricated screenshot, just the real app icon (app/og-logo.png, the same
// artwork used for app/icon.png and public/icons/*) + tagline on the app's
// own orange (#FC8019), matching --orange in globals.css.
export default function OpengraphImage() {
  const logo = readFileSync(join(process.cwd(), 'app', 'og-logo.png'));
  const logoDataUrl = `data:image/png;base64,${logo.toString('base64')}`;

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#FC8019',
          fontFamily: 'sans-serif',
        }}
      >
        <img
          src={logoDataUrl}
          width={120}
          height={120}
          style={{ borderRadius: 28, marginBottom: 32 }}
        />
        <div style={{ display: 'flex', fontSize: 64, fontWeight: 800, color: '#FFFFFF' }}>
          Fridge to Fork
        </div>
        <div style={{ display: 'flex', fontSize: 30, fontWeight: 500, color: 'rgba(255,255,255,0.85)', marginTop: 16 }}>
          Cook anything. Order what&apos;s missing.
        </div>
      </div>
    ),
    { ...size }
  );
}
