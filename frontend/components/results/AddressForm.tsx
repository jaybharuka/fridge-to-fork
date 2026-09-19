'use client';

import { LocateFixed } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import type { Coords } from '@/lib/addressStore';
import type { NewAddress } from '@/lib/instamart';
import styles from './instamart.module.css';

const CATEGORIES: { value: NewAddress['address_category']; label: string }[] = [
  { value: 'HOME', label: 'Home' },
  { value: 'WORK', label: 'Work' },
  { value: 'OFFICE', label: 'Office' },
  { value: 'FRIENDS_AND_FAMILY', label: 'Friends & family' },
  { value: 'OTHER', label: 'Other' },
];

interface AddressFormProps {
  busy: boolean;
  /** Server error from the last attempt (Swiggy's own wording). */
  error: string | null;
  onSubmit: (fields: NewAddress, coords: Coords | null) => void;
  onCancel: () => void;
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      {children}
      {hint && <span className={styles.meta}>{hint}</span>}
    </label>
  );
}

/** Add a saved address to the user's Swiggy account. Swiggy needs the account holder's name and phone. */
export function AddressForm({ busy, error, onSubmit, onCancel }: AddressFormProps) {
  const [v, setV] = useState({
    address_tag: '', address_category: 'HOME' as NewAddress['address_category'], full_address: '', address_line: '', address_line2: '',
    locality: '', city: '', postal_code: '', user_name: '', user_phone: '',
  });
  const [coords, setCoords] = useState<Coords | null>(null);
  const [geoMessage, setGeoMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV(prev => ({ ...prev, [k]: e.target.value }));

  const locate = () => {
    setGeoMessage(null);
    if (!navigator.geolocation) return setGeoMessage("This browser can't share its location.");
    navigator.geolocation.getCurrentPosition(
      pos => setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => setGeoMessage('Location wasn’t shared. You can still save the address without it.'),
      { timeout: 10_000 },
    );
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const missing = (['full_address', 'address_line', 'address_line2', 'city', 'user_name'] as const).find(k => !v[k].trim());
    if (missing) return setProblem('Please fill in all the required fields.');
    if (!/^\d{6}$/.test(v.postal_code.trim())) return setProblem('Enter a 6-digit PIN code.');
    if (!/^\+?\d{10,15}$/.test(v.user_phone.trim())) return setProblem('Enter a valid phone number (10–15 digits).');
    setProblem(null);
    const fields: NewAddress = {
      full_address: v.full_address.trim(), address_line: v.address_line.trim(), address_line2: v.address_line2.trim(),
      city: v.city.trim(), postal_code: v.postal_code.trim(), address_category: v.address_category,
      user_name: v.user_name.trim(), user_phone: v.user_phone.trim(),
      ...(v.locality.trim() ? { locality: v.locality.trim() } : {}),
      ...(v.address_tag.trim() ? { address_tag: v.address_tag.trim() } : {}),
      ...(coords ? { latitude: coords.lat, longitude: coords.lng } : {}),
    };
    onSubmit(fields, coords);
  };

  return (
    <form onSubmit={submit} className={styles.form} noValidate>
      <Field label="Save as">
        <select className={styles.input} value={v.address_category} onChange={set('address_category')}>
          {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </Field>
      <Field label="Label (optional)"><input className={styles.input} value={v.address_tag} onChange={set('address_tag')} maxLength={60} placeholder="e.g. Mum's place" /></Field>
      <Field label="Full address"><textarea className={styles.input} rows={2} value={v.full_address} onChange={set('full_address')} maxLength={200} autoComplete="street-address" /></Field>
      <Field label="House / building"><input className={styles.input} value={v.address_line} onChange={set('address_line')} maxLength={200} /></Field>
      <Field label="Apartment, floor, wing"><input className={styles.input} value={v.address_line2} onChange={set('address_line2')} maxLength={200} /></Field>
      <Field label="Area / locality (optional)"><input className={styles.input} value={v.locality} onChange={set('locality')} maxLength={200} /></Field>
      <div className={styles.fieldRow}>
        <Field label="City"><input className={styles.input} value={v.city} onChange={set('city')} maxLength={80} autoComplete="address-level2" /></Field>
        <Field label="PIN code"><input className={styles.input} value={v.postal_code} onChange={set('postal_code')} inputMode="numeric" maxLength={6} autoComplete="postal-code" /></Field>
      </div>
      <Field label="Your name" hint="Swiggy needs the account holder's details."><input className={styles.input} value={v.user_name} onChange={set('user_name')} maxLength={80} autoComplete="name" /></Field>
      <Field label="Your phone"><input className={styles.input} value={v.user_phone} onChange={set('user_phone')} inputMode="tel" maxLength={16} autoComplete="tel" /></Field>

      <div className={styles.geo}>
        <button type="button" className={styles.linkBtn} onClick={locate}><LocateFixed style={{ width: 14, height: 14, verticalAlign: '-2px' }} /> {coords ? 'Location captured' : 'Use my current location'}</button>
        <span className={styles.meta}>
          {coords
            ? 'Saved on this device only, to show the rider on the map while tracking. Only use it if you’re at this address right now.'
            : 'Optional. Only use it if you’re at this address right now — it lets us show the rider on the map while tracking.'}
        </span>
        {geoMessage && <span className={styles.couponWhy}>{geoMessage}</span>}
      </div>

      {(problem || error) && <p className={styles.blocker}>{problem ?? error}</p>}
      <button type="submit" className={styles.primary} disabled={busy}>{busy ? 'Saving…' : 'Save address'}</button>
      <button type="button" className={styles.secondary} disabled={busy} onClick={onCancel}>Cancel</button>
    </form>
  );
}
