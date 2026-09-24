'use client';

// Internal-only, unlinked preview of the Phase 1 base components (components/ui/*) — not part of any user flow, not
// linked from nav. A living reference while later phases adopt these into real screens; safe to delete once that's
// done, or to keep as an ongoing style guide.
import { useState } from 'react';
import { Package, ShoppingCart } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Icon, type IconSize } from '@/components/ui/Icon';
import { Sheet } from '@/components/ui/Sheet';

const ICON_SIZES: IconSize[] = ['xs', 'sm', 'md', 'lg', 'xl'];

export default function DesignSystemPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  return (
    <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 32, maxWidth: 480, margin: '0 auto' }}>
      <section>
        <h2 style={{ marginBottom: 12 }}>Icons</h2>
        {/* data-icon-size on each swatch is a hook for the browser check to read getComputedStyle width/height
            precisely per size, rather than eyeballing it — see the icon audit's sizing-bug finding. */}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 20 }}>
          {ICON_SIZES.map(size => (
            <div key={size} data-icon-size={size} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <Icon icon={ShoppingCart} size={size} aria-label={`${size} icon`} />
              <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{size}</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: 12 }}>Buttons</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="primary" icon={<Package size={18} />}>With icon</Button>
          <Button variant="primary" loading={loading} onClick={() => setLoading(l => !l)}>Toggle loading</Button>
          <Button variant="primary" disabled>Disabled</Button>
          <Button variant="ghost" fullWidth={false}>Ghost / inline</Button>
          <Button variant="primary" size="sm" fullWidth={false}>Small</Button>
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: 12 }}>Cards</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>Default (bordered, md padding)</Card>
          <Card elevated>Elevated (shadow, no border)</Card>
          <Card padding="sm">Small padding</Card>
          <Card padding="lg">Large padding</Card>
        </div>
      </section>

      <section>
        <h2 style={{ marginBottom: 12 }}>Sheet</h2>
        <Button variant="primary" fullWidth={false} onClick={() => setSheetOpen(true)}>Open sheet</Button>
        <Sheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          ariaLabel="Preview sheet"
          title="Sheet title"
          subtitle="Subtitle text describing the sheet"
        >
          <p style={{ marginBottom: 16 }}>Body content goes here. Swipe down, tap the backdrop, or press Escape to close.</p>
          <Button variant="primary" onClick={() => setSheetOpen(false)}>Primary action</Button>
        </Sheet>
      </section>
    </div>
  );
}
