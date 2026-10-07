'use client';

import type { UsePhotoUpload } from '@/hooks/usePhotoUpload';
import { DISABLED_HELP, hasDish, landingAction } from '@/lib/landingAction';
import { Hero } from './Hero';
import { DishInput } from './DishInput';
import { ServingsSelector } from './ServingsSelector';
import { GetRecipeButton } from './GetRecipeButton';
import { PhotoUploadArea } from './PhotoUploadArea';
import { PopularDishes } from './PopularDishes';
import styles from './landing.module.css';

interface LandingProps {
  targetDish: string;
  /** Shared by DishInput's own onChange and PopularDishes' onSelectDish —
   *  DishInput deliberately has no onSelectDish of its own (Task 5). */
  onTargetDishChange: (value: string) => void;
  servings: number;
  onServingsChange: (n: number) => void;
  photos: UsePhotoUpload;
  onGetRecipe: () => void;
  submitState: 'ready' | 'loading';
}

const HELP_ID = 'get-recipe-help';

// Assembles #landingSection — templates/index.html:1793-1898. Composition only: every piece owns its own markup and CSS
// module. Two independent, optional routes (a dish, a fridge photo) joined by "or", then the servings and one button whose
// label follows what was given (lib/landingAction.ts) and which stays disabled until there is a dish or a photo.
export function Landing({
  targetDish,
  onTargetDishChange,
  servings,
  onServingsChange,
  photos,
  onGetRecipe,
  submitState,
}: LandingProps) {
  const action = landingAction(targetDish, photos.photos.length);
  return (
    <>
      <Hero />
      <div className="wrap">
        <div className={`${styles.fieldLabel} ${styles.fieldLabelFirst}`}>
          <span>A dish in mind</span>
          <span className={styles.optionalChip}>Optional</span>
        </div>
        <DishInput value={targetDish} onChange={onTargetDishChange} />
        <div className={styles.orDivider} role="separator"><span>or</span></div>
        <PhotoUploadArea
          photos={photos.photos}
          thumbnailUrls={photos.thumbnailUrls}
          addPhoto={photos.addPhoto}
          removePhoto={photos.removePhoto}
          hasDish={hasDish(targetDish)}
        />
        <ServingsSelector value={servings} onChange={onServingsChange} />
        <GetRecipeButton
          state={submitState}
          label={action.label}
          onClick={onGetRecipe}
          disabled={!action.enabled}
          describedBy={action.enabled ? undefined : HELP_ID}
        />
        {!action.enabled && <p id={HELP_ID} className={styles.ctaHint}>{DISABLED_HELP}</p>}
        <div className="section-divider" />
        <PopularDishes onSelectDish={onTargetDishChange} />
      </div>
    </>
  );
}
