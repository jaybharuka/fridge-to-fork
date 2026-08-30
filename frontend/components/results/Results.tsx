'use client';

import { useCallback, useRef, useState } from 'react';
import type { ScanState } from '@/hooks/useScanStream';
import { getItemsToOrder } from '@/hooks/useRecipeChecklist';
import type { YoutubeData } from '@/hooks/useYoutubeVideos';
import { StickySummaryBar } from './StickySummaryBar';
import { ResultTabBar } from './ResultTabBar';
import { DishHeroSection } from './DishHeroSection';
import { FridgeSummaryHeader } from './FridgeSummaryHeader';
import { FridgeChipsDropdown } from './FridgeChipsDropdown';
import { FridgeLightbox } from './FridgeLightbox';
import { MealSuggestionsSection } from './MealSuggestionsSection';
import { IngredientChecklistCard } from './IngredientChecklistCard';
import { ChoiceCard } from './ChoiceCard';
import { ChecklistSkeleton, ChoiceSkeleton } from './ResultsSkeleton';
import { OrderResultCard } from './OrderResultCard';
import { OrderBottomSheet } from './OrderBottomSheet';
import { RecipeStepsSection } from './RecipeStepsSection';
import { YoutubeCarousel } from './YoutubeCarousel';
import styles from './results.module.css';

type ResultTab = 'order' | 'recipe';

interface ResultsProps {
  state: ScanState;
  servings: number;
  tab: ResultTab;
  onTabChange: (tab: ResultTab) => void;
  onLockedTabClick: () => void;
  recipeHasUnreadDot: boolean;
  /** Object URL of the first uploaded fridge photo — thumbnail + lightbox. */
  heroPhotoUrl: string;
  /** False while PhotoScanScreen is still covering the page; flips to true
   *  on its onRevealComplete, driving the shared-element crossfade. */
  fridgeVisible: boolean;
  /** True once results have actually been shown to the user — an error then
   *  renders as the inline strip rather than the full-page "try again" card. */
  resultsAlreadyShown: boolean;
  fetchVideos: (dishName: string) => Promise<YoutubeData>;
  fetchYoutubeFirstThumbnail: () => Promise<string>;
  onToggleChecklistItem: (index: number) => void;
  onOrderGroceries: () => void;
  onOrderDish: () => void;
  orderSheetOpen: boolean;
  onCloseOrderSheet: () => void;
  onConfirmOrderSheet: () => void;
  onResetToLanding: () => void;
}

