'use client';
import { useCallback, useEffect, useState } from 'react';

const MAX_PHOTOS = 3;
const MAX_DIMENSION = 1200;
const JPEG_QUALITY = 0.82;

function scaledDimensions(width: number, height: number, maxWidth: number, maxHeight: number): { width: number; height: number } {
  if (width > maxWidth) {
    height = Math.round((height * maxWidth) / width);
    width = maxWidth;
  }
  if (height > maxHeight) {
    width = Math.round((width * maxHeight) / height);
    height = maxHeight;
  }
  return { width, height };
}

function canvasToJpeg(source: CanvasImageSource, width: number, height: number, quality: number): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.reject(new Error('Canvas 2D context unavailable'));
  ctx.drawImage(source, 0, 0, width, height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => (blob ? resolve(blob) : reject(new Error('Image compression failed'))), 'image/jpeg', quality);
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
// downscale in one native step, with only ONE axis specified so the
// browser computes the other preserving aspect ratio (per spec) — this is
// what lets browsers that support scaled JPEG decoding (e.g. libjpeg's IDCT
// scaling in Chromium) skip materializing the full-resolution bitmap
// entirely, rather than decoding full-size and then downsampling. No base64
// copy is ever made either way. Falls back to an object-URL <img> (still no
// base64 blow-up, just no native resize-on-decode) for the rare browser
// without createImageBitmap resize support.
async function compressImage(file: File, maxWidth: number, maxHeight: number, quality: number): Promise<Blob> {
  if (typeof createImageBitmap === 'function') {
    try {
      let bitmap = await createImageBitmap(file, { resizeWidth: maxWidth, resizeQuality: 'medium' });
      // Width-based scaling alone isn't enough for a portrait photo taller
      // than maxHeight even after being narrowed to maxWidth — correct with
      // one more resize, but FROM the already-small bitmap, not the
      // original file, so this second pass is cheap regardless.
      if (bitmap.height > maxHeight) {
        const corrected = await createImageBitmap(bitmap, { resizeHeight: maxHeight, resizeQuality: 'medium' });
        bitmap.close();
        bitmap = corrected;
      }
      try {
        return await canvasToJpeg(bitmap, bitmap.width, bitmap.height, quality);
      } finally {
        bitmap.close();
      }
    } catch {
      // Fall through to the <img> path below — e.g. a format createImageBitmap won't decode.
    }
  }

  const objectUrl = URL.createObjectURL(file);
  try {
    return await new Promise<Blob>((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const { width, height } = scaledDimensions(img.naturalWidth, img.naturalHeight, maxWidth, maxHeight);
        canvasToJpeg(img, width, height, quality).then(resolve, reject);
      };
      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = objectUrl;
    });
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
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
