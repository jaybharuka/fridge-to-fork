// Sizing rule for fridge photos, kept pure (no DOM) so it is unit tested in plain Node: see imageSize.test.ts.

/** The size a photo must end up at: the largest that fits within maxWidth x maxHeight, aspect ratio kept, never enlarged. */
export function fitWithin(width: number, height: number, maxWidth: number, maxHeight: number): { width: number; height: number } {
  const scale = Math.min(1, maxWidth / width, maxHeight / height);
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}
