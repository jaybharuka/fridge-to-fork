'use client';
import { useCallback, useEffect, useState } from 'react';
import {
  InstamartApiError,
  instamartOrderDetails,
  instamartOrders,
  instamartOrderStatus,
  isPastOrder,
  type DeliveryStatus,
  type OrderDetails,
  type OrderSummary,
} from '../lib/instamart';

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
    const load = async () => {
      try {
        const { orders } = await instamartOrders(false);
        if (!alive) return;
        setLoaded({ key, data: orders, error: null });
        if (waitFor && !orders.some(o => o.orderId === waitFor) && ++attempts < 4) timer = setTimeout(load, 4000);
      } catch (e) {
        if (alive) setLoaded({ key, data: null, error: message(e) });
      }
    };
    void load();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [open, waitFor, key]);

  const reload = useCallback(() => setNonce(n => n + 1), []);
  const current = loaded?.key === key ? loaded : null;
  return { orders: current?.data ?? null, error: current?.error ?? null, loading: current === null, reload };
}

const MAX_STATUS_FAILURES = 5;

/** Polls live delivery status at the interval Swiggy asks for (never faster), and stops when the order
 *  is delivered/cancelled, the sheet closes, or repeated failures. Past orders aren't polled. */
export function useLiveStatus(order: OrderSummary | null) {
  const orderId = order?.orderId ?? null;
  const addressId = order?.addressId ?? null;
  const live = !!order && !isPastOrder(order.status);
  const [snap, setSnap] = useState<{ orderId: string; delivery: DeliveryStatus | null; notes: string[]; failed: boolean } | null>(null);

  useEffect(() => {
    if (!orderId || !live) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const tick = async () => {
      let wait = 30;
      try {
        const { delivery, notes } = await instamartOrderStatus(orderId, addressId);
        if (!alive) return;
        failures = 0;
        setSnap({ orderId, delivery, notes, failed: false });
        if (delivery?.terminal || !delivery) return; // finished, or nothing pollable (no address / tool missing)
        wait = delivery.pollIntervalSec;
      } catch {
        if (!alive) return;
        if (++failures >= MAX_STATUS_FAILURES) return setSnap(s => ({ orderId, delivery: s?.delivery ?? null, notes: [], failed: true }));
      }
      timer = setTimeout(tick, wait * 1000);
    };
    void tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [orderId, addressId, live]);

  const current = snap?.orderId === orderId ? snap : null;
  return { delivery: current?.delivery ?? null, notes: current?.notes ?? [], failed: current?.failed ?? false, polling: live && current === null };
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
