'use client';

import { useState } from 'react';
import { setSelectedAddressId } from '@/lib/addressStore';
import { useAddresses } from '@/hooks/useInstamartAddresses';
import { AddressForm } from './AddressForm';
import styles from './instamart.module.css';

interface AddressPickerProps {
  /** The address the current search/cart is for. */
  currentId: string | null;
  /** The user picked (or created) an address; the caller re-runs the search for it. */
  onChoose: (addressId: string | null) => void;
  onBack: () => void;
}

// Choose which saved address to order to, add a new one, or delete one. Only reachable while picking
// items: changing the address restarts the search (price and stock depend on it) and the cart is rebuilt
// from scratch, so the cart/address re-verification at checkout can never be bypassed from here.
export function AddressPicker({ currentId, onChoose, onBack }: AddressPickerProps) {
  const { list, error, busy, create, remove } = useAddresses();
  const [adding, setAdding] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  if (adding) {
    return (
      <AddressForm
        busy={busy}
        error={error}
        onCancel={() => setAdding(false)}
        onSubmit={async (fields, coords) => {
          const id = await create(fields, coords);
          if (id) { setSelectedAddressId(id); onChoose(id); }
        }}
      />
    );
  }

  const choose = (id: string) => { setSelectedAddressId(id); onChoose(id); };
  const doDelete = async (id: string) => {
    const next = await remove(id);
    setConfirmId(null);
    // Deleting the address the search was for: fall back to the account's default and search again.
    if (next && id === currentId) onChoose(next.defaultId);
  };

  return (
    <div>
      <p className={styles.sectionLabel}>Deliver to</p>
      {error && !list && <p className={styles.blocker}>{error}</p>}
      {!list && !error && <div className={styles.skeleton} aria-busy="true" />}
      {list && list.addresses.length === 0 && <p className={styles.none}>No saved addresses yet.</p>}

      <ul className={styles.coupons}>
        {list?.addresses.map(a => (
          <li key={a.id} className={styles.coupon}>
            <label className={`${styles.payOption} ${a.id === currentId ? styles.on : ''}`} style={{ flex: 1 }}>
              <input type="radio" name="instamart-address" checked={a.id === currentId} disabled={busy} onChange={() => choose(a.id)} />
              <span className={styles.payText}>
                <span className={styles.payLabel}>{a.label}</span>
                <span className={styles.meta}>{a.addressLine}</span>
              </span>
            </label>
            {confirmId === a.id ? (
              <div className={styles.confirmDelete}>
                <p className={styles.couponWhy}>Permanently delete this from your Swiggy account? This can’t be undone.</p>
                <button type="button" className={styles.dangerBtn} disabled={busy} onClick={() => doDelete(a.id)}>{busy ? 'Deleting…' : 'Delete'}</button>
                <button type="button" className={styles.linkBtn} disabled={busy} onClick={() => setConfirmId(null)}>Keep</button>
              </div>
            ) : (
              <button type="button" className={`${styles.linkBtn} ${styles.muted}`} disabled={busy} onClick={() => setConfirmId(a.id)} aria-label={`Delete ${a.label} address`}>Delete</button>
            )}
          </li>
        ))}
      </ul>
      {error && list && <p className={styles.blocker}>{error}</p>}

      <button type="button" className={styles.secondary} disabled={busy} onClick={() => setAdding(true)}>Add a new address</button>
      <button type="button" className={styles.linkBtn} style={{ display: 'block', margin: '12px auto 0' }} onClick={onBack}>Back to your items</button>
    </div>
  );
}
