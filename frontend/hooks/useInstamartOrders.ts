'use client';
import { useCallback, useEffect, useState } from 'react';
import {
  InstamartApiError,
  instamartOrderDetails,
  instamartOrders,
  instamartOrderStatus,
  isPastOrder,
  type DeliveryStatus,
  type TrackingInfo,
  type OrderDetails,
  type OrderSummary,
} from '../lib/instamart';
import { coordsFor } from '../lib/addressStore';
import { startLivePoll } from '../lib/livePoll';

const message = (e: unknown) =>
  e instanceof InstamartApiError ? e.message : "Couldn't reach the server. Check your connection and try again.";

interface Loaded<T> { key: string; data: T | null; error: string | null }

/** Recent Instamart orders (newest first from Swiggy). `reload` refetches. While `waitFor` isn't in the
 *  list yet (an order placed seconds ago may lag get_orders) it retries a few times. */
export function useOrderList(open: boolean, waitFor: string | null) {
  const [loaded, setLoaded] = useState<Loaded<OrderSummary[]> | null>(null);
  const [nonce, setNonce] = useState(0);
  const key = `${nonce}`;

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
        const { orders } = await instamartOrders(false, controller.signal);
        if (!alive) return;
        setLoaded({ key, data: orders, error: null });
        if (waitFor && !orders.some(o => o.orderId === waitFor) && ++attempts < 4) timer = setTimeout(load, 4000);
      } catch (e) {
        if ((e as { name?: string })?.name === 'AbortError') return;
        if (alive) setLoaded({ key, data: null, error: message(e) });
      }
    };
    void load();
    return () => { alive = false; controller.abort(); if (timer) clearTimeout(timer); };
  }, [open, waitFor, key]);

  const reload = useCallback(() => setNonce(n => n + 1), []);
  const current = loaded?.key === key ? loaded : null;
  return { orders: current?.data ?? null, error: current?.error ?? null, loading: current === null, reload };
}

/** Polls live delivery status at the interval Swiggy asks for (never faster), and stops when the order
 *  is delivered/cancelled, the sheet closes, or repeated failures. Past orders aren't polled. */
export function useLiveStatus(order: OrderSummary | null) {
  const orderId = order?.orderId ?? null;
  const addressId = order?.addressId ?? null;
  const live = !!order && !isPastOrder(order.status);
  const [snap, setSnap] = useState<{ orderId: string; delivery: DeliveryStatus | null; tracking: TrackingInfo | null; notes: string[]; failed: boolean } | null>(null);

  useEffect(() => {
    if (!orderId || !live) return;
    // Coordinates exist only for addresses created here with the user's shared location; else none is sent.
    return startLivePoll({
      fetch: () => instamartOrderStatus(orderId, addressId, coordsFor(addressId)),
      onResult: ({ delivery, tracking, notes }) => setSnap({ orderId, delivery, tracking, notes, failed: false }),
      // finished, or nothing pollable: stop; else the interval Swiggy asked for
      nextWaitSec: ({ delivery, tracking }) => (delivery?.terminal || (!delivery && !tracking) ? null : delivery?.pollIntervalSec ?? tracking?.pollIntervalSec ?? 30),
      onGiveUp: () => setSnap(s => ({ orderId, delivery: s?.delivery ?? null, tracking: s?.tracking ?? null, notes: [], failed: true })),
    });
  }, [orderId, addressId, live]);

  const current = snap?.orderId === orderId ? snap : null;
  return { delivery: current?.delivery ?? null, tracking: current?.tracking ?? null, notes: current?.notes ?? [], failed: current?.failed ?? false, polling: live && current === null };
}

/** Itemized details for one order (fetched once). `available: false` when Swiggy hasn't rolled the tool out. */
export function useOrderDetails(orderId: string | null) {
  const [loaded, setLoaded] = useState<{ orderId: string; details: OrderDetails | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!orderId) return;
    let alive = true;
    instamartOrderDetails(orderId)
      .then(({ details }) => alive && setLoaded({ orderId, details, error: null }))
      .catch(e => alive && setLoaded({ orderId, details: null, error: message(e) }));
    return () => { alive = false; };
  }, [orderId]);
  const current = loaded?.orderId === orderId ? loaded : null;
  return { details: current?.details ?? null, error: current?.error ?? null, loading: !!orderId && current === null };
}
