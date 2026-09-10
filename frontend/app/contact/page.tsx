import type { Metadata } from 'next';
import { Mail } from 'lucide-react';
import { StaticPage } from '@/components/shared/StaticPage';
import styles from './contact.module.css';

export const metadata: Metadata = {
  title: 'Fridge to Fork: Contact',
  description: 'Get in touch about Fridge to Fork: bugs, feedback, or anything else.',
};

const CONTACT_EMAIL = 'jaybharuka7@gmail.com';

export default function ContactPage() {
  return (
    <StaticPage
      title="Contact"
      lead="Found a bug, have feedback, or just want to say hi? Reach out directly."
    >
      <a href={`mailto:${CONTACT_EMAIL}`} className={styles.emailLink}>
        <Mail size={18} />
        <span>{CONTACT_EMAIL}</span>
      </a>
    </StaticPage>
  );
}
