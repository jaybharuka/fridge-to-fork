'use client';

import { ChevronLeft, CircleAlert, CircleCheck, RefreshCw, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useFoodLiveStatus, useFoodOrderDetails, useFoodOrderList } from '@/hooks/useFoodOrders';
import { formatInr, type FoodOrderRow } from '@/lib/food';
import { closeOrders, useOrdersUi } from '@/lib/ordersUi';
import { useSelectedAddressId } from '@/lib/addressStore';
import { AddressPicker } from './AddressPicker';
import { ReportProblem } from './ReportProblem';
import resultsStyles from './results.module.css';
import styles from './instamart.module.css';

const BAD = /cancel|reject|fail/i; // display colour only; whether an order is live comes from Swiggy's isActiveOrder

function StatusChip({ order }: { order: FoodOrderRow }) {
  const text = order.active ? order.deliveryStatus || order.status : order.status;
  const kind = BAD.test(text) ? styles.chipBad : order.active ? styles.chipLive : styles.chipDone;
  return <span className={`${styles.chip} ${kind}`}>{text || 'Placed'}</span>;
}

function OrderList({ orders, onPick }: { orders: FoodOrderRow[]; onPick: (id: string) => void }) {
  if (orders.length === 0) {
    return <p className={styles.none}>No Food orders found for this address. If you ordered to a different address, use Change to check it.</p>;
  }
  const group = (label: string, rows: FoodOrderRow[]) =>
    rows.length > 0 && (
      <section>
        <p className={styles.sectionLabel}>{label}</p>
        <ul className={styles.coupons}>
          {rows.map(o => (
            <li key={o.orderId}>
              <button type="button" className={styles.orderRow} onClick={() => onPick(o.orderId)}>
                <span className={styles.couponBody}>
                  <span className={styles.orderTitle}>{o.restaurant || `Order ${o.orderId}`}</span>
                  <span className={styles.meta}>{[o.orderedTime, o.items].filter(Boolean).join(' · ')}</span>
                </span>
                <span className={styles.orderSide}>
                  <StatusChip order={o} />
                  {o.total && <span className={styles.lineTotal}>{o.total}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    );
  return <>{group('In progress', orders.filter(o => o.active))}{group('Past orders', orders.filter(o => !o.active))}</>;
}

function LiveStatus({ order }: { order: FoodOrderRow | null }) {
  const live = useFoodLiveStatus(order);
  const d = live.delivery;
  const t = live.tracking;
  const past = order ? !order.active : false;

  let title = order?.deliveryStatus || order?.status || 'Placed';
  let sub: string | null = null;
  let tone = styles.ok;
  let Icon = Truck;
  if (d) {
    title = d.delivered ? 'Delivered' : d.cancelled ? 'Cancelled' : d.statusText || title;
    sub = d.terminal ? null : d.minutesLeft !== null ? (d.minutesLeft <= 1 ? 'Arriving any moment' : `Arriving in about ${d.minutesLeft} min`) : d.etaText;
    if (d.delivered) Icon = CircleCheck;
    if (d.cancelled) { Icon = CircleAlert; tone = styles.bad; }
  } else if (past) {
    Icon = BAD.test(title) ? CircleAlert : CircleCheck;
    tone = Icon === CircleAlert ? styles.bad : styles.ok;
  }
  if (t && !d?.terminal) {
    title = t.title || title;
    sub = t.subtitle || t.etaText || sub;
  }

  return (
    <div className={styles.statusCard} aria-live="polite">
      <Icon className={`${styles.statusIcon} ${tone}`} aria-hidden />
      <div style={{ flex: 1, minWidth: 0 }}>
        <p className={styles.statusBig}>{title}</p>
        {sub && <p className={styles.meta}>{sub}</p>}
        {t?.progress != null && !d?.terminal && (
          <div className={styles.progressTrack} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(t.progress)}>
            <div className={styles.progressBar} style={{ width: `${t.progress}%` }} />
          </div>
        )}
        {live.notes.map(n => <p key={n} className={styles.meta}>{n}</p>)}
        {live.failed && <p className={styles.couponWhy}>Live updates paused — reopen this screen to refresh.</p>}
      </div>
    </div>
  );
}

function Details({ orderId, order }: { orderId: string; order: FoodOrderRow | null }) {
  const { details, error, loading } = useFoodOrderDetails(orderId);
  if (loading) return <div className={styles.skeleton} aria-busy="true" />;
  if (error) return <p className={styles.couponWhy}>{error}</p>;
  if (details?.available) {
    const d = details;
    return (
      <div>
        {d.restaurant.name && <p className={styles.address}>From <strong>{[d.restaurant.name, d.restaurant.area].filter(Boolean).join(' · ')}</strong></p>}
        <p className={styles.sectionLabel}>Items</p>
        {d.items.map((i, idx) => (
          <div className={styles.cartItem} key={`${i.name}-${idx}`}>
            <div className={styles.info}>
              <p className={styles.name}>{i.name || 'Item'}</p>
              {(i.quantity !== null || i.options.length > 0) && <p className={styles.meta}>{[i.quantity !== null ? `Qty ${i.quantity}` : null, ...i.options].filter(Boolean).join(' · ')}</p>}
            </div>
            {i.price !== null && <span className={styles.lineTotal}>{formatInr(i.price)}</span>}
          </div>
        ))}
        <div className={styles.bill}>
          {d.charges.map(c => <div className={styles.billRow} key={c.label}><span>{c.label}</span><span>{c.value}</span></div>)}
          {d.coupon && d.coupon.discount ? <div className={styles.billRow}><span>Coupon {d.coupon.code}</span><span>−{formatInr(d.coupon.discount)}</span></div> : null}
          <div className={styles.billTotal}><span>Total</span><span>{d.total !== null ? formatInr(d.total) : order?.total ?? ''}</span></div>
        </div>
        {d.paymentMethod && <p className={styles.payment}>Paid by <strong>{d.paymentMethod}</strong></p>}
        {d.cancelHelp && <p className={styles.hint} style={{ textAlign: 'left' }}>{d.cancelHelp}</p>}
      </div>
    );
  }
  // Details not available: show what the order list already told us.
  return (
    <div>
      {order?.items && (<><p className={styles.sectionLabel}>Items</p><p className={styles.meta}>{order.items}</p></>)}
      {order?.total && <div className={styles.billTotal}><span>Total</span><span>{order.total}</span></div>}
      <p className={styles.hint}>{details && !details.available ? details.message : ''}</p>
    </div>
  );
}

function Panel({ initialOrderId, initialAddressId, onClose }: { initialOrderId: string | null; initialAddressId: string | null; onClose: () => void }) {
  const selected = useSelectedAddressId();
  const [addressId, setAddressId] = useState<string | null>(initialAddressId ?? selected);
  const [addressOpen, setAddressOpen] = useState(false);
  const [viewId, setViewId] = useState<string | null>(initialOrderId);
  const list = useFoodOrderList(true, addressId, initialOrderId);
  const order = viewId ? list.orders?.find(o => o.orderId === viewId) ?? null : null;

  if (addressOpen) {
    return (
      <AddressPicker
        currentId={list.address?.id ?? addressId}
        onBack={() => setAddressOpen(false)}
        onChoose={id => { setAddressOpen(false); setViewId(null); setAddressId(id); }}
      />
    );
  }

  return (
    <>
      <div className={resultsStyles.orderSheetHeader}>
        {viewId && <button type="button" className={styles.backBtn} onClick={() => setViewId(null)}><ChevronLeft aria-hidden /> All orders</button>}
        <h3 className={resultsStyles.orderSheetTitle}>{viewId ? `Order ${viewId}` : 'Your Food orders'}</h3>
        <p className={resultsStyles.orderSheetSubtitle}>{viewId ? 'Live status and details' : 'Track an order or look back at past ones'}</p>
      </div>

      {list.error && !list.orders ? (
        <div className={styles.centered}>
          <p className={styles.outcomeBody}>{list.error}</p>
          <button type="button" className={styles.primary} onClick={list.reload}>Try again</button>
          <ReportProblem product="food" input={{ tool: 'get_food_orders', errorMessage: list.error, flow: 'Opening my Food orders in the app', context: addressId ? { addressId } : {} }} />
        </div>
      ) : viewId ? (
        <>
          {list.loading && !order ? (
            <div className={styles.skeleton} aria-busy="true" />
          ) : order ? (
            <LiveStatus order={order} />
          ) : (
            <div className={styles.statusCard}>
              <Truck className={`${styles.statusIcon} ${styles.ok}`} aria-hidden />
              <div>
                <p className={styles.statusBig}>Just placed</p>
                <p className={styles.meta}>It can take a moment to show up in your orders.</p>
                <button type="button" className={styles.linkBtn} onClick={list.reload}><RefreshCw style={{ width: 13, height: 13, verticalAlign: '-2px' }} /> Refresh</button>
              </div>
            </div>
          )}
          <Details orderId={viewId} order={order} />
          <ReportProblem
            product="food"
            label="Report a problem with this order"
            input={{
              tool: order?.active ? 'get_food_delivery_status' : 'get_food_order_details',
              errorMessage: `Problem with order ${viewId}${order?.status ? ` (status: ${order.status})` : ''}`,
              flow: 'Viewing the order in the app',
              context: { orderId: viewId, ...(list.address?.id ?? addressId ? { addressId: (list.address?.id ?? addressId) as string } : {}) },
            }}
          />
        </>
      ) : list.loading ? (
        <div className={styles.list} aria-busy="true">{[0, 1, 2].map(i => <div key={i} className={styles.skeleton} />)}</div>
      ) : (
        <>
          {list.address && (
            <p className={styles.address}>
              Showing orders for <strong>{list.address.label}</strong> — {list.address.addressLine}{' '}
              <button type="button" className={styles.linkBtn} onClick={() => setAddressOpen(true)}>Change</button>
            </p>
          )}
          <OrderList orders={list.orders ?? []} onPick={setViewId} />
        </>
      )}

      <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
    </>
  );
}

// Food order history + live tracking + details, reachable from the order-placed screen (and the header once the
// flow is on). Same always-dark sheet as the order flow.
export function FoodOrdersSheet() {
  const ui = useOrdersUi();
  const isOpen = ui.open && ui.kind === 'food';
  const [mounted, setMounted] = useState(isOpen);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setMounted(true);
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    const timer = setTimeout(() => setMounted(false), 400);
    return () => clearTimeout(timer);
  }, [isOpen]);

  if (!mounted) return null;
  return (
    <div className={resultsStyles.orderBottomSheet}>
      <div className={`${resultsStyles.orderSheetBackdrop} ${visible ? resultsStyles.visible : ''}`} onClick={closeOrders} />
      <div className={`${resultsStyles.orderSheetPanel} ${visible ? resultsStyles.visible : ''}`} role="dialog" aria-label="Your Food orders">
        <div className={resultsStyles.orderSheetHandle} />
        {/* keyed by session: every open starts from a fresh list/order view */}
        <Panel key={ui.session} initialOrderId={ui.orderId} initialAddressId={ui.addressId} onClose={closeOrders} />
      </div>
    </div>
  );
}
