'use client';
import { useCallback, useEffect, useState } from 'react';
import {
  FoodApiError,
  foodOrderDetails,
  foodOrders,
  foodOrderStatus,
  type DeliveryStatus,
  type FoodOrderDetails,
  type FoodOrderRow,
  type FoodTracking,
  type InstamartAddress,
} from '../lib/food';
import { startLivePoll } from '../lib/livePoll';

const message = (e: unknown) => (e instanceof FoodApiError ? e.message : "Couldn't reach the server. Check your connection and try again.");

interface Loaded { key: string; address: InstamartAddress | null; orders: FoodOrderRow[] | null; error: string | null }

/** Recent Food orders for one address (newest first from Swiggy). While `waitFor` isn't in the list yet (an order
 *  placed seconds ago may lag get_food_orders) it retries a few times. */
export function useFoodOrderList(open: boolean, addressId: string | null, waitFor: string | null) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [nonce, setNonce] = useState(0);
  const key = `${addressId ?? ''}|${nonce}`;

  useEffect(() => {
    if (!open) return;
    let alive = true;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Cancels the in-flight request on cleanup, so a quick re-open (or a request superseded by a newer one)
    // doesn't keep running in the background and doesn't count as a second call against Swiggy's rate limit.
    const controller = new AbortController();
    const load = async () => {
      try {
        const { address, orders } = await foodOrders(addressId, false, controller.signal);
        if (!alive) return;
        setLoaded({ key, address, orders, error: null });
        if (waitFor && !orders.some(o => o.orderId === waitFor) && ++attempts < 4) timer = setTimeout(load, 4000);
      } catch (e) {
        if ((e as { name?: string })?.name === 'AbortError') return;
        if (alive) setLoaded({ key, address: null, orders: null, error: message(e) });
      }
    };
    void load();
    return () => { alive = false; controller.abort(); if (timer) clearTimeout(timer); };
  }, [open, addressId, waitFor, key]);

  const reload = useCallback(() => setNonce(n => n + 1), []);
  const current = loaded?.key === key ? loaded : null;
  return { orders: current?.orders ?? null, address: current?.address ?? null, error: current?.error ?? null, loading: current === null, reload };
}

/** Polls live delivery status at the interval Swiggy asks for (never faster). Only active orders are polled; it stops
 *  when the order is delivered/cancelled, the sheet closes, or after repeated failures. No coordinates are needed. */
export function useFoodLiveStatus(order: FoodOrderRow | null) {
  const orderId = order?.orderId ?? null;
  const live = !!order?.active;
  const [snap, setSnap] = useState<{ orderId: string; delivery: DeliveryStatus | null; tracking: FoodTracking | null; notes: string[]; failed: boolean } | null>(null);

  useEffect(() => {
    if (!orderId || !live) return;
    return startLivePoll({
      fetch: () => foodOrderStatus(orderId),
      onResult: ({ delivery, tracking, notes }) => setSnap({ orderId, delivery, tracking, notes, failed: false }),
      nextWaitSec: ({ delivery, tracking }) => (delivery?.terminal || (!delivery && !tracking) ? null : delivery?.pollIntervalSec ?? 30),
      onGiveUp: () => setSnap(s => ({ orderId, delivery: s?.delivery ?? null, tracking: s?.tracking ?? null, notes: [], failed: true })),
    });
  }, [orderId, live]);

  const current = snap?.orderId === orderId ? snap : null;
  return { delivery: current?.delivery ?? null, tracking: current?.tracking ?? null, notes: current?.notes ?? [], failed: current?.failed ?? false };
}

/** Itemized details for one order (fetched once). `available: false` when Swiggy doesn't return them. */
export function useFoodOrderDetails(orderId: string | null) {
  const [loaded, setLoaded] = useState<{ orderId: string; details: FoodOrderDetails | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!orderId) return;
    let alive = true;
    foodOrderDetails(orderId)
      .then(({ details }) => alive && setLoaded({ orderId, details, error: null }))
      .catch(e => alive && setLoaded({ orderId, details: null, error: message(e) }));
    return () => { alive = false; };
  }, [orderId]);
  const current = loaded?.orderId === orderId ? loaded : null;
  return { details: current?.details ?? null, error: current?.error ?? null, loading: !!orderId && current === null };
}
