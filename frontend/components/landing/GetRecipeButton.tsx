import { Wand2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import styles from './landing.module.css';

interface GetRecipeButtonProps {
  state: 'ready' | 'loading';
  label: string;
  onClick: () => void;
}

// Ported from templates/index.html:1808-1811 (icon/spinner swap: 2751-2764). Phase 2 (2026-09): one of the three
// button systems the audit found — now the shared Button component. The shimmer sweep (a nice existing detail, part
// of the "does motion feel satisfying" bar) is kept as a local, additive overlay (styles.shimmer, ::after in
// landing.module.css) rather than folding it into Button itself — Button already shipped in Phase 1, and a flourish
// specific to this one landing CTA doesn't belong in the shared component every future screen will use.
export function GetRecipeButton({ state, label, onClick }: GetRecipeButtonProps) {
  const ready = state === 'ready';
  return (
    <Button
      variant="primary"
      icon={<Wand2 size={16} />}
      loading={!ready}
      onClick={onClick}
      className={ready ? styles.shimmer : undefined}
    >
      {label}
    </Button>
  );
}
