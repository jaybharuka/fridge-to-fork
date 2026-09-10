import type { MetadataRoute } from "next";

// Next.js App Router convention: this file is auto-served as
// /manifest.webmanifest and linked from <head> automatically — no manual
// <link rel="manifest"> needed.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Fridge to Fork",
    short_name: "F2F",
    description:
      "Scan your fridge, get a recipe you can actually make, and order whatever's missing straight from Instamart or Swiggy.",
    start_url: "/",
    display: "standalone",
    background_color: "#0F0F0F",
    theme_color: "#FC8019",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
