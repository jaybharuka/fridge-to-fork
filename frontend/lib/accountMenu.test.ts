// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { accountMenuModel } from './accountMenu.ts';

describe('accountMenuModel', () => {
  it('a connected account sees its status and both order rows', () => {
    assert.deepEqual(accountMenuModel(true, true), { statusLabel: 'Connected to Swiggy', connected: true, showInstamartOrders: true, showFoodOrders: true });
  });
  it('Food orders disappear when Food ordering is switched off', () => {
    const m = accountMenuModel(true, false);
    assert.equal(m.showInstamartOrders, true);
    assert.equal(m.showFoodOrders, false);
  });
  it('without a connection there are no order rows (they would only hit an auth wall) and the status says so', () => {
    const m = accountMenuModel(false, true);
    assert.equal(m.statusLabel, 'Not connected');
    assert.equal(m.showInstamartOrders, false);
    assert.equal(m.showFoodOrders, false);
  });
});
