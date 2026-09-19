// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createSearchCache, keyOf, type SearchFn } from './searchCache.ts';

const ADDRESS = { id: 'addr-home', label: 'Home', addressLine: '12 MG Road' };

const option = (spinId: string, available = true) => ({
  spinId, skuId: `sku-${spinId}`, name: `Product ${spinId}`, brand: 'Brand', size: '500 g',
  price: 32, mrp: 40, imageUrl: null, available, maxQuantity: 5,
});

/** Fake of POST /api/instamart/search: records every request, answers from `catalog`. */
function fakeSearch(catalog: Record<string, ReturnType<typeof option>[]>, opts: { fail?: Set<string> } = {}) {
  const calls: string[][] = [];
  const search: SearchFn = async items => {
    calls.push([...items]);
    await Promise.resolve();
    if (items.some(i => opts.fail?.has(i.toLowerCase()))) throw new Error('boom');
    return {
      address: ADDRESS,
      results: items.map(i => ({ ingredient: i, options: catalog[i.toLowerCase()] ?? [], note: catalog[i.toLowerCase()] ? null : 'No match on Instamart' })),
    };
  };
  return { search, calls };
}

describe('search cache', () => {
  it('fetches once, then serves the same ingredients from cache (the order sheet opening after the checklist)', async () => {
    const { search, calls } = fakeSearch({ tomato: [option('t1')], onion: [option('o1')] });
    const cache = createSearchCache(search);

    const first = await cache.ensure(['tomato', 'onion']);
    const second = await cache.ensure(['tomato', 'onion']);

    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0], ['tomato', 'onion']);
    assert.equal(first.entries.get('tomato')?.status, 'ready');
    assert.equal(second.entries.get('onion')?.result?.options[0].spinId, 'o1');
    assert.deepEqual(second.address, ADDRESS);
    assert.equal(second.error, null);
  });

  it('only requests the ingredients it is missing', async () => {
    const { search, calls } = fakeSearch({ tomato: [option('t1')], paneer: [option('p1')] });
    const cache = createSearchCache(search);
    await cache.ensure(['tomato']);
    await cache.ensure(['tomato', 'paneer']);
    assert.deepEqual(calls, [['tomato'], ['paneer']]);
  });

  it('shares an in-flight request between concurrent callers', async () => {
    const { search, calls } = fakeSearch({ tomato: [option('t1')], onion: [option('o1')] });
    const cache = createSearchCache(search);
    const [a, b] = await Promise.all([cache.ensure(['tomato', 'onion']), cache.ensure(['onion', 'tomato'])]);
    assert.equal(calls.length, 1);
    assert.equal(a.entries.get('tomato')?.status, 'ready');
    assert.equal(b.entries.get('onion')?.status, 'ready');
  });

  it('treats names case-insensitively and ignores blanks/duplicates', async () => {
    const { search, calls } = fakeSearch({ tomato: [option('t1')] });
    const cache = createSearchCache(search);
    const out = await cache.ensure(['Tomato', 'tomato ', '  ', 'TOMATO']);
    assert.deepEqual(calls, [['Tomato']]);
    assert.equal(out.entries.size, 1);
    assert.equal(out.entries.get(keyOf('tomato'))?.status, 'ready');
  });

  it('caches "no match" as a real answer and does not search it again', async () => {
    const { search, calls } = fakeSearch({});
    const cache = createSearchCache(search);
    const out = await cache.ensure(['unobtainium']);
    await cache.ensure(['unobtainium']);
    assert.equal(calls.length, 1);
    assert.equal(out.entries.get('unobtainium')?.status, 'ready');
    assert.deepEqual(out.entries.get('unobtainium')?.result?.options, []);
  });

  it('a failed search degrades to failed entries, never throws, and is retried next time', async () => {
    const { search, calls } = fakeSearch({ tomato: [option('t1')] }, { fail: new Set(['tomato']) });
    const cache = createSearchCache(search);

    const out = await cache.ensure(['tomato']);
    assert.equal(out.entries.get('tomato')?.status, 'failed');
    assert.equal(out.entries.get('tomato')?.result, null);
    assert.ok(out.error instanceof Error);
    assert.equal(out.address, null);

    await cache.ensure(['tomato']); // failed entries are not "usable" -> searched again
    assert.equal(calls.length, 2);
  });

  it('one bad batch does not poison ingredients that already succeeded', async () => {
    const { search } = fakeSearch({ tomato: [option('t1')], onion: [option('o1')] }, { fail: new Set(['onion']) });
    const cache = createSearchCache(search);
    await cache.ensure(['tomato']);
    const out = await cache.ensure(['tomato', 'onion']);
    assert.equal(out.entries.get('tomato')?.status, 'ready');
    assert.equal(out.entries.get('onion')?.status, 'failed');
    assert.deepEqual(out.address, ADDRESS); // address from the earlier success is kept
  });

  it('marks an ingredient failed if the server omits it from the response', async () => {
    const cache = createSearchCache(async () => ({ address: ADDRESS, results: [] }));
    const out = await cache.ensure(['tomato']);
    assert.equal(out.entries.get('tomato')?.status, 'failed');
    assert.equal(out.error, null);
  });

  it('searches again once an entry is older than the TTL', async () => {
    let clock = 0;
    const { search, calls } = fakeSearch({ tomato: [option('t1')] });
    const cache = createSearchCache(search, { ttlMs: 1000, now: () => clock });
    await cache.ensure(['tomato']);
    clock = 999;
    await cache.ensure(['tomato']);
    assert.equal(calls.length, 1);
    clock = 1001;
    await cache.ensure(['tomato']);
    assert.equal(calls.length, 2);
  });

  it('publishes loading then ready to subscribers, with a new snapshot each time', async () => {
    const { search } = fakeSearch({ tomato: [option('t1')] });
    const cache = createSearchCache(search);
    const seen: string[] = [];
    const before = cache.getSnapshot();
    const unsubscribe = cache.subscribe(() => seen.push(cache.getSnapshot().entries.get('tomato')?.status ?? 'none'));

    const pending = cache.ensure(['tomato']);
    assert.equal(cache.getSnapshot().entries.get('tomato')?.status, 'loading'); // visible synchronously, for the row skeleton
    await pending;
    unsubscribe();

    assert.deepEqual(seen, ['loading', 'ready']);
    assert.notEqual(cache.getSnapshot(), before);
    assert.equal(before.entries.size, 0); // old snapshots are never mutated
    await cache.ensure(['tomato']);
    assert.equal(seen.length, 2); // unsubscribed
  });
});
