'use client';

import { useState, type ReactNode } from 'react';
import { Minus, Plus, Star } from 'lucide-react';
import { formatInr, type FoodResult } from '@/lib/food';
import { pickProblem, type Picks } from '@/lib/foodSelection';
import { askGate, cancelGate, confirmGate, type Gate } from '@/lib/loadGate';
import { Icon } from '@/components/ui/Icon';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

const Thumb = ({ url }: { url: string | null }) => (
  <ProductThumb url={url} className={styles.thumb} fallbackClassName={styles.thumbFallback} size="md" />
);

export function VegMark({ isVeg }: { isVeg: boolean | null }) {
  if (isVeg === null) return null;
  return <span className={`${styles.vegDot} ${isVeg ? styles.vegOn : styles.vegOff}`} role="img" aria-label={isVeg ? 'Vegetarian' : 'Non-vegetarian'} />;
}

// Was a plain `★ ${rating}` string joined with the rest — the icon audit found this duplicating the Star icon
// already used elsewhere (MealSuggestionsSection's "Recommended"), so the rating segment is now real JSX and the
// whole thing returns parts to render, not a string to join.
function restaurantMeta(r: FoodResult['restaurant']): ReactNode[] {
  const eta = r.etaRange ?? (r.etaMinutes !== null ? `${r.etaMinutes} mins` : null);
  const distance = r.distanceKm !== null ? `${r.distanceKm} km` : null;
  const rating = r.rating !== null ? <span key="rating"><Icon icon={Star} size="xs" /> {r.rating}</span> : null;
  const parts = [rating, eta, distance, r.costForTwo].filter((p): p is NonNullable<typeof p> => p !== null);
  return parts.flatMap((part, i) => (i === 0 ? [part] : [<span key={`sep-${i}`}> · </span>, part]));
}

interface CardProps {
  result: FoodResult;
  picks: Picks | null;
  onOpen: () => void;
  /** Some dish's options are being fetched: one at a time, since each is a cart round-trip. */
  loadingOptions: boolean;
  loadingThis: boolean;
  /** Loading options empties the user's Swiggy cart, so it asks first (see lib/loadGate.ts). */
  confirming: boolean;
  onAsk: () => void;
  onCancelAsk: () => void;
  onConfirm: () => void;
  onClose: () => void;
  onVariant: (groupId: string, optionId: string) => void;
  onAddon: (groupId: string, addonId: string, max: number | null) => void;
  onQuantity: (quantity: number) => void;
}

