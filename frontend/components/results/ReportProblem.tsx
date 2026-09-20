'use client';

import { Mail } from 'lucide-react';
import { useState } from 'react';
import { foodReport } from '@/lib/food';
import { instamartReport, localReportText, type ProblemReport, type ReportInput } from '@/lib/instamart';
import styles from './instamart.module.css';

type Phase =
  | { kind: 'idle' }
  | { kind: 'form' }
  | { kind: 'busy' }
  | { kind: 'ready'; report: ProblemReport }
  | { kind: 'unavailable'; text: string };

interface ReportProblemProps {
  /** What went wrong, in Swiggy's terms: the failing tool, the error and the identifiers involved. */
  input: Omit<ReportInput, 'notes'>;
  label?: string;
  /** Which Swiggy server the failing tool belongs to (its report goes to that server's report_error). */
  product?: 'instamart' | 'food';
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// A way out of a dead end: asks Swiggy (report_error) to prepare a report, then hands the user a pre-filled
// email to send themselves. Nothing is sent by us. If Swiggy can't prepare one, the user still gets the
// technical details as text they can paste into Swiggy's own Help.
export function ReportProblem({ input, label = 'Report a problem', product = 'instamart' }: ReportProblemProps) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' });
  const [notes, setNotes] = useState('');
  const [copied, setCopied] = useState(false);

  const prepare = async () => {
    setPhase({ kind: 'busy' });
    const full: ReportInput = { ...input, ...(notes.trim() ? { notes: notes.trim() } : {}) };
    try {
      const { report } = await (product === 'food' ? foodReport(full) : instamartReport(full));
      setPhase({ kind: 'ready', report });
    } catch {
      setPhase({ kind: 'unavailable', text: localReportText(full, product === 'food' ? 'Food' : 'Instamart') });
    }
  };

  const doCopy = async (text: string) => {
    setCopied(await copy(text));
    setTimeout(() => setCopied(false), 2500);
  };

  if (phase.kind === 'idle') {
    return <button type="button" className={`${styles.linkBtn} ${styles.reportLink}`} onClick={() => setPhase({ kind: 'form' })}>{label}</button>;
  }

  return (
    <div className={styles.reportBox} role="group" aria-label="Report a problem">
      {(phase.kind === 'form' || phase.kind === 'busy') && (
        <>
          <p className={styles.meta}>Swiggy will prepare a report with the technical details. Nothing is sent until you send the email yourself.</p>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Anything to add? (optional)</span>
            <textarea className={styles.input} rows={3} maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)} disabled={phase.kind === 'busy'} />
          </label>
          <button type="button" className={styles.primary} style={{ marginTop: 4 }} disabled={phase.kind === 'busy'} onClick={prepare}>
            {phase.kind === 'busy' ? 'Preparing…' : 'Prepare report'}
          </button>
          <button type="button" className={styles.secondary} disabled={phase.kind === 'busy'} onClick={() => setPhase({ kind: 'idle' })}>Cancel</button>
        </>
      )}

      {phase.kind === 'ready' && (
        <>
          <p className={styles.meta}>Your report is ready. Sending it opens your email app with the details filled in.</p>
          {phase.report.mailto && (
            <a className={styles.primary} style={{ display: 'block', textAlign: 'center', textDecoration: 'none', marginTop: 4 }} href={phase.report.mailto}>
              <Mail style={{ width: 16, height: 16, verticalAlign: '-3px' }} aria-hidden /> Email the Swiggy team
            </a>
          )}
          {phase.report.body && (
            <button type="button" className={styles.secondary} onClick={() => doCopy([phase.report.subject, phase.report.body].filter(Boolean).join('\n\n'))}>
              {copied ? 'Copied' : 'Copy report text'}
            </button>
          )}
        </>
      )}

      {phase.kind === 'unavailable' && (
        <>
          <p className={styles.meta}>Swiggy&apos;s reporting isn&apos;t available right now. Copy these details and share them through Help in the Swiggy app.</p>
          <pre className={styles.reportText}>{phase.text}</pre>
          <button type="button" className={styles.secondary} onClick={() => doCopy(phase.text)}>{copied ? 'Copied' : 'Copy details'}</button>
        </>
      )}
    </div>
  );
}
