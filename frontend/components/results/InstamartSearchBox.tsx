'use client';

import { useRef, useState, type FormEvent } from 'react';
import { Search, X } from 'lucide-react';
import { formatInr, type InstamartSearchResult } from '@/lib/instamart';
import { searchBoxCacheFor } from '@/lib/instamartSearch';
import { keyOf } from '@/lib/searchCache';
import { rowsFrom, toCartResult } from '@/lib/instamartSearchRows';
import { ProductThumb } from './ProductThumb';
import styles from './instamart.module.css';

const MIN_QUERY = 2;

type Status = 'idle' | 'loading' | 'ready' | 'error';

interface SearchBoxProps {
  /** The delivery address the sheet is using: price and stock depend on it. The sheet keys this component on it, so a
   *  different address remounts it with nothing left over from the last one. */
  addressId: string;
  /** Variations currently chosen in the order (a row for one of them reads "Added"). */
  addedSpinIds: ReadonlySet<string>;
  /** Names the sheet already uses for its items (each added item needs a unique one). */
  takenLabels: ReadonlySet<string>;
  /** The sheet's own add path (`addProduct`): the item joins the selection and the cart is built later, at "Review cart". */
  onAdd: (result: InstamartSearchResult) => void;
}

function errorText(e: unknown): string {
  const code = typeof e === 'object' && e !== null ? (e as { code?: unknown }).code : undefined;
  if (code === 'auth_required') return 'Your Swiggy session expired. Reconnect and try again.';
  const message = e instanceof Error ? e.message : '';
  return message && message.length < 160 ? message : "Couldn't search Instamart right now.";
}

/** Free-text product search for the picking screen. Submit-only (a search is a real Swiggy call). Adding a result reuses the
 *  sheet's existing add path, so nothing here touches the cart. */
export function InstamartSearchBox({ addressId, addedSpinIds, takenLabels, onAdd }: SearchBoxProps) {
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [result, setResult] = useState<InstamartSearchResult | null>(null);
  const [searched, setSearched] = useState('');
  const [message, setMessage] = useState('');
  const run = useRef(0);

  const trimmed = query.trim();

  const search = async (text: string) => {
    const id = ++run.current;
    setStatus('loading');
    setSearched(text);
    const { entries, error } = await searchBoxCacheFor(addressId).ensure([text]);
    if (run.current !== id) return; // superseded by a newer search, a clear, or an address change
    const entry = entries.get(keyOf(text));
    if (entry?.status === 'ready' && entry.result) {
      setResult(entry.result);
      setStatus('ready');
    } else {
      setMessage(errorText(error));
      setStatus('error');
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (trimmed.length >= MIN_QUERY && status !== 'loading') void search(trimmed);
  };

  const clear = () => {
    run.current++;
    setQuery('');
    setStatus('idle');
    setResult(null);
    setSearched('');
  };

  const rows = status === 'ready' ? rowsFrom(result, addedSpinIds, takenLabels) : [];

  return (
    <section aria-label="Search Instamart" className={styles.searchBox}>
      <p className={styles.sectionLabel}>Looking for something else?</p>
      <form className={styles.searchField} onSubmit={submit} role="search">
        <Search className={styles.searchIcon} aria-hidden="true" />
        <input
          type="search"
          className={styles.searchInput}
          value={query}
          maxLength={80}
          enterKeyHint="search"
          placeholder="Search Instamart"
          aria-label="Search Instamart products"
          onChange={e => setQuery(e.target.value)}
        />
        {query && (
          <button type="button" className={styles.searchClear} onClick={clear} aria-label="Clear search"><X /></button>
        )}
        <button type="submit" className={styles.searchGo} disabled={trimmed.length < MIN_QUERY || status === 'loading'} aria-label="Search">
          Search
        </button>
      </form>

      {status === 'loading' && (
        <div className={`${styles.usualRow} ${styles.searchCards}`} aria-busy="true" aria-label={`Searching for ${searched}`}>
          {[0, 1, 2].map(i => <div key={i} className={styles.searchSkelCard} />)}
        </div>
      )}

      {status === 'error' && (
        <div className={styles.searchNote} role="alert">
          <p>{message}</p>
          <button type="button" className={styles.linkBtn} onClick={() => void search(searched)}>Try again</button>
        </div>
      )}

      {status === 'ready' && rows.length === 0 && (
        <p className={styles.searchNote} role="status">
          {result?.note ?? 'No match on Instamart'} for &ldquo;{searched}&rdquo;. Try a different word.
        </p>
      )}

      {status === 'ready' && rows.length > 0 && (
        <ul className={`${styles.usualRow} ${styles.searchCards}`} aria-label={`Results for ${searched}`}>
          {rows.map(row => {
            const { option } = row;
            const discounted = option.price !== null && option.mrp !== null && option.mrp > option.price;
            return (
              <li key={option.spinId} className={`${styles.usualCard} ${!option.available ? styles.searchCardOff : ''}`}>
                <ProductThumb url={option.imageUrl} className={styles.usualThumb} fallbackClassName={styles.usualThumbFallback} />
                <p className={styles.usualName}>{option.name}</p>
                {option.size && <p className={styles.meta}>{option.size}</p>}
                {option.price !== null && (
                  <p className={styles.price}>
                    {formatInr(option.price)}
                    {discounted && <span className={styles.mrp}>{formatInr(option.mrp)}</span>}
                  </p>
                )}
                {!option.available ? (
                  <span className={styles.oos}>Out of stock</span>
                ) : (
                  <button
                    type="button"
                    className={styles.couponBtn}
                    disabled={!row.canAdd}
                    onClick={() => onAdd(toCartResult(row))}
                    aria-label={`${row.added ? 'Added' : 'Add'} ${[option.name, option.size].filter(Boolean).join(' ')}`}
                  >
                    {row.added ? '✓ Added' : '+ Add'}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
