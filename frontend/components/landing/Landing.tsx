'use client';

import type { UsePhotoUpload } from '@/hooks/usePhotoUpload';
import { Hero } from './Hero';
import { DishInput } from './DishInput';
import { ServingsSelector } from './ServingsSelector';
import { GetRecipeButton } from './GetRecipeButton';
import { PhotoUploadArea } from './PhotoUploadArea';
import { PopularDishes } from './PopularDishes';

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

// Assembles #landingSection — templates/index.html:1793-1898. Pure
// composition: every piece already owns its own markup and CSS module.
export function Landing({
  targetDish,
  onTargetDishChange,
  servings,
  onServingsChange,
  photos,
  onGetRecipe,
  submitState,
}: LandingProps) {
  return (
    <>
      <Hero />
      <div className="wrap">
        <DishInput value={targetDish} onChange={onTargetDishChange} />
        <ServingsSelector value={servings} onChange={onServingsChange} />
        <GetRecipeButton state={submitState} label="Get Recipe" onClick={onGetRecipe} />
        <PhotoUploadArea
          photos={photos.photos}
          thumbnailUrls={photos.thumbnailUrls}
          addPhoto={photos.addPhoto}
          removePhoto={photos.removePhoto}
        />
        <div className="section-divider" />
        <PopularDishes onSelectDish={onTargetDishChange} />
      </div>
    </>
  );
}
