'use client';

import { formatInr, type FoodResult } from '@/lib/food';
import { pickProblem, type Picks } from '@/lib/foodSelection';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

const Thumb = ({ url }: { url: string | null }) => (
  <ProductThumb url={url} className={styles.thumb} fallbackClassName={styles.thumbFallback} />
);

export function VegMark({ isVeg }: { isVeg: boolean | null }) {
  if (isVeg === null) return null;
  return <span className={`${styles.vegDot} ${isVeg ? styles.vegOn : styles.vegOff}`} role="img" aria-label={isVeg ? 'Vegetarian' : 'Non-vegetarian'} />;
}

function restaurantMeta(r: FoodResult['restaurant']): string {
  const eta = r.etaRange ?? (r.etaMinutes !== null ? `${r.etaMinutes} mins` : null);
  const distance = r.distanceKm !== null ? `${r.distanceKm} km` : null;
  return [r.rating !== null ? `★ ${r.rating}` : null, eta, distance, r.costForTwo].filter(Boolean).join(' · ');
}

interface CardProps {
  result: FoodResult;
  picks: Picks | null;
  onOpen: () => void;
  onClose: () => void;
  onVariant: (groupId: string, optionId: string) => void;
  onAddon: (groupId: string, addonId: string, max: number | null) => void;
  onQuantity: (quantity: number) => void;
}

function DishCard({ result, picks, onOpen, onClose, onVariant, onAddon, onQuantity }: CardProps) {
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
          {meta && <p className={styles.meta}>{meta}</p>}
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
                          disabled={!on && group.max !== null && chosen.length >= group.max}
                          onClick={() => onAddon(group.groupId, a.id, group.max)}
                        >
                          <span className={styles.optionName}>{a.name}</span>
                          {a.price !== null && a.price > 0 && <span className={styles.optionPrice}>+{formatInr(a.price)}</span>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
          <div className={styles.qtyRow}>
            <span className={styles.qtyLabel}>Quantity</span>
            <div className={styles.stepper}>
              <button type="button" aria-label="Decrease quantity" disabled={picks.quantity <= 1} onClick={() => onQuantity(picks.quantity - 1)}>−</button>
              <span aria-live="polite">{picks.quantity}</span>
              <button type="button" aria-label="Increase quantity" disabled={picks.quantity >= 20} onClick={() => onQuantity(picks.quantity + 1)}>+</button>
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
          ) : !c.supported ? (
            <span className={styles.skipped}>Needs options we can&apos;t set here — order it in the Swiggy app.</span>
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
  onClose: () => void;
  onVariant: (groupId: string, optionId: string) => void;
  onAddon: (groupId: string, addonId: string, max: number | null) => void;
  onQuantity: (quantity: number) => void;
}

/** Real matching dishes near the address. While one is being customized, only that dish is shown. */
export function FoodPicker({ results, openId, picks, onOpen, onClose, onVariant, onAddon, onQuantity }: PickerProps) {
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
          onClose={onClose}
          onVariant={onVariant}
          onAddon={onAddon}
          onQuantity={onQuantity}
        />
      ))}
    </div>
  );
}
