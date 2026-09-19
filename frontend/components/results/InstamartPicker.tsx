'use client';

import { useState } from 'react';
import type { Choice } from '@/hooks/useInstamartOrder';
import { formatInr, type InstamartOption, type InstamartSearchResult } from '@/lib/instamart';
import styles from './instamart.module.css';

const MAX_QTY = 20;

function Thumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return <div className={styles.thumbFallback} aria-hidden>🛒</div>;
  // eslint-disable-next-line @next/next/no-img-element
  return <img className={styles.thumb} src={url} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
}

function Price({ option }: { option: InstamartOption }) {
  if (option.price === null) return null;
  const discounted = option.mrp !== null && option.mrp > option.price;
  return (
    <p className={styles.price}>
      {formatInr(option.price)}
      {discounted && <span className={styles.mrp}>{formatInr(option.mrp)}</span>}
    </p>
  );
}

function OptionSummary({ option }: { option: InstamartOption }) {
  const meta = [option.brand, option.size].filter(Boolean).join(' · ');
  return (
    <div className={styles.info}>
      <p className={styles.name}>{option.name}</p>
      {meta && <p className={styles.meta}>{meta}</p>}
      <Price option={option} />
    </div>
  );
}

interface RowProps {
  result: InstamartSearchResult;
  choice: Choice;
  removable: boolean;
  onPick: (spinId: string | null) => void;
  onQuantity: (quantity: number) => void;
  onRemove: () => void;
}

function IngredientRow({ result, choice, removable, onPick, onQuantity, onRemove }: RowProps) {
  const [open, setOpen] = useState(false);
  const selected = result.options.find(o => o.spinId === choice.spinId) ?? null;
  const topAvailable = result.options.find(o => o.available) ?? null;
  const maxQty = Math.min(selected?.maxQuantity ?? 10, MAX_QTY);

  return (
    <section className={styles.row}>
      <div className={styles.rowHead}>
        <span className={styles.ingredient}>{result.ingredient}</span>
        {removable && <button type="button" className={`${styles.linkBtn} ${styles.muted}`} onClick={onRemove}>Remove</button>}
      </div>

      {selected ? (
        <div className={styles.picked}>
          <Thumb url={selected.imageUrl} />
          <OptionSummary option={selected} />
          <div className={styles.stepper}>
            <button type="button" aria-label="Decrease quantity" disabled={choice.quantity <= 1} onClick={() => onQuantity(choice.quantity - 1)}>−</button>
            <span aria-live="polite">{choice.quantity}</span>
            <button type="button" aria-label="Increase quantity" disabled={choice.quantity >= maxQty} onClick={() => onQuantity(choice.quantity + 1)}>+</button>
          </div>
        </div>
      ) : (
        <p className={styles.skipped}>{result.note ?? 'Skipped — not in this order'}</p>
      )}

      <div className={styles.actions}>
        {result.options.length > 0 && (
          <button type="button" className={styles.linkBtn} onClick={() => setOpen(o => !o)} aria-expanded={open}>
            {open ? 'Hide options' : `See ${result.options.length} option${result.options.length === 1 ? '' : 's'}`}
          </button>
        )}
        {selected ? (
          <button type="button" className={`${styles.linkBtn} ${styles.muted}`} onClick={() => onPick(null)}>Skip</button>
        ) : topAvailable ? (
          <button type="button" className={styles.linkBtn} onClick={() => onPick(topAvailable.spinId)}>Add back</button>
        ) : null}
      </div>

      {open && (
        <ul className={styles.options}>
          {result.options.map(o => (
            <li key={o.spinId}>
              <button
                type="button"
                className={`${styles.option} ${o.spinId === choice.spinId ? styles.on : ''}`}
                disabled={!o.available}
                onClick={() => { onPick(o.spinId); setOpen(false); }}
              >
                <Thumb url={o.imageUrl} />
                <OptionSummary option={o} />
                {!o.available && <span className={styles.oos}>Out of stock</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface PickerProps {
  results: InstamartSearchResult[];
  choices: Record<string, Choice>;
  /** Ingredient names added via the add-on cards (removable here). */
  extras: ReadonlySet<string>;
  onPick: (ingredient: string, spinId: string | null) => void;
  onQuantity: (ingredient: string, quantity: number) => void;
  onRemoveExtra: (ingredient: string) => void;
}

export function InstamartPicker({ results, choices, extras, onPick, onQuantity, onRemoveExtra }: PickerProps) {
  if (results.length === 0) {
    return <p className={styles.none}>Nothing is missing from your recipe — add extras below if you like.</p>;
  }
  return (
    <div className={styles.list}>
      {results.map(result => (
        <IngredientRow
          key={result.ingredient}
          result={result}
          choice={choices[result.ingredient] ?? { spinId: null, quantity: 1 }}
          removable={extras.has(result.ingredient)}
          onPick={spinId => onPick(result.ingredient, spinId)}
          onQuantity={q => onQuantity(result.ingredient, q)}
          onRemove={() => onRemoveExtra(result.ingredient)}
        />
      ))}
    </div>
  );
}

/** Rough basket value while picking; the real total (with fees) comes from Swiggy at review. */
export function estimateSubtotal(results: InstamartSearchResult[], choices: Record<string, Choice>): { count: number; amount: number } {
  return results.reduce(
    (acc, r) => {
      const choice = choices[r.ingredient];
      const option = r.options.find(o => o.spinId === choice?.spinId);
      if (!option || !choice) return acc;
      return { count: acc.count + 1, amount: acc.amount + (option.price ?? 0) * choice.quantity };
    },
    { count: 0, amount: 0 },
  );
}
