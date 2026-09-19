'use client';
import { useEffect, useSyncExternalStore } from 'react';
import { getAuthState, getServerAuthState, loadAuth, subscribeAuth } from '@/lib/auth';

// Checked on mount — which is also the moment the user lands back from the
// full-page Swiggy OAuth redirect, so the real result drives the UI instead
// of only being inferred from a failed order.
export function useAuth() {
  const state = useSyncExternalStore(subscribeAuth, getAuthState, getServerAuthState);
  useEffect(() => { void loadAuth(); }, []);
  return state;
}
