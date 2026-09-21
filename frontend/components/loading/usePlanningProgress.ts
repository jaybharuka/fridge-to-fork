'use client';

import { useEffect, useState } from 'react';

/** Milliseconds since `active` last turned true (0 while inactive). Ticks a few times a second: enough for a smooth-looking
 *  bar (the fill has its own CSS transition) without re-rendering every frame. Purely a clock: it reads nothing from the scan. */
export function useElapsed(active: boolean, tickMs = 250): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!active) return;
    const start = performance.now();
    const id = setInterval(() => setElapsed(performance.now() - start), tickMs);
    return () => {
      clearInterval(id);
      setElapsed(0);
    };
  }, [active, tickMs]);
  return elapsed;
}

/** A progress percentage that eases toward `ceiling` and never reaches it: quick at first, slowing down, so a 5s wait and a
 *  40s wait both keep visibly moving without ever claiming to be finished. (There is no real signal to key it to: the meal
 *  plan arrives in one piece.) Half-life form: half of the remaining distance is covered every `halfLifeMs`. */
export function easedProgress(elapsedMs: number, ceiling = 92, halfLifeMs = 9000): number {
  return ceiling * (1 - Math.pow(0.5, Math.max(0, elapsedMs) / halfLifeMs));
}
