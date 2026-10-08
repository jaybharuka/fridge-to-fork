// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// The "unknown" and "partial" checkout screens must let the user see whether the order exists: a primary "Check my orders" button
// that closes the sheet and opens the matching order history. It must not appear on the placed or plain-failure screens.
//
// These components import CSS modules, which Node's test runner cannot load, so the screens are checked by reading their source:
// the branches are cut at the markers the components already have, and each branch is asserted on. The click itself (closing the
// sheet, opening the right history with the right orders) is checked in a browser against a mock backend.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel: string) => fs.readFileSync(path.join(FRONTEND, rel), 'utf8');

function branches(src: string) {
  const placed = src.indexOf("outcome.status === 'placed'");
  const failed = src.indexOf("outcome.status === 'failed'");
  const unknown = src.indexOf('never offer a retry');
  assert.ok(placed >= 0 && failed > placed && unknown > failed, 'placed, failed and unknown branches are all there, in that order');
  return { beforeUnknown: src.slice(0, unknown), unknown: src.slice(unknown) };
}

const PRODUCTS = [
  { name: 'Instamart', screen: 'components/results/InstamartOutcome.tsx', sheet: 'components/results/InstamartOrderSheet.tsx', opens: 'openOrders(null);' },
  { name: 'Food', screen: 'components/results/FoodOutcome.tsx', sheet: 'components/results/FoodOrderSheet.tsx', opens: "openOrders(null, 'food', state.review?.address.id ?? null);" },
];

for (const p of PRODUCTS) {
  describe(`${p.name} outcome screen`, () => {
    const src = read(p.screen);
    const { beforeUnknown, unknown } = branches(src);

    it('has the button in the unknown and partial branch, as the primary action above Close', () => {
      assert.match(unknown, /<button type="button" className=\{styles\.primary\} onClick=\{onCheckOrders\}>Check my orders<\/button>/);
      assert.ok(unknown.indexOf('Check my orders') < unknown.indexOf('>Close<'), 'above Close');
      assert.match(unknown, /className=\{styles\.secondary\} onClick=\{onClose\}>Close<\/button>/);
    });
    it('keeps the warning text and puts "Report a problem" after the buttons', () => {
      assert.ok(unknown.includes("Don&apos;t order again until you&apos;ve checked, so you aren&apos;t charged twice."));
      assert.ok(unknown.indexOf('>Close<') < unknown.indexOf('{report}'));
    });
    it('does not have the button on the placed or plain-failure screens', () => {
      assert.ok(!beforeUnknown.includes('Check my orders'));
      assert.equal(beforeUnknown.split('onClick={onCheckOrders}').length - 1, 0);
    });
    it('takes the handler as a prop', () => {
      assert.match(src, /onCheckOrders: \(\) => void;/);
      assert.match(src, /onCheckOrders,/);
    });
  });

  describe(`${p.name} order sheet`, () => {
    it('wires the button to close the sheet and open the matching order history', () => {
      const src = read(p.sheet);
      assert.ok(src.includes(`onCheckOrders={() => { onClose(); ${p.opens} }}`), `expected onCheckOrders to call ${p.opens}`);
    });
  });
}

describe('the two products open their own history', () => {
  it('Instamart opens the Instamart list (the default kind), Food opens the Food list for the address of the review', () => {
    assert.ok(read(PRODUCTS[0].sheet).includes('openOrders(null);'));
    assert.ok(read(PRODUCTS[1].sheet).includes("openOrders(null, 'food', state.review?.address.id ?? null);"));
  });
});
