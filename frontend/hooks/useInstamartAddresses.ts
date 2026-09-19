'use client';
import { useCallback, useEffect, useState } from 'react';
import {
  InstamartApiError,
  instamartAddresses,
  instamartCreateAddress,
  instamartDeleteAddress,
  instamartGoToItems,
  type AddressList,
  type InstamartSearchResult,
  type NewAddress,
} from '../lib/instamart';
import { forgetAddress, rememberCoords, type Coords } from '../lib/addressStore';

const message = (e: unknown) =>
  e instanceof InstamartApiError ? e.message : "Couldn't reach the server. Check your connection and try again.";

interface AddressState { list: AddressList | null; error: string | null; busy: boolean }

/** The user's saved Swiggy addresses, with create and (permanent) delete. */
export function useAddresses() {
  const [state, setState] = useState<AddressState>({ list: null, error: null, busy: false });

  useEffect(() => {
    let alive = true;
    instamartAddresses()
      .then(list => alive && setState(s => ({ ...s, list, error: null })))
      .catch(e => alive && setState(s => ({ ...s, error: message(e) })));
    return () => { alive = false; };
  }, []);

  /** Returns the new address id, or null on failure (the message lands in `error`). */
  const create = useCallback(async (fields: NewAddress, coords: Coords | null): Promise<string | null> => {
    setState(s => ({ ...s, busy: true, error: null }));
    try {
      const result = await instamartCreateAddress(fields);
      if (coords) rememberCoords(result.addressId, coords); // real coordinates the user chose to share, for live tracking
      setState({ list: result, error: null, busy: false });
      return result.addressId;
    } catch (e) {
      setState(s => ({ ...s, busy: false, error: message(e) }));
      return null;
    }
  }, []);

  /** Permanent on Swiggy's side; the caller confirms with the user first. Returns the refreshed list or null. */
  const remove = useCallback(async (addressId: string): Promise<AddressList | null> => {
    setState(s => ({ ...s, busy: true, error: null }));
    try {
      const list = await instamartDeleteAddress(addressId);
      forgetAddress(addressId);
      setState({ list, error: null, busy: false });
      return list;
    } catch (e) {
      setState(s => ({ ...s, busy: false, error: message(e) }));
      return null;
    }
  }, []);

  return { ...state, create, remove };
}

/** "Your usual items" at an address (real frequently/recently ordered products); empty when unavailable. */
export function useGoToItems(addressId: string | null, enabled: boolean) {
  const [loaded, setLoaded] = useState<{ addressId: string; items: InstamartSearchResult[] } | null>(null);
  useEffect(() => {
    if (!enabled || !addressId) return;
    let alive = true;
    instamartGoToItems(addressId)
      .then(({ results }) => alive && setLoaded({ addressId, items: results }))
      .catch(() => alive && setLoaded({ addressId, items: [] }));
    return () => { alive = false; };
  }, [addressId, enabled]);
  const current = loaded?.addressId === addressId ? loaded : null;
  return { items: current?.items ?? [], loading: enabled && !!addressId && current === null };
}
