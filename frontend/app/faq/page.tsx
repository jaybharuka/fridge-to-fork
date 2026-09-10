import type { Metadata } from 'next';
import { StaticPage } from '@/components/shared/StaticPage';
import { FaqAccordion } from './FaqAccordion';

export const metadata: Metadata = {
  title: 'Fridge to Fork: FAQ',
  description: 'Answers to common questions about how Fridge to Fork scans your fridge, matches recipes, and orders what you\'re missing.',
};

const FAQS: { q: string; a: string }[] = [
  {
    q: 'Is my fridge photo stored?',
    a: "No. Your photo is sent to the vision service (Google's Gemini, and optionally AWS Rekognition if it's configured) for a single scan, then the temporary copy on the server is deleted as soon as that scan finishes. Nothing is kept afterward.",
  },
  {
    q: 'How accurate is the fridge scanning?',
    a: "It's good with clearly visible, well-lit items, and less reliable with items stacked behind each other, in opaque containers, or in a dim/cluttered shot. Every detected item shows a confidence level, and you can always manually check items off the list yourself. The scan is a starting point, not the final word.",
  },
  {
    q: 'Do I need a Swiggy account to use this?',
    a: 'No, you can scan your fridge and get a recipe without connecting anything. You only need to connect a Swiggy account when you actually want to place an order (either for the missing ingredients via Instamart, or for the finished dish via Swiggy Food).',
  },
  {
    q: "What if an ingredient isn't detected correctly?",
    a: "Just tap it in the checklist to toggle whether you have it. The scan is a best-effort suggestion, not a source of truth, and every item stays fully editable before you order anything.",
  },
  {
    q: 'Is this affiliated with Swiggy?',
    a: "Fridge to Fork was built independently, using Swiggy's public MCP integration as part of the Swiggy Builders Club program. It isn't an official Swiggy product.",
  },
];

export default function FaqPage() {
  return (
    <StaticPage title="Frequently asked questions">
      <FaqAccordion faqs={FAQS} />
    </StaticPage>
  );
}
