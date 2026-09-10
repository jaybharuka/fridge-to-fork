// One-off icon generation script for PWA support. Not part of the build —
// run manually (`node scripts/gen-pwa-icons.mjs`) whenever the icon design
// changes. Matches app/icon.svg's design exactly: solid #FC8019 background,
// bold white "F" glyph, centered.
import sharp from "sharp";
import { mkdirSync } from "fs";

const ORANGE = "#FC8019";
const WHITE = "#FFFFFF";

mkdirSync("public/icons", { recursive: true });

// Standard icon: glyph fills most of the canvas (14% corner radius, matches
// app/icon.svg's rx="14" on a 64px canvas = ~22% — scaled down slightly for
// larger canvases to read cleanly at a distance).
function standardSvg(size) {
  const r = Math.round(size * 0.16);
  const fontSize = Math.round(size * 0.53);
  const y = Math.round(size * 0.705);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" rx="${r}" fill="${ORANGE}" />
  <text x="${size / 2}" y="${y}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="${fontSize}" fill="${WHITE}">F</text>
</svg>`;
}

// Maskable icon: background fills edge-to-edge (required — the OS applies
// its own mask shape over the full square), glyph sized/centered to stay
// within an 80%-diameter safe-zone circle so it survives circle/squircle
// cropping on Android without clipping.
function maskableSvg(size) {
  const fontSize = Math.round(size * 0.36);
  const y = Math.round(size * 0.5 + fontSize * 0.35);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
  <rect width="${size}" height="${size}" fill="${ORANGE}" />
  <text x="${size / 2}" y="${y}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-weight="800" font-size="${fontSize}" fill="${WHITE}">F</text>
</svg>`;
}

const jobs = [
  ["public/icons/icon-192.png", standardSvg(192), 192],
  ["public/icons/icon-512.png", standardSvg(512), 512],
  ["public/icons/icon-maskable-512.png", maskableSvg(512), 512],
  ["app/apple-icon.png", standardSvg(180), 180], // Next.js file convention: auto-injects apple-touch-icon link
];

for (const [path, svg, size] of jobs) {
  await sharp(Buffer.from(svg)).resize(size, size).png().toFile(path);
  console.log(`wrote ${path} (${size}x${size})`);
}
