'use client';

import { useCallback, useState } from 'react';
import { useScanStream } from '@/hooks/useScanStream';
import { usePhotoUpload } from '@/hooks/usePhotoUpload';
import { useYoutubeVideos } from '@/hooks/useYoutubeVideos';
import { useToast } from '@/hooks/useToast';
import { getItemsToOrder } from '@/hooks/useRecipeChecklist';
import { Landing } from '@/components/landing/Landing';
import { LoadingOverlay } from '@/components/loading/LoadingOverlay';
import { PhotoScanScreen } from '@/components/loading/PhotoScanScreen';
import { AppHeader } from '@/components/results/AppHeader';
import { Results } from '@/components/results/Results';
import { Toast } from '@/components/results/Toast';

// Replaces startScan()/resetToLanding()/handleEvent()'s DOM orchestration
// (templates/index.html:4033-4041, 4543-4549, 4614-4624) with phase-driven
// rendering: useScanStream owns the phase, this owns what each phase shows.
export default function Home() {
  const [targetDish, setTargetDish] = useState('');
  const [servings, setServings] = useState(2);
  const [tab, setTab] = useState<'order' | 'recipe'>('order');
  // Gates the handoff from PhotoScanScreen to Results. Deliberately NOT
  // derived from `phase`: the photo-scan screen goes up the instant Get
  // Recipe is tapped and stays up through its own reveal animation, which
  // outlives step1 and can outlive `complete`.
  const [photoDetectionRevealed, setPhotoDetectionRevealed] = useState(false);
  const [orderSheetOpen, setOrderSheetOpen] = useState(false);
  // Recreated per scan — resetResultTabs() (templates/index.html:3565).
  const [recipeDotDismissed, setRecipeDotDismissed] = useState(false);

  const photos = usePhotoUpload();
  const { state, startScan, placeOrder, toggleChecklistItem, reset } = useScanStream();
  const { fetchVideos } = useYoutubeVideos();
  const toast = useToast();

  const dishName = state.recommendedMeal ?? '';
  const heroPhotoUrl = photos.thumbnailUrls[0] ?? '';

  // One shared cache for DishHeroSection and YoutubeCarousel. Memoized —
  // DishHeroSection's effect keys on this callback's identity.
  const fetchYoutubeFirstThumbnail = useCallback(
    () => fetchVideos(dishName).then(d => d.first_thumbnail),
    [fetchVideos, dishName]
  );

  const handleGetRecipe = useCallback(() => {
    setTab('order');
    setPhotoDetectionRevealed(false);
    setRecipeDotDismissed(false);
    if (photos.photos.length > 0) {
      startScan('photo', { files: photos.photos, targetDish, servings });
    } else {
      startScan('recipe', { targetDish, servings });
    }
  }, [photos.photos, targetDish, servings, startScan]);

  const handleResetToLanding = useCallback(() => {
    reset();
    photos.clear();
    setTab('order');
    setPhotoDetectionRevealed(false);
    setOrderSheetOpen(false);
    setRecipeDotDismissed(false);
  }, [reset, photos]);

  const handleTabChange = useCallback((next: 'order' | 'recipe') => {
    if (next === 'recipe') setRecipeDotDismissed(true);
    setTab(next);
  }, []);

  // confirmOrderGroceries() — the preview sheet only exists to review what's
  // missing, so skip it outright when nothing is (lines 3900-3911).
  const handleOrderGroceries = useCallback(() => {
    if (getItemsToOrder(state.checklist).length === 0) {
      placeOrder('order_groceries', state.recommendedMeal ?? '', []);
      return;
    }
    setOrderSheetOpen(true);
  }, [state.checklist, state.recommendedMeal, placeOrder]);

  const handleConfirmOrderSheet = useCallback(() => {
    setOrderSheetOpen(false);
    placeOrder(
      'order_groceries',
      state.recommendedMeal ?? '',
      getItemsToOrder(state.checklist).map(i => i.name)
    );
  }, [state.checklist, state.recommendedMeal, placeOrder]);

  const showLanding = state.phase === 'idle';
  // Ruling B: once the scan screen is up it stays up until its OWN
  // onRevealComplete fires — `complete`/`error` can (and for a fast backend
  // routinely does) move `phase` off 'photo-scanning' mid-reveal, and that
  // must not yank the screen and strand the reveal timers. Hence keyed on
  // the reveal flag, not `phase`. The one `phase`-ish term left is the
  // detected-ingredients check: an error before step1 means no reveal will
  // ever run, so the screen must give way to the error card.
  const showPhotoScan =
    state.hasPhoto &&
    !photoDetectionRevealed &&
    (state.phase === 'photo-scanning' || state.detectedIngredients.length > 0);
  // "Has the user actually seen results yet" — drives OrderResultCard's
  // inline-strip vs. full-page error variant. `phase === 'results'` alone
  // misses an error that lands after the reveal finished but before
  // 'complete' (phase is 'error' by then, but results ARE on screen).
  const resultsAlreadyShown = state.phase === 'results' || (state.hasPhoto && photoDetectionRevealed);
  // Mounted for the whole photo-scanning phase (behind the fixed overlay) so
  // FridgeSummaryHeader's thumbnail already occupies its final position when
  // the crossfade starts — see its comment on the FLIP-clone replacement.
  const showResults =
    state.phase === 'results' || state.phase === 'error' || state.phase === 'photo-scanning';

  return (
    <div>
      <AppHeader />

      {showLanding && (
        <Landing
          targetDish={targetDish}
          onTargetDishChange={setTargetDish}
          servings={servings}
          onServingsChange={setServings}
          photos={photos}
          onGetRecipe={handleGetRecipe}
          submitState="ready"
        />
      )}

      <LoadingOverlay
        visible={state.phase === 'loading'}
        hasPhoto={state.hasPhoto}
        headlineText={targetDish ? `Looking up ${targetDish}` : 'Finding your recipe'}
      />

      <PhotoScanScreen
        visible={showPhotoScan}
        photoUrls={photos.thumbnailUrls}
        detectedIngredients={state.detectedIngredients.length ? state.detectedIngredients : null}
        onRevealComplete={() => setPhotoDetectionRevealed(true)}
        onRetry={handleGetRecipe}
      />

      {showResults && (
        <Results
          state={state}
          servings={servings}
          tab={tab}
          onTabChange={handleTabChange}
          onLockedTabClick={() => toast.show('Still loading your recipe...')}
          recipeHasUnreadDot={!recipeDotDismissed}
          heroPhotoUrl={heroPhotoUrl}
          fridgeVisible={!showPhotoScan}
          resultsAlreadyShown={resultsAlreadyShown}
          fetchVideos={fetchVideos}
          fetchYoutubeFirstThumbnail={fetchYoutubeFirstThumbnail}
          onToggleChecklistItem={toggleChecklistItem}
          onOrderGroceries={handleOrderGroceries}
          onOrderDish={() => placeOrder('order_dish', state.recommendedMeal ?? '', [])}
          orderSheetOpen={orderSheetOpen}
          onCloseOrderSheet={() => setOrderSheetOpen(false)}
          onConfirmOrderSheet={handleConfirmOrderSheet}
          onResetToLanding={handleResetToLanding}
        />
      )}

      <Toast message={toast.message} />
    </div>
  );
}
