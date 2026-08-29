'use client';
import { useRef } from 'react';
import { Camera, Plus, X } from 'lucide-react';
import type { UsePhotoUpload } from '@/hooks/usePhotoUpload';
import styles from './landing.module.css';

const MAX_PHOTOS = 3;

// Parent (page.tsx, Task 14) owns the single usePhotoUpload() instance —
// this component is a controlled view over it, mirroring DishInput's
// controlled-props pattern (see the note in DishInput.tsx).
type PhotoUploadAreaProps = Pick<UsePhotoUpload, 'photos' | 'thumbnailUrls' | 'addPhoto' | 'removePhoto'>;

// Ported from templates/index.html:1818-1824 (markup), 4223-4243
// (updatePhotoUI / input onChange). Toggles between a single "Scan Fridge"
// button and a thumbnail-row + inline "+" once at least one photo is added.
export function PhotoUploadArea({ photos, thumbnailUrls, addPhoto, removePhoto }: PhotoUploadAreaProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFiles(files: FileList | null) {
    if (!files) return;
    const remaining = MAX_PHOTOS - photos.length;
    const toAdd = Array.from(files).slice(0, Math.max(remaining, 0));
    for (const file of toAdd) {
      await addPhoto(file);
    }
    if (inputRef.current) inputRef.current.value = '';
  }

  return (
    <div className={styles.photoUploadArea}>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        style={{ display: 'none' }}
        onChange={e => handleFiles(e.target.files)}
      />
      {photos.length === 0 ? (
        <button type="button" className={styles.addPhotoBtn} onClick={() => inputRef.current?.click()}>
          <Camera size={18} />
          <span>Scan Fridge</span>
        </button>
      ) : (
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
              onClick={() => inputRef.current?.click()}
              aria-label="Add another photo"
            >
              <Plus />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
