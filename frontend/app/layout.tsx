import type { Metadata } from "next";
import { Analytics } from "@vercel/analytics/react";
import { Footer } from "@/components/shared/Footer";
import { ServiceWorkerRegister } from "@/components/shared/ServiceWorkerRegister";
import "./globals.css";

const TITLE = "Fridge to Fork — Cook anything. Order what's missing.";
const DESCRIPTION =
  "Scan your fridge, get a recipe you can actually make, and order whatever's missing straight from Instamart or Swiggy.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000"),
  title: TITLE,
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  // iOS Safari doesn't fully respect the web manifest — these are what
  // actually drive the standalone/no-browser-chrome experience there.
  // apple-touch-icon itself is auto-injected by the app/apple-icon.png
  // file convention, not set here.
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Fridge to Fork",
  },
};

export const viewport = {
  themeColor: "#FC8019",
};

const themeInitScript = `(function(){try{var t=localStorage.getItem('theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        {/* Next.js's typed `appleWebApp` metadata (below) emits the modern
            mobile-web-app-capable tag, but iOS Safari's full-screen/
            standalone launch specifically still keys off this legacy
            Apple-prefixed one — Chrome/Android already gets it from the
            manifest's display:"standalone", iOS doesn't fully defer to
            that yet, so both tags stay. */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
      </head>
      <body>
        <a href="#main-content" className="skip-link">Skip to content</a>
        {children}
        <Footer />
        <Analytics />
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
