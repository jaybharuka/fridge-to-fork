'use client';
import { useCallback, useEffect, useState } from 'react';
import { fitWithin } from '@/lib/imageSize';

const MAX_PHOTOS = 3;
const MAX_DIMENSION = 1200;
const JPEG_QUALITY = 0.82;

export const PHOTO_ERROR_MESSAGE = "This photo couldn't be processed. Try a smaller photo, or add fewer photos at once.";

// Draws `source` onto a canvas of exactly width x height (the TARGET size, never the source's own) and encodes it. The
// canvas is zeroed afterwards: iOS Safari keeps a canvas's backing store until GC, and it has a global canvas memory cap.
function canvasToJpeg(source: CanvasImageSource, width: number, height: number, quality: number, afterDraw?: () => void): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.reject(new Error('Canvas 2D context unavailable'));
  ctx.drawImage(source, 0, 0, width, height);
  afterDraw?.(); // the decoded source is no longer needed: let the caller free it BEFORE the (slow) encode
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      blob => {
        canvas.width = 0;
        canvas.height = 0;
        if (blob) resolve(blob);
        else reject(new Error('Image compression failed'));
      },
      'image/jpeg',
      quality
    );
  });
}

// A modern phone camera photo (12MP+, sometimes HEIC) is routinely
// 20-50MB+. The previous implementation (FileReader.readAsDataURL -> <img>
// -> canvas) base64-encodes the WHOLE raw file into a string (~33% larger
// than the file) and then decodes that into a full-resolution bitmap
// BEFORE any downscaling happens — original file + base64 string + full-res
// decoded bitmap all resident in memory at once (measured against a real
// 4032x3024/8.4MB synthetic test JPEG: an 11.2MB base64 string plus a
// 46.5MB decoded RGBA bitmap on top of the 8.4MB file — ~66MB simultaneous
// for ONE photo, before any resizing). That's what crashed real phones with
// a browser-level "low memory" error, before the request was ever sent.
//
// createImageBitmap(file, { resizeWidth }) lets the browser decode and
// downscale in one native step where it is supported (e.g. libjpeg's IDCT
// scaling in Chromium), with no base64 copy ever made.
//
// Safari's support tables list createImageBitmap's resize options as unsupported: the options are ignored and a FULL-size
// bitmap comes back (a 12MP photo is ~48MB decoded). So the options are only a hint here: the output size is always
// computed from the bitmap that actually came back and drawn at THAT target size, so a canvas is never sized from the
// source. (Stepped/progressive downscaling was considered and rejected: the decoded source is already in memory and
// intermediate canvases only add to it, so it would improve quality, not memory.)
async function compressImage(file: File, maxWidth: number, maxHeight: number, quality: number): Promise<Blob> {
  if (typeof createImageBitmap === 'function') {
    let bitmap: ImageBitmap | null = null;
    try {
      bitmap = await createImageBitmap(file, { resizeWidth: maxWidth, resizeQuality: 'medium' });
    } catch {
      // Only a failed DECODE falls through to the <img> path below, e.g. a format createImageBitmap won't take (iOS can
      // decode HEIC via <img>). A later failure (draw/encode) must not trigger a second full-size decode on top of it.
    }
    if (bitmap) {
      const decoded = bitmap;
      try {
        const { width, height } = fitWithin(decoded.width, decoded.height, maxWidth, maxHeight);
        // Freed right after the draw, before the slow encode; close() is idempotent so the finally is just the safety net.
        return await canvasToJpeg(decoded, width, height, quality, () => decoded.close());
      } finally {
        decoded.close();
      }
    }
  }

  const objectUrl = URL.createObjectURL(file);
  const img = new Image();
  try {
    return await new Promise<Blob>((resolve, reject) => {
      img.onload = () => {
        const { width, height } = fitWithin(img.naturalWidth, img.naturalHeight, maxWidth, maxHeight);
        canvasToJpeg(img, width, height, quality).then(resolve, reject);
      };
      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = objectUrl;
    });
  } finally {
    img.onload = null;
    img.onerror = null;
    img.src = ''; // drops the decoded full-size pixels instead of waiting for GC
    URL.revokeObjectURL(objectUrl);
  }
}

export interface UsePhotoUpload {
  photos: File[];
  thumbnailUrls: string[];
  /** Resolves true when the photo was added, false when it couldn't be processed (the user has been told via onError). */
  addPhoto: (file: File) => Promise<boolean>;
  removePhoto: (index: number) => void;
  clear: () => void;
}

// Ported from templates/index.html:4174-4218 (addPhoto/removePhoto/
// clearFridgePhotos). Object-URL lifecycle (previously scattered manual
// URL.revokeObjectURL calls in renderPhotoThumbnails(), line 4193) is
// consolidated into one effect keyed on `photos`.
export function usePhotoUpload(onError?: (message: string) => void): UsePhotoUpload {
  const [photos, setPhotos] = useState<File[]>([]);
  const [thumbnailUrls, setThumbnailUrls] = useState<string[]>([]);

  useEffect(() => {
    const urls = photos.map(f => URL.createObjectURL(f));
    setThumbnailUrls(urls);
    return () => urls.forEach(u => URL.revokeObjectURL(u));
  }, [photos]);

  const addPhoto = useCallback(async (file: File) => {
    if (photos.length >= MAX_PHOTOS) return false;
    let blob: Blob;
    try {
      blob = await compressImage(file, MAX_DIMENSION, MAX_DIMENSION, JPEG_QUALITY);
    } catch {
      onError?.(PHOTO_ERROR_MESSAGE); // a clear message, not an unhandled rejection that leaves the user guessing
      return false;
    }
    setPhotos(prev =>
      prev.length >= MAX_PHOTOS ? prev : [...prev, new File([blob], file.name, { type: 'image/jpeg' })]
    );
    return true;
  }, [photos.length, onError]);

  const removePhoto = useCallback((index: number) => {
    setPhotos(prev => prev.filter((_, i) => i !== index));
  }, []);

  const clear = useCallback(() => setPhotos([]), []);

  return { photos, thumbnailUrls, addPhoto, removePhoto, clear };
}
