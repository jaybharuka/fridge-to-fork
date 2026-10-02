// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { fitWithin } from './imageSize.ts';

describe('fitWithin', () => {
  it('shrinks a 12MP landscape photo to the cap, keeping its ratio', () => {
    assert.deepEqual(fitWithin(4032, 3024, 1200, 1200), { width: 1200, height: 900 });
  });
  it('shrinks a portrait photo by its long edge', () => {
    assert.deepEqual(fitWithin(3024, 4032, 1200, 1200), { width: 900, height: 1200 });
  });
  it('never enlarges a small photo', () => {
    assert.deepEqual(fitWithin(800, 600, 1200, 1200), { width: 800, height: 600 });
  });
  it('whatever the source size (up to 48MP and a panorama), the result fits the cap, so the canvas is never source-sized', () => {
    for (const [w, h] of [[8000, 6000], [6000, 8000], [12000, 1000], [1000, 12000], [1, 5000]] as const) {
      const out = fitWithin(w, h, 1200, 1200);
      assert.ok(out.width <= 1200 && out.height <= 1200 && out.width >= 1 && out.height >= 1, `${w}x${h} -> ${out.width}x${out.height}`);
    }
  });
});
