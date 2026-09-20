'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useScanStream } from '@/hooks/useScanStream';
import { usePhotoUpload } from '@/hooks/usePhotoUpload';
import { useYoutubeVideos } from '@/hooks/useYoutubeVideos';
import { useToast } from '@/hooks/useToast';
import { useAuth } from '@/hooks/useAuth';
import { usePrefetchProducts } from '@/hooks/useInstamartProducts';
import { useSelectedAddressId } from '@/lib/addressStore';
import { getItemsToOrder } from '@/hooks/useRecipeChecklist';
import { consumePendingOrder, savePendingOrder } from '@/lib/pendingOrder';
import { ConnectGate } from '@/components/auth/ConnectGate';
import { FoodOrdersSheet } from '@/components/results/FoodOrdersSheet';
import { InstamartOrdersSheet } from '@/components/results/InstamartOrdersSheet';
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
  const [focusIngredient, setFocusIngredient] = useState<string | null>(null);
  // Recreated per scan — resetResultTabs() (templates/index.html:3565).
  const [recipeDotDismissed, setRecipeDotDismissed] = useState(false);

  const photos = usePhotoUpload();
  const { state, startScan, toggleChecklistItem, reset, restore } = useScanStream();
  const { fetchVideos } = useYoutubeVideos();
  const toast = useToast();
  const auth = useAuth();
  const connected = auth.status === 'connected';

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

  // Groceries go through the staged Instamart sheet (real products -> real
  // cart -> explicit Place order); it also works with nothing missing, offering
  // just the add-on suggestions.
  const handleOrderGroceries = useCallback(() => {
    setFocusIngredient(null);
    setOrderSheetOpen(true);
  }, []);

  // A checklist row's Instamart match opens the same sheet, scrolled to that item.
  const handleOpenProduct = useCallback((ingredientName: string) => {
    setFocusIngredient(ingredientName);
    setOrderSheetOpen(true);
  }, []);

  // Start searching Instamart the moment the missing list is known, not when the sheet opens.
  const missingNames = useMemo(() => getItemsToOrder(state.checklist).map(i => i.name), [state.checklist]);
  usePrefetchProducts(missingNames, connected, useSelectedAddressId());

  // Stashes just enough state to resume the in-progress order after the
  // full-page OAuth redirect a "Connect with Swiggy" click triggers — see
  // lib/pendingOrder.ts. Two call sites: the order sheet's inline CTA
  // (reopens the sheet with top-up picks intact) and OrderResultCard's CTA
  // for the sheet-less order_dish flow (no top-ups, sheet not reopened).
  const handleSheetConnectClick = useCallback((selectedTopUpNames: string[]) => {
    savePendingOrder({
      recommendedMeal: state.recommendedMeal ?? '',
      reasoning: state.reasoning,
      checklist: state.checklist,
      topUpSuggestions: state.topUpSuggestions,
      selectedTopUpNames,
      reopenOrderSheet: true,
    });
  }, [state.recommendedMeal, state.reasoning, state.checklist, state.topUpSuggestions]);

  const handleResultCardConnectClick = useCallback(() => {
    savePendingOrder({
      recommendedMeal: state.recommendedMeal ?? '',
      reasoning: state.reasoning,
      checklist: state.checklist,
      topUpSuggestions: state.topUpSuggestions,
      selectedTopUpNames: [],
      reopenOrderSheet: false,
    });
  }, [state.recommendedMeal, state.reasoning, state.checklist, state.topUpSuggestions]);

  // Resumes state stashed in lib/pendingOrder.ts right before a "Connect
  // with Swiggy" click sent the user through the full-page OAuth redirect
  // (/auth/login -> Swiggy -> /auth/callback -> back here). The lazy
  // initializer reads (and clears) the stash exactly once, synchronously,
  // before anything else can — consumePendingOrder() is one-shot, so it
  // must not be called a second time on the same mount.
  const [restoredOrder] = useState(() => consumePendingOrder());

  useEffect(() => {
    if (!restoredOrder) return;
    restore({
      recommendedMeal: restoredOrder.recommendedMeal,
      reasoning: restoredOrder.reasoning,
      checklist: restoredOrder.checklist,
      topUpSuggestions: restoredOrder.topUpSuggestions,
    });
    setTab('order');
    if (restoredOrder.reopenOrderSheet) setOrderSheetOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The gate can appear mid-session (a 5-day Swiggy token expiring): keep the recipe if there is one.
  const handleGateConnectClick = useCallback(() => {
    if (state.checklist.length > 0) handleResultCardConnectClick();
  }, [state.checklist.length, handleResultCardConnectClick]);

  const showLanding = state.phase === 'idle';
  // Ruling B: once the scan screen is up it stays up until its OWN
  // onRevealComplete fires — `complete`/`error` can (and for a fast backend
  // routinely does) move `phase` off 'photo-scanning' mid-reveal, and that
  // must not yank the screen and strand the reveal timers. Hence keyed on
  // the reveal flag, not `phase`. The one `phase`-ish term left is
  // step1Received (not `detectedIngredients.length` — a scan that finds
  // zero ingredients also leaves that array empty, and must still get its
  // reveal/settle beat rather than being treated as "step1 never fired"):
  // an error before step1 means no reveal will ever run, so the screen must
  // give way to the error card.
  const showPhotoScan =
    state.hasPhoto &&
    !photoDetectionRevealed &&
    (state.phase === 'photo-scanning' || state.step1Received);
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

      <main id="main-content">
      {!connected ? (
        <ConnectGate checking={auth.status === 'loading'} onConnectClick={handleGateConnectClick} />
      ) : (
      <>
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
        detectedIngredients={state.step1Received ? state.detectedIngredients : null}
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
          onOpenProduct={handleOpenProduct}
          focusIngredient={focusIngredient}
          orderSheetOpen={orderSheetOpen}
          onCloseOrderSheet={() => setOrderSheetOpen(false)}
          onSheetConnectClick={handleSheetConnectClick}
          initialSelectedTopUpNames={restoredOrder?.reopenOrderSheet ? restoredOrder.selectedTopUpNames : undefined}
          onResultCardConnectClick={handleResultCardConnectClick}
          onResetToLanding={handleResetToLanding}
        />
      )}
      </>
      )}
      </main>

      {connected && <InstamartOrdersSheet />}
      {connected && <FoodOrdersSheet />}
      <Toast message={toast.message} />
    </div>
  );
}
