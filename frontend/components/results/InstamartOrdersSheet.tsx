'use client';

import { ChevronLeft, CircleAlert, CircleCheck, RefreshCw, Truck } from 'lucide-react';
import { useState } from 'react';
import { closeOrders, useOrdersUi } from '@/lib/ordersUi';
import { formatInr, isPastOrder, type OrderDetails, type OrderSummary } from '@/lib/instamart';
import { useLiveStatus, useOrderDetails, useOrderList } from '@/hooks/useInstamartOrders';
import { Sheet } from '@/components/ui/Sheet';
import sheetStyles from '@/components/ui/Sheet.module.css';
import { ReportProblem } from './ReportProblem';
import styles from './instamart.module.css';

function when(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function itemsLine(order: OrderSummary): string {
  const names = order.items.map(i => (i.quantity && i.quantity > 1 ? `${i.name} ×${i.quantity}` : i.name)).filter(Boolean);
  if (names.length === 0) return order.itemCount ? `${order.itemCount} item${order.itemCount === 1 ? '' : 's'}` : '';
  return names.length > 2 ? `${names.slice(0, 2).join(', ')} +${names.length - 2} more` : names.join(', ');
}

function StatusChip({ status }: { status: string }) {
  const kind = /cancel|reject|fail/i.test(status) ? styles.chipBad : isPastOrder(status) ? styles.chipDone : styles.chipLive;
  return <span className={`${styles.chip} ${kind}`}>{status || 'Placed'}</span>;
}

// get_orders only returns the last 15 days (per Swiggy's reference), so an empty list means "none recently", not "never".
function OrderList({ orders, onPick }: { orders: OrderSummary[]; onPick: (id: string) => void }) {
  if (orders.length === 0) return <p className={styles.none}>No Instamart orders in the last 15 days.</p>;
  const active = orders.filter(o => !isPastOrder(o.status));
  const past = orders.filter(o => isPastOrder(o.status));
  const group = (label: string, rows: OrderSummary[]) =>
    rows.length > 0 && (
      <section>
        <p className={styles.sectionLabel}>{label}</p>
        <ul className={styles.coupons}>
          {rows.map(o => (
            <li key={o.orderId}>
              <button type="button" className={styles.orderRow} onClick={() => onPick(o.orderId)}>
                <span className={styles.couponBody}>
                  <span className={styles.orderTitle}>Order {o.orderId}</span>
                  <span className={styles.meta}>{[when(o.createdAt), itemsLine(o)].filter(Boolean).join(' · ')}</span>
                </span>
                <span className={styles.orderSide}>
                  <StatusChip status={o.status} />
                  {o.totalAmount !== null && <span className={styles.lineTotal}>{formatInr(o.totalAmount)}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    );
  return <>{group('In progress', active)}{group('Past orders', past)}</>;
}

function LiveStatus({ order }: { order: OrderSummary | null }) {
  const live = useLiveStatus(order);
  const d = live.delivery;
  const past = order ? isPastOrder(order.status) : false;

  let title = order?.status || 'Placed';
  let sub: string | null = order?.estimatedDeliveryTime ? `Estimated delivery ${order.estimatedDeliveryTime}` : null;
  let tone = styles.ok;
  let Icon = Truck;
  if (d) {
    title = d.delivered ? 'Delivered' : d.cancelled ? 'Cancelled' : d.statusText || title;
    sub = d.terminal ? null : d.minutesLeft !== null ? (d.minutesLeft <= 1 ? 'Arriving any moment' : `Arriving in about ${d.minutesLeft} min`) : d.etaText || sub;
    if (d.delivered) Icon = CircleCheck;
    if (d.cancelled) { Icon = CircleAlert; tone = styles.bad; }
  } else if (past) {
    Icon = /cancel|reject|fail/i.test(title) ? CircleAlert : CircleCheck;
    tone = Icon === CircleAlert ? styles.bad : styles.ok;
    sub = null;
  }

  const t = live.tracking;
  if (t && !d?.terminal) {
    title = t.statusMessage || title;
    sub = t.subStatusMessage || t.etaText || sub;
  }

  return (
    <div className={styles.statusCard} aria-live="polite">
      <Icon className={`${styles.statusIcon} ${tone}`} aria-hidden />
      <div>
        <p className={styles.statusBig}>{title}</p>
        {sub && <p className={styles.meta}>{sub}</p>}
        {t?.store && <p className={styles.meta}>From {t.store}</p>}
        {t?.paymentMessage && <p className={styles.meta}>{t.paymentMessage}</p>}
        {t?.riderLocation && !d?.terminal && (
          <a className={styles.linkBtn} href={`https://www.google.com/maps?q=${t.riderLocation.lat},${t.riderLocation.lng}`} target="_blank" rel="noopener noreferrer">See rider on map</a>
        )}
        {live.notes.map(n => <p key={n} className={styles.meta}>{n}</p>)}
        {live.failed && <p className={styles.couponWhy}>Live updates paused — reopen this screen to refresh.</p>}
      </div>
    </div>
  );
}

function Details({ orderId, order }: { orderId: string; order: OrderSummary | null }) {
  const { details, error, loading } = useOrderDetails(orderId);
  if (loading) return <div className={styles.skeleton} aria-busy="true" />;
  if (error) return <p className={styles.couponWhy}>{error}</p>;
  const d: OrderDetails | null = details;
  if (d?.available) {
    return (
      <div>
        <p className={styles.sectionLabel}>Items</p>
        {d.items.map((i, idx) => (
          <div className={styles.cartItem} key={`${i.name}-${idx}`}>
            <div className={styles.info}>
              <p className={`${styles.name} ${i.removed ? styles.removed : ''}`}>{i.name}</p>
              <p className={styles.meta}>{[i.quantity ? `Qty ${i.quantity}` : null, i.removed ? 'Removed' : null].filter(Boolean).join(' · ')}</p>
            </div>
            {i.finalPrice !== null && <span className={`${styles.lineTotal} ${i.removed ? styles.removed : ''}`}>{formatInr(i.finalPrice)}</span>}
          </div>
        ))}
        <div className={styles.bill}>
          {d.bill.lineItems.map((li, idx) => (
            <div className={styles.billRow} key={`${li.name}-${idx}`}><span>{li.name}</span><span>{li.amount}</span></div>
          ))}
          <div className={styles.billTotal}><span>Total</span><span>{d.bill.grandTotal ?? formatInr(d.totalBill)}</span></div>
        </div>
        {d.hasRefunds && <p className={styles.notice}>Some of this order was refunded. Check the Swiggy app for refund status.</p>}
      </div>
    );
  }
  // Tool not available for this account: show what the order list already told us.
  return (
    <div>
      <p className={styles.sectionLabel}>Items</p>
      {order?.items.map((i, idx) => (
        <div className={styles.cartItem} key={`${i.name}-${idx}`}>
          <div className={styles.info}><p className={styles.name}>{i.name}</p>{i.quantity && <p className={styles.meta}>Qty {i.quantity}</p>}</div>
        </div>
      ))}
      {order?.totalAmount !== null && order?.totalAmount !== undefined && (
        <div className={styles.billTotal}><span>Total</span><span>{formatInr(order.totalAmount)}</span></div>
      )}
      <p className={styles.hint}>{d && !d.available ? d.message : 'Itemized details are loading…'}</p>
    </div>
  );
}

function Panel({ initialOrderId, onClose }: { initialOrderId: string | null; onClose: () => void }) {
  const [viewId, setViewId] = useState<string | null>(initialOrderId);
  const list = useOrderList(true, initialOrderId);
  const order = viewId ? list.orders?.find(o => o.orderId === viewId) ?? null : null;

  return (
    <>
      {/* The title/back-button toggle with viewId (internal navigation state), so it's rendered as plain content
          reusing Sheet's own header classes, rather than via Sheet's title/subtitle props (which are for a header
          that's fixed for the sheet's whole open lifetime, e.g. FoodOrderSheet's). */}
      <div className={sheetStyles.header}>
        {viewId && (
          <button type="button" className={styles.backBtn} onClick={() => setViewId(null)}><ChevronLeft aria-hidden /> All orders</button>
        )}
        <h3 className={sheetStyles.title}>{viewId ? `Order ${viewId}` : 'Your Instamart orders'}</h3>
        <p className={sheetStyles.subtitle}>{viewId ? 'Live status and details' : 'Track an order or look back at past ones'}</p>
      </div>

      {list.error && !list.orders ? (
        <div className={styles.centered}>
          <p className={styles.outcomeBody}>{list.error}</p>
          <button type="button" className={styles.primary} onClick={list.reload}>Try again</button>
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
            label="Report a problem with this order"
            input={{
              tool: order && isPastOrder(order.status) ? 'get_order_details' : 'get_delivery_status',
              errorMessage: `Problem with order ${viewId}${order?.status ? ` (status: ${order.status})` : ''}`,
              flow: 'Viewing the order in the app',
              context: { orderId: viewId, ...(order?.addressId ? { addressId: order.addressId } : {}) },
            }}
          />
        </>
      ) : list.loading ? (
        <div className={styles.list} aria-busy="true">{[0, 1, 2].map(i => <div key={i} className={styles.skeleton} />)}</div>
      ) : (
        <OrderList orders={list.orders ?? []} onPick={setViewId} />
      )}

      <button type="button" className={styles.secondary} onClick={onClose}>Close</button>
    </>
  );
}

// Order history + live tracking + itemized details, reachable from the header at any time and from the
// order-placed screen. Phase 3 (2026-09): now components/ui/Sheet — follows the light/dark toggle like the rest of
// the app instead of the old hardcoded-dark styling, and picks up Sheet's swipe-to-close and Escape-to-close for
// free (this sheet never had either before; a straightforward improvement, not a behavior change to preserve).
export function InstamartOrdersSheet() {
  const ui = useOrdersUi();
  const isOpen = ui.open && ui.kind === 'instamart';
  return (
    <Sheet open={isOpen} onClose={closeOrders} ariaLabel="Your Instamart orders">
      {/* keyed by session: every open starts from a fresh list/order view */}
      <Panel key={ui.session} initialOrderId={ui.orderId} onClose={closeOrders} />
    </Sheet>
  );
}
