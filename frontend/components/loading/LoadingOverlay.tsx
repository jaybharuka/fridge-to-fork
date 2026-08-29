'use client';
import { useEffect, useState, type CSSProperties } from 'react';
import styles from './loading.module.css';

interface LoadingOverlayProps {
  visible: boolean;
  hasPhoto: boolean;
  headlineText: string;
}

interface Stage {
  label: string;
  delay: number;
}

// Ported from templates/index.html:2235-2246 (LOADING_STAGES) — no real
// backend signal exists to key these off of mid-flight, so they advance on
// a fixed schedule tuned to roughly match each mode's real latency.
const LOADING_STAGES: { photo: Stage[]; recipe: Stage[] } = {
  photo: [
    { label: 'Reading your fridge photo', delay: 0 },
    { label: 'Detecting ingredients', delay: 1800 },
    { label: 'Cross-checking pantry basics', delay: 4200 },
  ],
  recipe: [
    { label: 'Understanding your request', delay: 0 },
    { label: 'Gathering recipe knowledge', delay: 700 },
    { label: 'Preparing your ingredient list', delay: 1600 },
  ],
};

interface Particle {
  left: number;
  drift: number;
  duration: number;
  delay: number;
}

// Ported from templates/index.html:2367-2379 (initLoadingParticles) — 8
// particles with randomized position/drift/timing, generated once.
function makeParticles(): Particle[] {
  return Array.from({ length: 8 }, () => ({
    left: Math.random() * 100,
    drift: Math.random() * 100 - 50,
    duration: 12 + Math.random() * 8,
    delay: Math.random() * 10,
  }));
}

// Dark full-screen overlay shown for recipe-only scans (and behind the
// fridge illustration for photo scans before PhotoScanScreen takes over).
// Ported from templates/index.html:1886-1905 (markup), 1307-1664 (CSS),
// 2235-2409 (particle field + staged checklist + show/hide mechanics).
export function LoadingOverlay({ visible, hasPhoto, headlineText }: LoadingOverlayProps) {
  const [shouldRender, setShouldRender] = useState(visible);
  const [shown, setShown] = useState(false);
  const [headlineEntered, setHeadlineEntered] = useState(false);
  const [enteredStages, setEnteredStages] = useState<boolean[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);
  // Lazy initializer — generated once on mount, never updated, so a plain
  // ref would need to be read during render (flagged by react-hooks/refs);
  // useState's initializer runs outside render instead.
  const [particles] = useState<Particle[]>(makeParticles);

  const stages = hasPhoto ? LOADING_STAGES.photo : LOADING_STAGES.recipe;

  // Mount immediately on becoming visible; on hide, mirror
  // hideLoadingOverlay()'s 300ms fade-then-unmount (line 2402-2409): the
  // 'show' class drops right away, display:none (here, unmount) only after
  // the opacity transition finishes.
  useEffect(() => {
    if (visible) {
      setShouldRender(true);
      return;
    }
    setShown(false);
    const t = setTimeout(() => setShouldRender(false), 300);
    return () => clearTimeout(t);
  }, [visible]);

  // Forces the opacity transition to animate from 0 — mirrors the source's
  // `void overlay.offsetHeight` reflow before adding 'show', done here via
  // a frame so the mount commits opacity:0 first.
  useEffect(() => {
    if (!visible) return;
    const frame = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(frame);
  }, [visible]);

  // Staged checklist advance — startLoadingStages/setActiveStage/
  // finishLoadingStages (lines 2257-2302). On hide, every stage is marked
  // done outright so a fast-resolving scan never leaves a row stuck
  // mid-spin during the fade-out.
  useEffect(() => {
    if (!visible) {
      setActiveIndex(stages.length);
      return;
    }

    setHeadlineEntered(false);
    const headlineFrame = requestAnimationFrame(() => setHeadlineEntered(true));
    setEnteredStages(stages.map(() => false));
    setActiveIndex(-1);

    const timers: ReturnType<typeof setTimeout>[] = [];
    stages.forEach((_, i) => {
      timers.push(
        setTimeout(() => {
          setEnteredStages(prev => prev.map((v, idx) => (idx === i ? true : v)));
        }, i * 100)
      );
    });
    stages.forEach((stage, i) => {
      timers.push(setTimeout(() => setActiveIndex(i), stage.delay));
    });

    return () => {
      cancelAnimationFrame(headlineFrame);
      timers.forEach(clearTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, hasPhoto, headlineText]);

  if (!shouldRender) return null;

  return (
    <div className={`${styles.loadingOverlay} ${shown ? styles.show : ''}`}>
      <div className={styles.loadingParticles}>
        {particles.map((p, i) => (
          <div
            key={i}
            className={styles.loadingParticle}
            style={
              {
                left: `${p.left}%`,
                '--drift': `${p.drift}px`,
                animationDuration: `${p.duration}s`,
                animationDelay: `${p.delay}s`,
              } as CSSProperties
            }
          />
        ))}
      </div>

      {hasPhoto && (
        <div className={styles.loadingFridgeZone}>
          <div className={styles.loadingFridge}>
            <div className={styles.loadingFridgeFreezerLine} />
            <div className={styles.loadingFridgeShelf} style={{ top: '33%' }} />
            <div className={styles.loadingFridgeShelf} style={{ top: '55%' }} />
            <div className={styles.loadingFridgeShelf} style={{ top: '75%' }} />
            <div className={styles.loadingFridgeHandle} />
            <div className={styles.loadingFridgeScanline} />
            <div className={styles.loadingFridgeDots} />
          </div>
        </div>
      )}

      <div className={styles.loadingStatusZone}>
        <div className={`${styles.loadingHeadline} ${headlineEntered ? styles.entered : ''}`}>{headlineText}</div>
        <div className={styles.loadingStages}>
          {stages.map((stage, i) => (
            <div
              key={i}
              className={[
                styles.loadingStage,
                enteredStages[i] ? styles.entered : '',
                i === activeIndex ? styles.active : '',
                i < activeIndex ? styles.done : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span className={styles.loadingStageIcon} />
              <span className={styles.loadingStageLabel}>{stage.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
