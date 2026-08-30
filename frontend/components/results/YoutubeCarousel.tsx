'use client';

import { useEffect, useState } from 'react';
import { Video } from 'lucide-react';
import type { YoutubeData, YoutubeVideo } from '@/hooks/useYoutubeVideos';
import styles from './results.module.css';

interface YoutubeCarouselProps {
  dishName: string;
  fetchVideos: (dishName: string) => Promise<YoutubeData>;
}

// Ported from templates/index.html:3378-3448 (renderYouTubeEmbed /
// buildYouTubeCarouselHtml / switchYouTubeVideo), 691-748 (CSS).
// Best-effort recipe video lookup — a clean empty-state placeholder on any
// failure or empty result, never an error message.
//
// lucide-react (v1.37, installed here) dropped brand icons — there's no
// "youtube" icon anymore, so `Video` (a generic camera/film icon) stands in
// for it, matching the closest available shape.
export function YoutubeCarousel({ dishName, fetchVideos }: YoutubeCarouselProps) {
  const [videos, setVideos] = useState<YoutubeVideo[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [mainSrc, setMainSrc] = useState('');

  useEffect(() => {
    let cancelled = false;
    setVideos([]);
    setActiveIndex(0);
    setMainSrc('');
    fetchVideos(dishName).then(data => {
      if (cancelled) return;
      setVideos(data.videos);
      setMainSrc(data.videos[0]?.embed_url ?? '');
    });
    return () => {
      cancelled = true;
    };
  }, [dishName, fetchVideos]);

  const thumbs = videos.slice(0, 4);

  function switchVideo(video: YoutubeVideo, index: number) {
    // autoplay=1 needs its own separator logic since embed_url already has
    // its own query string (built server-side with "?rel=0...").
    setMainSrc(`${video.embed_url}&autoplay=1`);
    setActiveIndex(index);
  }

  return (
    <div className={styles.sectionReveal}>
      <div className={styles.sectionLabel}>
        <Video /> Watch recipe video
      </div>
      <div className={styles.ytVideoWrap}>
        {!videos.length ? (
          <div className={styles.emptyState}>
            <Video size={32} style={{ color: 'var(--text-muted)', display: 'block', margin: '0 auto 8px' }} />
            No video found for this dish
          </div>
        ) : (
          <>
            <div className={styles.ytIframeWrap}>
              <iframe
                src={mainSrc}
                frameBorder="0"
                allowFullScreen
                style={{ width: '100%', height: '100%', display: 'block' }}
              />
            </div>
            {thumbs.length > 1 && (
              <div className={styles.ytThumbnails}>
                {thumbs.map((v, i) => (
                  <button
                    key={v.id}
                    type="button"
                    className={`${styles.ytThumbCard} ${i === activeIndex ? styles.ytThumbActive : ''}`}
                    aria-label={`Play ${v.title || 'recipe video'}`}
                    onClick={() => switchVideo(v, i)}
                  >
                    <div className={styles.ytThumbImgWrap}>
                      <img src={v.thumbnail} alt={v.title || ''} />
                      {i === activeIndex && <span className={styles.ytPlayingBadge}>PLAYING</span>}
                    </div>
                    <div className={styles.ytThumbTitle}>{v.title || ''}</div>
                    <div className={styles.ytThumbChannel}>{v.channel || ''}</div>
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
