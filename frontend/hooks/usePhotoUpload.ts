'use client';
import { useCallback, useEffect, useState } from 'react';

const MAX_PHOTOS = 3;
const MAX_DIMENSION = 1200;
const JPEG_QUALITY = 0.82;

// Ported from templates/index.html:4141-4168 (compressImage) — resizes to
// fit within maxWidth/maxHeight (preserving aspect ratio) and re-encodes as
// JPEG at `quality` via an off-screen canvas.
function compressImage(file: File, maxWidth: number, maxHeight: number, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        let width = img.width;
        let height = img.height;
        if (width > maxWidth) {
          height = Math.round((height * maxWidth) / width);
          width = maxWidth;
        }
        if (height > maxHeight) {
          width = Math.round((width * maxHeight) / height);
          height = maxHeight;
        }
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('Canvas 2D context unavailable'));
          return;
        }
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob(
          blob => (blob ? resolve(blob) : reject(new Error('Image compression failed'))),
          'image/jpeg',
          quality
        );
      };
      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = e.target?.result as string;
    };
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

export interface UsePhotoUpload {
  photos: File[];
  thumbnailUrls: string[];
  addPhoto: (file: File) => Promise<void>;
  removePhoto: (index: number) => void;
  clear: () => void;
}

// Ported from templates/index.html:4174-4218 (addPhoto/removePhoto/
// clearFridgePhotos). Object-URL lifecycle (previously scattered manual
// URL.revokeObjectURL calls in renderPhotoThumbnails(), line 4193) is
// consolidated into one effect keyed on `photos`.
export function usePhotoUpload(): UsePhotoUpload {
  const [photos, setPhotos] = useState<File[]>([]);
  const [thumbnailUrls, setThumbnailUrls] = useState<string[]>([]);

  useEffect(() => {
    const urls = photos.map(f => URL.createObjectURL(f));
    setThumbnailUrls(urls);
    return () => urls.forEach(u => URL.revokeObjectURL(u));
  }, [photos]);

  const addPhoto = useCallback(async (file: File) => {
    if (photos.length >= MAX_PHOTOS) return;
    const blob = await compressImage(file, MAX_DIMENSION, MAX_DIMENSION, JPEG_QUALITY);
    setPhotos(prev =>
      prev.length >= MAX_PHOTOS ? prev : [...prev, new File([blob], file.name, { type: 'image/jpeg' })]
    );
  }, [photos.length]);

  const removePhoto = useCallback((index: number) => {
    setPhotos(prev => prev.filter((_, i) => i !== index));
  }, []);

  const clear = useCallback(() => setPhotos([]), []);

  return { photos, thumbnailUrls, addPhoto, removePhoto, clear };
}
