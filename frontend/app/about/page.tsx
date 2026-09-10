import type { Metadata } from 'next';
import { StaticPage } from '@/components/shared/StaticPage';

export const metadata: Metadata = {
  title: 'Fridge to Fork: About',
  description:
    'Fridge to Fork is a solo-built app that scans your fridge, figures out what to cook, and orders whatever you\'re missing through a live Swiggy integration.',
};

export default function AboutPage() {
  return (
    <StaticPage title="About Fridge to Fork" lead="Cook anything. Order what's missing.">
      <p>
        Fridge to Fork is a small app built by a solo developer. Point your camera at your
        fridge (or just tell it what you want to cook), and it figures out what you can make
        right now and what you&apos;d need to order to finish the dish.
      </p>

      <h2>How it works</h2>
      <p>
        A photo of your fridge is analysed with Google&apos;s Gemini vision model to detect
        what&apos;s actually in there. That gets matched against a recipe for the dish you asked
        for (or a suggestion, if you didn&apos;t name one), which sorts every ingredient into
        &quot;you have it&quot; or &quot;you need it.&quot;
      </p>
      <p>
        Anything missing can be ordered straight from Instamart, or you can get the finished
        dish delivered instead, both routed through a live Swiggy MCP integration built as part
        of the Swiggy Builders Club.
      </p>

      <h2>Who built this</h2>
      <p>
        One person, in their own time. There&apos;s no team, no funding, and no user numbers to
        brag about, just an app that tries to be genuinely useful for the very ordinary problem
        of staring into a fridge with no idea what to make.
      </p>
    </StaticPage>
  );
}