function DishCard({ result, picks, onOpen, loadingOptions, loadingThis, confirming, onAsk, onCancelAsk, onConfirm, onClose, onVariant, onAddon, onQuantity }: CardProps) {
  const { customization: c, restaurant: r } = result;
  const problem = picks ? pickProblem(result, picks) : null;
  const blocked = !result.available || !c.supported;
  const meta = restaurantMeta(r);
  return (
    <section className={styles.row} data-dish={result.menuItemId}>
      <div className={styles.picked}>
        <Thumb url={result.imageUrl} />
        <div className={styles.info}>
          <div className={styles.dishTitle}>
            <VegMark isVeg={result.isVeg} />
            <p className={styles.name}>{result.name}</p>
          </div>
          <p className={styles.meta}>{r.name}{r.area ? ` · ${r.area}` : ''}</p>
          {meta.length > 0 && <p className={styles.meta}>{meta}</p>}
          {result.price !== null && <p className={styles.price}>{formatInr(result.price)}{c.variantGroups.length > 0 ? ' onwards' : ''}</p>}
        </div>
      </div>
      {r.offer && <p className={styles.actions}><span className={`${styles.chip} ${styles.chipLive}`}>{r.offer}</span></p>}

      {picks ? (
        <div className={styles.customize}>
          {c.variantGroups.map(group => (
            <div key={group.groupId} role="radiogroup" aria-label={group.name}>
              <p className={styles.sectionLabel}>{group.name}</p>
              <ul className={styles.options}>
                {group.options.map(o => (
                  <li key={o.id}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={picks.variants[group.groupId] === o.id}
                      className={`${styles.option} ${picks.variants[group.groupId] === o.id ? styles.on : ''}`}
                      disabled={!o.available}
                      onClick={() => onVariant(group.groupId, o.id)}
                    >
                      <span className={styles.optionName}>{o.name}</span>
                      {!o.available ? <span className={`${styles.optionPrice} ${styles.oos}`}>Out of stock</span> : o.price !== null && <span className={styles.optionPrice}>{formatInr(o.price)}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {c.addonGroups.map(group => {
            const chosen = picks.addons[group.groupId] ?? [];
            const hint = [group.min > 0 ? `choose at least ${group.min}` : 'optional', group.max !== null ? `up to ${group.max}` : null].filter(Boolean).join(', ');
            return (
              <div key={group.groupId} role="group" aria-label={group.name}>
                <p className={styles.sectionLabel}>{group.name} <span style={{ textTransform: 'none', letterSpacing: 0 }}>({hint})</span></p>
                <ul className={styles.options}>
                  {group.choices.map(a => {
                    const on = chosen.includes(a.id);
                    return (
                      <li key={a.id}>
                        <button
                          type="button"
                          aria-pressed={on}
                          className={`${styles.option} ${on ? styles.on : ''}`}
                          disabled={!a.available || (!on && group.max !== null && chosen.length >= group.max)}
                          onClick={() => onAddon(group.groupId, a.id, group.max)}
                        >
                          <span className={styles.optionName}>{a.name}</span>
                          {!a.available ? <span className={`${styles.optionPrice} ${styles.oos}`}>Out of stock</span> : a.price !== null && a.price > 0 && <span className={styles.optionPrice}>+{formatInr(a.price)}</span>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
          {c.addonsUnavailable && <p className={styles.notice}>Add-ons for this dish can&apos;t be ordered here yet, so you&apos;ll get it as listed.</p>}
          <div className={styles.qtyRow}>
            <span className={styles.qtyLabel}>Quantity</span>
            <div className={styles.stepper}>
              <button type="button" aria-label="Decrease quantity" disabled={picks.quantity <= 1} onClick={() => onQuantity(picks.quantity - 1)}><Icon icon={Minus} size="xs" /></button>
              <span aria-live="polite">{picks.quantity}</span>
              <button type="button" aria-label="Increase quantity" disabled={picks.quantity >= 20} onClick={() => onQuantity(picks.quantity + 1)}><Icon icon={Plus} size="xs" /></button>
            </div>
          </div>
          {problem && <p className={styles.notice} style={{ marginTop: 12 }}>{problem}</p>}
          <div className={styles.actions}>
            <button type="button" className={`${styles.linkBtn} ${styles.muted}`} onClick={onClose}>Choose a different dish</button>
          </div>
        </div>
      ) : (
        <div className={styles.actions}>
          {!result.available ? (
            <span className={styles.oos}>Out of stock</span>
          ) : c.optionsOnDemand && confirming && !loadingOptions ? (
            <div className={styles.confirmDelete} style={{ maxWidth: 'none', alignItems: 'flex-start' }}>
              <p className={styles.couponWhy} role="alert">Checking this dish&apos;s add-ons will clear your current Swiggy cart. Continue?</p>
              <button type="button" className={styles.dangerBtn} onClick={onConfirm}>Clear cart &amp; continue</button>
              <button type="button" className={styles.linkBtn} onClick={onCancelAsk}>Cancel</button>
            </div>
          ) : c.optionsOnDemand ? (
            <button type="button" className={styles.linkBtn} disabled={loadingOptions} aria-busy={loadingThis} onClick={onAsk}>
              {loadingThis ? 'Checking add-ons…' : 'Choose this'}
            </button>
          ) : !c.supported ? (
            <span className={styles.skipped}>Needs options we can&apos;t set here. Order it in the Swiggy app.</span>
          ) : (
            <button type="button" className={styles.linkBtn} disabled={blocked} onClick={onOpen}>
              {c.variantGroups.length > 0 || c.addonGroups.length > 0 ? 'Choose & customize' : 'Choose this'}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

interface PickerProps {
  results: FoodResult[];
  openId: string | null;
  picks: Picks | null;
  onOpen: (result: FoodResult) => void;
  onLoadOptions: (result: FoodResult) => void;
  loadingOptionsId: string | null;
  onClose: () => void;
  onVariant: (groupId: string, optionId: string) => void;
  onAddon: (groupId: string, addonId: string, max: number | null) => void;
  onQuantity: (quantity: number) => void;
}

/** Real matching dishes near the address. While one is being customized, only that dish is shown. */
export function FoodPicker({ results, openId, picks, onOpen, onLoadOptions, loadingOptionsId, onClose, onVariant, onAddon, onQuantity }: PickerProps) {
  const [gate, setGate] = useState<Gate>(null);
  if (results.length === 0) {
    return <p className={styles.none}>No matching dishes are available near this address right now. Try another address, or order the ingredients instead.</p>;
  }
  const shown = openId ? results.filter(r => r.menuItemId === openId) : results;
  return (
    <div className={styles.list}>
      {shown.map(result => (
        <DishCard
          key={result.menuItemId}
          result={result}
          picks={result.menuItemId === openId ? picks : null}
          onOpen={() => onOpen(result)}
          confirming={gate === result.menuItemId}
          onAsk={() => setGate(g => askGate(g, result.menuItemId))}
          onCancelAsk={() => setGate(cancelGate())}
          onConfirm={() => setGate(confirmGate(gate, result.menuItemId, () => onLoadOptions(result)))} // not inside an updater: those run twice in StrictMode
          loadingOptions={loadingOptionsId !== null}
          loadingThis={loadingOptionsId === result.menuItemId}
          onClose={onClose}
          onVariant={onVariant}
          onAddon={onAddon}
          onQuantity={onQuantity}
        />
      ))}
    </div>
  );
}
