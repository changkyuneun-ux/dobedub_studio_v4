export const BATCH_IMAGE_MIME_PREFIX = "image/";
export const BATCH_IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".webp"]);

export function isBatchImageFile(file: File): boolean {
  if (file.type.startsWith(BATCH_IMAGE_MIME_PREFIX)) {
    return true;
  }
  const lowerName = file.name.toLowerCase();
  return [...BATCH_IMAGE_EXTENSIONS].some((extension) => lowerName.endsWith(extension));
}

export function batchFolderName(files: File[]): string {
  const first = files.find((file) => (file as File & { webkitRelativePath?: string }).webkitRelativePath);
  const relative = first ? (first as File & { webkitRelativePath?: string }).webkitRelativePath || "" : "";
  const folder = relative.split("/").filter(Boolean)[0];
  return folder || "selected-folder";
}

export function batchImageFiles(files: FileList | File[]): File[] {
  return Array.from(files).filter(isBatchImageFile);
}
