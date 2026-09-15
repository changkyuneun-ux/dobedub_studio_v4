import { PDF_CMAP_URL, PDF_RENDER_SCALE, PDF_STANDARD_FONT_DATA_URL } from "./constants";
import type { SourceUnit } from "./types";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";

type PdfJsModule = typeof import("pdfjs-dist");

export function pdfRenderScale() {
  return PDF_RENDER_SCALE;
}

export async function countPdfPages(file: File): Promise<number> {
  const pdfjs = await loadPdfJs();
  const data = new Uint8Array(await file.arrayBuffer());
  const task = pdfjs.getDocument({
    data,
    disableAutoFetch: true,
    disableRange: true,
    disableStream: true,
    cMapUrl: PDF_CMAP_URL,
    cMapPacked: true,
    standardFontDataUrl: PDF_STANDARD_FONT_DATA_URL
  });
  const document = await task.promise;
  try {
    return document.numPages;
  } finally {
    await destroyPdfTask(task, document);
  }
}

export async function* iteratePdf(file: File, sourcePath: string, signal: AbortSignal): AsyncIterable<SourceUnit> {
  const pdfjs = await loadPdfJs();
  const data = new Uint8Array(await file.arrayBuffer());
  const task = pdfjs.getDocument({
    data,
    disableAutoFetch: true,
    disableRange: true,
    disableStream: true,
    cMapUrl: PDF_CMAP_URL,
    cMapPacked: true,
    standardFontDataUrl: PDF_STANDARD_FONT_DATA_URL
  });
  const document = await task.promise;
  try {
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      if (signal.aborted) throw signal.reason || new DOMException("Aborted", "AbortError");
      const page = await document.getPage(pageNumber);
      try {
        const viewport = page.getViewport({ scale: PDF_RENDER_SCALE });
        const canvas = new OffscreenCanvas(Math.ceil(viewport.width), Math.ceil(viewport.height));
        const context = canvas.getContext("2d", { willReadFrequently: true });
        if (!context) throw new Error("PDF 페이지 렌더링 컨텍스트를 만들 수 없습니다.");
        await page.render({
          canvas: canvas as unknown as HTMLCanvasElement,
          canvasContext: context as unknown as CanvasRenderingContext2D,
          viewport
        }).promise;
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        yield {
          unitId: pdfUnitId(sourcePath, pageNumber),
          sourcePath,
          sourceKind: "pdf-page",
          page: pageNumber,
          image,
          width: canvas.width,
          height: canvas.height
        };
      } finally {
        page.cleanup();
      }
    }
  } finally {
    await destroyPdfTask(task, document);
  }
}

export function pdfUnitId(sourcePath: string, page: number) {
  return `pdf:${sourcePath.normalize("NFC")}#page=${String(page).padStart(3, "0")}`;
}

async function loadPdfJs(): Promise<PdfJsModule> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
  return pdfjs;
}

async function destroyPdfTask(task: { destroy?: () => Promise<void> | void }, document: unknown) {
  const documentWithDestroy = document as { destroy?: () => Promise<void> | void };
  if (documentWithDestroy.destroy) {
    await documentWithDestroy.destroy();
    return;
  }
  await task.destroy?.();
}
