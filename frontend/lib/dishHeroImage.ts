// Dish hero image waterfall — ported from templates/index.html:3591-3652
// (tryLoadImage, loadDishHeroImage). Text/placeholder show immediately (no
// network wait, handled by the caller); the real photo is best-effort from
// three sources tried in order until one actually loads: Unsplash first
// (better quality/framing for a hero image than a YouTube thumbnail),
// TheMealDB (free, no key, strong for common/global dishes), then a
// YouTube recipe video's thumbnail as the last resort before the
// placeholder. Never throws — if every source fails or times out, callers
// get `null` and keep showing the placeholder initial.

function tryLoadImage(url: string): Promise<boolean> {
  return new Promise(resolve => {
    const img = new Image();
    let settled = false;
    const finish = (ok: boolean) => {
      if (!settled) {
        settled = true;
        resolve(ok);
      }
    };
    img.onload = () => finish(true);
    img.onerror = () => finish(false);
    img.src = url;
    setTimeout(() => finish(false), 5000);
  });
}

interface DishImageResponse {
  found?: boolean;
  image_url?: string;
}

interface MealDbResponse {
  meals?: Array<{ strMealThumb?: string }>;
}

// Cache keyed on dish name, storing the final resolved image URL (or null
// if the waterfall exhausted every source). Broader than the old
// cachedYoutubeDish/cachedYoutubeData pattern (which only cached the
// YouTube leg) but still satisfies "cached per dish name" — the injected
// fetchYoutubeFirstThumbnail is expected to be backed by its own shared
// cache (Task 12) so this cache and that one don't need to be the same Map.
const dishImageCache = new Map<string, string | null>();

/**
 * Resolves a dish's hero image via a Unsplash → TheMealDB → YouTube
 * waterfall, returning the first URL that actually loads, or null if all
 * three sources fail/time out.
 *
 * `fetchYoutubeFirstThumbnail` is injected rather than called directly so
 * it can share a cache with the YouTube carousel (Task 12) — mirrors the
 * old code's cachedYoutubeDish/cachedYoutubeData sharing between
 * loadDishHeroImage() and fetchYoutubeVideos().
 */
export async function resolveDishHeroImage(
  dishName: string,
  fetchYoutubeFirstThumbnail: () => Promise<string>
): Promise<string | null> {
  if (dishImageCache.has(dishName)) return dishImageCache.get(dishName)!;

  // Source 1 — Unsplash
  try {
    const uRes = await fetch(`/api/dish-image?dish=${encodeURIComponent(dishName)}`);
    const uData: DishImageResponse = await uRes.json();
    if (uData.found && uData.image_url && (await tryLoadImage(uData.image_url))) {
      dishImageCache.set(dishName, uData.image_url);
      return uData.image_url;
    }
  } catch {
    /* fall through */
  }

  // Source 2 — TheMealDB
  try {
    const mealRes = await fetch(
      `https://www.themealdb.com/api/json/v1/1/search.php?s=${encodeURIComponent(dishName)}`
    );
    const mealData: MealDbResponse = await mealRes.json();
    const thumb = mealData?.meals?.[0]?.strMealThumb;
    if (thumb && (await tryLoadImage(thumb))) {
      dishImageCache.set(dishName, thumb);
      return thumb;
    }
  } catch {
    /* fall through */
  }

  // Source 3 — YouTube recipe video thumbnail
  try {
    const thumb = await fetchYoutubeFirstThumbnail();
    if (thumb && (await tryLoadImage(thumb))) {
      dishImageCache.set(dishName, thumb);
      return thumb;
    }
  } catch {
    /* fall through */
  }

  dishImageCache.set(dishName, null);
  return null;
}
