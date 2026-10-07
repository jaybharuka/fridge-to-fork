'use client';
import { useRef, useState } from 'react';
import { Camera, Check, Images, Plus, X } from 'lucide-react';
import type { UsePhotoUpload } from '@/hooks/usePhotoUpload';
import { Button } from '@/components/ui/Button';
import { Sheet } from '@/components/ui/Sheet';
import { fridgeHint } from '@/lib/landingAction';
import styles from './landing.module.css';

const MAX_PHOTOS = 3;

// Parent (page.tsx, Task 14) owns the single usePhotoUpload() instance —
// this component is a controlled view over it, mirroring DishInput's
// controlled-props pattern (see the note in DishInput.tsx).
type PhotoUploadAreaProps = Pick<UsePhotoUpload, 'photos' | 'thumbnailUrls' | 'addPhoto' | 'removePhoto'> & {
  /** A dish is already typed: the hint after a photo is added says the recipe will be built around the fridge. */
  hasDish: boolean;
};

// Ported from templates/index.html:1818-1824 (markup), 4223-4243
// (updatePhotoUI / input onChange). Toggles between a single "Scan Fridge"
// button and a thumbnail-row + inline "+" once at least one photo is added.
//
// TWO separate hidden file inputs, not one — a single <input type="file"
// accept="image/*"> was tried first (relying on the browser to present a
// combined camera-or-gallery chooser on its own) and failed on a real
// device: Android 14/15 + Chrome now routes a plain, capture-less input to
// the OS's newer built-in Photo Picker, which has NO camera option at all
// (a real, dated, cross-referenced platform change, not a one-off bug).
// Two explicit buttons avoids depending on any single input's automatic
// chooser behavior: the camera button's input always forces the camera
// (capture's one reliable, universal effect, on both iOS Safari and
// Android Chrome); the gallery button's input never has `capture`, so
// gallery access is always available through it regardless of which exact
// picker UI a given browser/OS version happens to show for it.
export function PhotoUploadArea({ photos, thumbnailUrls, addPhoto, removePhoto, hasDish }: PhotoUploadAreaProps) {
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  async function handleFiles(files: FileList | null) {
    if (!files) return;
    const remaining = MAX_PHOTOS - photos.length;
    const toAdd = Array.from(files).slice(0, Math.max(remaining, 0));
    for (const file of toAdd) {
      // Stop at the first photo that fails: the likely cause is memory pressure, and the next one would only repeat it.
      if (!(await addPhoto(file))) break;
    }
    if (cameraInputRef.current) cameraInputRef.current.value = '';
    if (galleryInputRef.current) galleryInputRef.current.value = '';
  }

  function openCamera() {
    setPickerOpen(false);
    cameraInputRef.current?.click();
  }

  function openGallery() {
    setPickerOpen(false);
    galleryInputRef.current?.click();
  }

  return (
    <section className={styles.photoUploadArea} aria-label="Your fridge (optional)">
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        style={{ display: 'none' }}
        onChange={e => handleFiles(e.target.files)}
      />
      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        multiple
        style={{ display: 'none' }}
        onChange={e => handleFiles(e.target.files)}
      />
      <div className={styles.fieldLabel}>
        <span>Your fridge</span>
        <span className={styles.optionalChip}>Optional</span>
      </div>
      <div className={styles.fridgeCard}>
      {photos.length === 0 ? (
        <>
          <div className={styles.fridgeCardTop}>
            <div className={styles.fridgeIcon} aria-hidden="true"><Camera size={20} /></div>
            <div>
              <p className={styles.fridgeTitle}>No dish in mind?</p>
              <p className={styles.fridgeText}>Snap your fridge and we&apos;ll suggest what to cook.</p>
            </div>
          </div>
          <Button variant="secondary" size="sm" icon={<Camera size={16} />} onClick={() => setPickerOpen(true)}>
            Add a fridge photo
          </Button>
        </>
      ) : (
        <>
        <div className={styles.photoThumbnailRow}>
          {thumbnailUrls.map((url, i) => (
            <div key={url} className={styles.photoThumb}>
              <img src={url} alt={`Fridge photo ${i + 1}`} />
              <button
                type="button"
                className={styles.photoThumbRemove}
                onClick={() => removePhoto(i)}
                aria-label={`Remove photo ${i + 1}`}
              >
                <X size={12} />
              </button>
            </div>
          ))}
          {photos.length < MAX_PHOTOS && (
            <button
              type="button"
              className={styles.addPhotoPlus}
              onClick={() => setPickerOpen(true)}
              aria-label="Add another photo"
            >
              <Plus />
            </button>
          )}
        </div>
        <p className={styles.fridgeHint} role="status"><Check aria-hidden="true" /><span>{fridgeHint(hasDish ? 'dish' : '')}</span></p>
        </>
      )}
      </div>

      <Sheet open={pickerOpen} onClose={() => setPickerOpen(false)} ariaLabel="Add a fridge photo" title="Add a fridge photo">
        <div className={styles.photoPickerOptions}>
          <Button variant="secondary" icon={<Camera size={18} />} onClick={openCamera}>
            Take Photo
          </Button>
          <Button variant="secondary" icon={<Images size={18} />} onClick={openGallery}>
            Choose from Gallery
          </Button>
        </div>
      </Sheet>
    </section>
  );
}
