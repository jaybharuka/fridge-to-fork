// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// A checkout call that fails without a usable answer is the "unknown" screen (no retry, no way back to the cart), never "failed".
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { isAmbiguousCheckoutError } from './checkoutOutcome.ts';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel: string) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

describe('isAmbiguousCheckoutError', () => {
  it('no response, a garbled response, and Swiggy unreachable are all ambiguous', () => {
    for (const code of ['network', 'unexpected_response', 'upstream_unavailable']) assert.equal(isAmbiguousCheckoutError(code), true, code);
  });
  it('a request that never left the server is a plain failure', () => {
    assert.equal(isAmbiguousCheckoutError('checkout_not_sent'), false);
  });
  it('Swiggy refusals and review-again problems are plain failures', () => {
    for (const code of ['tool_error', 'cart_changed', 'cart_blocked', 'address_mismatch', 'payment_unavailable', 'checkout_in_progress', 'auth_required']) {
      assert.equal(isAmbiguousCheckoutError(code), false, code);
    }
  });
});

describe('the order hooks and screens', () => {
  for (const hook of ['hooks/useInstamartOrder.ts', 'hooks/useFoodOrder.ts']) {
    it(`${path.basename(hook)} decides "unknown" with isAmbiguousCheckoutError, not a hand-written list of codes`, () => {
      const src = read(hook);
      assert.match(src, /const ambiguous = isAmbiguousCheckoutError\(d\.code\);/);
      assert.ok(!/d\.code === 'network' \|\| d\.code === 'unexpected_response'/.test(src), 'no private list of ambiguous codes');
    });
  }
  for (const screen of ['components/results/InstamartOutcome.tsx', 'components/results/FoodOutcome.tsx']) {
    it(`${path.basename(screen)} offers a way back to the cart on exactly one screen: the plain failure`, () => {
      const src = read(screen);
      assert.equal(src.split('onClick={onBackToCart}').length - 1, 1);
      const failed = src.indexOf("outcome.status === 'failed'");
      const back = src.indexOf('onClick={onBackToCart}');
      const unknown = src.indexOf('never offer a retry');
      assert.ok(failed >= 0 && unknown >= 0, 'the screens still have their failed and unknown branches');
      assert.ok(failed < back && back < unknown, 'the back button sits between the failed branch and the unknown one, i.e. in the failed branch');
    });
  }
});