// Assembles #resultsSection — templates/index.html:1940-2069. The sticky
// header group (summary bar + tab bar) sits above the scroll area; the dish
// hero is shared chrome living OUTSIDE both tab panels and shown only
// alongside the Order tab (switchResultTab(), lines 3548-3568).
export function Results({
  state,
  servings,
  tab,
  onTabChange,
  onLockedTabClick,
  recipeHasUnreadDot,
  heroPhotoUrl,
  fridgeVisible,
  resultsAlreadyShown,
  fetchVideos,
  fetchYoutubeFirstThumbnail,
  onToggleChecklistItem,
  onOrderGroceries,
  onOrderDish,
  orderSheetOpen,
  onCloseOrderSheet,
  onConfirmOrderSheet,
  onResetToLanding,
}: ResultsProps) {
  // Owned here rather than in page.tsx: nothing outside Results reads them.
  // The row ref MUST be the same object in both FridgeSummaryHeader and
  // FridgeChipsDropdown or the click-outside exclusion is inert.
  const fridgeRowRef = useRef<HTMLDivElement>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const closeDropdown = useCallback(() => setDropdownOpen(false), []);

  const dishName = state.recommendedMeal ?? '';
  const haveCount = state.checklist.filter(i => i.checked).length;
  const itemsToOrder = getItemsToOrder(state.checklist);

  // handleEvent()'s step2 branch — templates/index.html:4595-4598.
  const recSuggestion =
    state.suggestions.find(s => s.name === state.recommendedMeal) ?? state.suggestions[0];
  // step1 flips recipe mode straight into results while step2 is still
  // streaming, leaving several seconds with nothing on screen — the source
  // fills that gap with skeletons from step1 until each section's own event
  // lands (templates/index.html:4526-4527). awaiting_user_choice is the last
  // of those events, so it marks the end of the gap.
  const contentPending = !state.awaitingChoice && !state.scanError;

  const cookTime = recSuggestion?.prep_time_minutes ? `${recSuggestion.prep_time_minutes} min` : null;

  return (
    <div>
      <div className={styles.resultStickyHeader}>
        <StickySummaryBar
          visible={state.checklist.length > 0}
          haveCount={haveCount}
          total={state.checklist.length}
          dishName={dishName}
        />
        <ResultTabBar
          activeTab={tab}
          onTabChange={onTabChange}
          onLockedClick={onLockedTabClick}
          recipeUnlocked={state.recipeTabUnlocked}
          recipeHasUnreadDot={recipeHasUnreadDot}
        />
      </div>

      <div className="wrap">
        {/* Shared chrome — outside both panels, Order tab only. */}
        {tab === 'order' && dishName && (
          <DishHeroSection
            dishName={dishName}
            servings={servings}
            cookTime={cookTime}
            fetchYoutubeFirstThumbnail={fetchYoutubeFirstThumbnail}
          />
        )}

        {tab === 'order' && (
          <div>
            {/* Mounted from step1 on (well before the reveal ends, so it has
                settled into its final layout position by the time the
                crossfade starts) — but never rendered as an empty
                "0 items detected" row when a scan errored before step1. */}
            {state.hasPhoto && state.detectedIngredients.length > 0 && (
              <FridgeSummaryHeader
                rowRef={fridgeRowRef}
                visible={fridgeVisible}
                thumbUrl={heroPhotoUrl}
                ingredientCount={state.detectedIngredients.length}
                onOpenLightbox={() => setLightboxOpen(true)}
                onToggleDropdown={() => setDropdownOpen(o => !o)}
                dropdownOpen={dropdownOpen}
              >
                <FridgeChipsDropdown
                  ingredients={state.detectedIngredients}
                  matchedFridgeItems={state.matchedFridgeItems}
                  open={dropdownOpen}
                  onClose={closeDropdown}
                  onResetToLanding={onResetToLanding}
                  excludeRef={fridgeRowRef}
                />
              </FridgeSummaryHeader>
            )}

            {/* Only worth comparing when there's more than one option —
                templates/index.html:4585. */}
            {state.suggestions.length > 1 && (
              <MealSuggestionsSection
                suggestions={state.suggestions}
                recommendedMeal={state.recommendedMeal}
              />
            )}

            {/* No recipe_ingredients → no checklist at all (lines 3219-3223). */}
            {state.checklist.length > 0 ? (
              <IngredientChecklistCard
                checklist={state.checklist}
                toggleChecklistItem={onToggleChecklistItem}
              />
            ) : (
              contentPending && <ChecklistSkeleton />
            )}

            {state.awaitingChoice ? (
              <ChoiceCard
                recommendedMeal={dishName}
                reasoning={state.reasoning}
                itemsToOrder={itemsToOrder}
                onOrderGroceries={onOrderGroceries}
                onOrderDish={onOrderDish}
                orderPlacing={state.orderPlacing}
              />
            ) : (
              contentPending && <ChoiceSkeleton />
            )}

            <OrderResultCard
              result={state.orderResult}
              resultsAlreadyShown={resultsAlreadyShown}
              onRetry={onResetToLanding}
            />
          </div>
        )}

        {tab === 'recipe' && (
          <div>
            {dishName && <YoutubeCarousel dishName={dishName} fetchVideos={fetchVideos} />}
            <RecipeStepsSection steps={state.cookingSteps} />
          </div>
        )}
      </div>

      <FridgeLightbox open={lightboxOpen} imageUrl={heroPhotoUrl} onClose={() => setLightboxOpen(false)} />
      <OrderBottomSheet
        open={orderSheetOpen}
        itemsToOrder={itemsToOrder}
        topUpSuggestions={state.topUpSuggestions}
        onClose={onCloseOrderSheet}
        onConfirm={onConfirmOrderSheet}
      />
    </div>
  );
}
