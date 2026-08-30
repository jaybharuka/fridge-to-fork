'use client';

import { useRef, useCallback } from 'react';

export interface YoutubeVideo {
  id: string;
  title: string;
  channel: string;
  thumbnail: string;
  embed_url: string;
}

export interface YoutubeData {
  videos: YoutubeVideo[];
  first_thumbnail: string;
}

// Port of fetchYoutubeVideos()'s cachedYoutubeDish/cachedYoutubeData caching
// (templates/index.html:3475-3489). Instantiate this hook ONCE at the
// page.tsx level (Task 14) and pass the returned `fetchVideos` down to both
// DishHeroSection (as `fetchYoutubeFirstThumbnail`) and YoutubeCarousel, so
// they share one cache/one API call — mirrors the original's module-level
// shared cache between loadDishHeroImage() and fetchYoutubeVideos().
export function useYoutubeVideos() {
  const cache = useRef<{ dish: string; data: YoutubeData } | null>(null);

  const fetchVideos = useCallback(async (dishName: string): Promise<YoutubeData> => {
    if (cache.current?.dish === dishName) return cache.current.data;
    try {
      const res = await fetch(`/api/youtube?dish=${encodeURIComponent(dishName)}`);
      const data: YoutubeData = await res.json();
      cache.current = { dish: dishName, data };
      return data;
    } catch {
      return { videos: [], first_thumbnail: '' };
    }
  }, []);

  return { fetchVideos };
}
