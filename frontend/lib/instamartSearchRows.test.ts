// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { MAX_SEARCH_ROWS, rowsFrom, toCartResult } from './instamartSearchRows.ts';
import type { InstamartOption, InstamartSearchResult } from './instamart.ts';

const opt = (spinId: string, over: Partial<InstamartOption> = {}): InstamartOption => ({
  spinId, skuId: `sku-${spinId}`, name: 'Amul Butter', brand: 'Amul', size: '100 g',
  price: 58, mrp: 60, imageUrl: null, available: true, maxQuantity: 5, ...over,
});
const result = (options: InstamartOption[], note: string | null = null): InstamartSearchResult => ({ ingredient: 'butter', options, note });
const none = new Set<string>();

describe('rowsFrom', () => {
  it('returns nothing for no result', () => {
    assert.deepEqual(rowsFrom(null, none, none), []);
  });

  it('keeps at most five rows', () => {
    const many = Array.from({ length: 9 }, (_, i) => opt(`s${i}`, { size: `${i} g` }));
    assert.equal(MAX_SEARCH_ROWS, 5);
    assert.equal(rowsFrom(result(many), none, none).length, 5);
  });

  it('sorts in-stock first and keeps Swiggy order otherwise', () => {
    const rows = rowsFrom(result([opt('a', { available: false }), opt('b', { size: '200 g' }), opt('c', { size: '500 g' })]), none, none);
    assert.deepEqual(rows.map(r => r.option.spinId), ['b', 'c', 'a']);
    assert.equal(rows[2].canAdd, false);
    assert.equal(rows[0].canAdd, true);
  });

  it('marks a variation already in the order as added and not addable again', () => {
    const rows = rowsFrom(result([opt('a'), opt('b', { size: '200 g' })]), new Set(['a']), none);
    assert.deepEqual(rows.map(r => [r.option.spinId, r.added, r.canAdd]), [['a', true, false], ['b', false, true]]);
  });

  it('gives each row a label that is unique among the sheet\'s items', () => {
    const rows = rowsFrom(result([opt('a'), opt('b', { size: '200 g' })]), none, new Set(['Amul Butter']));
    assert.deepEqual(rows.map(r => r.label), ['Amul Butter · 100 g', 'Amul Butter · 200 g']);
  });

  it('uses the plain name when nothing else has it', () => {
    assert.equal(rowsFrom(result([opt('a')]), none, none)[0].label, 'Amul Butter');
  });

  it('never repeats a label even when name and size collide', () => {
    const rows = rowsFrom(result([opt('a'), opt('b')]), none, new Set(['Amul Butter', 'Amul Butter · 100 g']));
    assert.equal(new Set(rows.map(r => r.label)).size, 2);
    assert.ok(rows.every(r => !['Amul Butter', 'Amul Butter · 100 g'].includes(r.label)));
  });

  it('falls back to the brand or a placeholder when Swiggy sends no name', () => {
    assert.equal(rowsFrom(result([opt('a', { name: '', brand: 'Amul' })]), none, none)[0].label, 'Amul');
    assert.equal(rowsFrom(result([opt('a', { name: '', brand: null })]), none, none)[0].label, 'Item');
  });
});

describe('toCartResult', () => {
  it('wraps the chosen variation so the sheet\'s add path picks exactly that SKU', () => {
    const [row] = rowsFrom(result([opt('a'), opt('b', { size: '200 g' })]), none, none);
    assert.deepEqual(toCartResult(row), { ingredient: row.label, options: [row.option], note: null });
  });
});
