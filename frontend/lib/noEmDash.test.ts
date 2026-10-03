// Run: npm test   (node --experimental-strip-types --test lib/*.test.ts)
// Guard: no em dash in any text the UI can show. The backend has the same guard in tests/test_no_em_dashes.py.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const EM = '—'; // escaped on purpose: this file must not contain the character itself
const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

/** Lines holding an em dash that are code or text, not a comment. Comments are for developers, not shown in the UI. */
function visibleEmDashes(): string[] {
  const hits: string[] = [];
  for (const dir of ['app', 'components', 'hooks', 'lib']) {
    for (const file of sourceFiles(path.join(FRONTEND, dir))) {
      let inBlock = false;
      fs.readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        const t = line.trim();
        const comment = inBlock || t.startsWith('//') || t.startsWith('*') || t.startsWith('/*') || t.startsWith('{/*');
        if (line.includes(EM) && !comment) hits.push(`${path.relative(FRONTEND, file)}:${i + 1}: ${t.slice(0, 80)}`);
        if (line.includes('/*') && !line.includes('*/')) inBlock = true;
        if (line.includes('*/')) inBlock = false;
      });
    }
  }
  return hits;
}

describe('no em dashes in UI text', () => {
  it('no non-comment line in app/, components/, hooks/ or lib/ contains one', () => {
    assert.deepEqual(visibleEmDashes(), []);
  });
});
