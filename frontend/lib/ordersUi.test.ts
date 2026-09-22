// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';
import { closeOrders, getOrdersUiState, openOrders } from './ordersUi.ts';

afterEach(() => closeOrders());

describe('openOrders', () => {
  it('opens with the given kind/order/address and bumps the session', () => {
    const before = getOrdersUiState().session;
    openOrders('F-1', 'food', 'addr-home');
    assert.deepEqual(getOrdersUiState(), { open: true, orderId: 'F-1', kind: 'food', addressId: 'addr-home', session: before + 1 });
  });

  it('a repeat call for the exact same view already open is a no-op (this is the double-tap guard)', () => {
    openOrders(null, 'food');
    const after1 = getOrdersUiState();
    openOrders(null, 'food');
    assert.deepEqual(getOrdersUiState(), after1); // same object identity's worth of fields — nothing changed, no remount
  });

  it('a second tap on the Instamart orders button is likewise a no-op while already open', () => {
    openOrders();
    const after1 = getOrdersUiState().session;
    openOrders();
    assert.equal(getOrdersUiState().session, after1);
  });

  it('a different order id while open still opens (jumping straight to a just-placed order)', () => {
    openOrders(null, 'food');
    const before = getOrdersUiState().session;
    openOrders('F-2', 'food', 'addr-home');
    assert.equal(getOrdersUiState().session, before + 1);
    assert.equal(getOrdersUiState().orderId, 'F-2');
  });

  it('switching kind while open still opens', () => {
    openOrders(null, 'food');
    const before = getOrdersUiState().session;
    openOrders(null, 'instamart');
    assert.equal(getOrdersUiState().session, before + 1);
    assert.equal(getOrdersUiState().kind, 'instamart');
  });

  it('reopening the same view after closing is not blocked by the guard', () => {
    openOrders(null, 'food');
    closeOrders();
    const before = getOrdersUiState().session;
    openOrders(null, 'food');
    assert.equal(getOrdersUiState().session, before + 1);
    assert.equal(getOrdersUiState().open, true);
  });
});

describe('closeOrders', () => {
  it('keeps the last view but flips open to false, without touching the session', () => {
    openOrders('F-1', 'food', 'addr-home');
    const before = getOrdersUiState().session;
    closeOrders();
    assert.deepEqual(getOrdersUiState(), { open: false, orderId: 'F-1', kind: 'food', addressId: 'addr-home', session: before });
  });
});
