// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// Guard: a "Report a problem" never carries Swiggy's free-text order status, which can contain a rider's name.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { orderProblemMessage } from './reportText.ts';

const RIDER_STATUS = 'Order delivered on 29 Sep 2026, 11:01 AM by Rider Name';
const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel: string) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

describe('orderProblemMessage', () => {
  it('is the order id only', () => {
    assert.equal(orderProblemMessage('249628590953392'), 'Problem with order 249628590953392');
  });

  it('ignores a status string even if one is passed at runtime', () => {
    const message = (orderProblemMessage as (...args: unknown[]) => string)('IM-1', { status: RIDER_STATUS }, RIDER_STATUS);
    assert.equal(message, 'Problem with order IM-1');
    assert.ok(!message.includes('Rider Name'));
    assert.ok(!/status/i.test(message));
  });
});

describe('the order sheets', () => {
  for (const file of ['components/results/InstamartOrdersSheet.tsx', 'components/results/FoodOrdersSheet.tsx']) {
    it(`${path.basename(file)} builds its report message with orderProblemMessage and never from order.status`, () => {
      const src = read(file);
      assert.match(src, /errorMessage: orderProblemMessage\(viewId\)/);
      assert.ok(!/errorMessage:[^\n]*status/i.test(src), 'errorMessage must not include the order status');
      assert.ok(!src.includes('(status:'), 'no "(status: ...)" text in a report');
    });
  }
});
