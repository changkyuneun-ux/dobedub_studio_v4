import { zlibSync } from "fflate";
import { SUMMARY_COLUMNS } from "./constants";
import { writeAtomically, type DirectoryPort } from "./filesystem";
import type { PixelRegion, SummaryRow } from "./types";

const PNG_SIGNATURE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

export async function encodeCut(image: ImageData, region: PixelRegion): Promise<Blob> {
  const width = region.x1 - region.x0;
  const height = region.y1 - region.y0;
  const raw = new Uint8Array((width * 4 + 1) * height);
  let target = 0;
  for (let y = region.y0; y < region.y1; y += 1) {
    raw[target] = 0;
    target += 1;
    for (let x = region.x0; x < region.x1; x += 1) {
      const source = (y * image.width + x) * 4;
      raw[target] = image.data[source];
      raw[target + 1] = image.data[source + 1];
      raw[target + 2] = image.data[source + 2];
      raw[target + 3] = image.data[source + 3];
      target += 4;
    }
  }

  return new Blob([buildPng(width, height, raw)], { type: "image/png" });
}

export function serializeSummary(rows: SummaryRow[]): Uint8Array {
  const header = SUMMARY_COLUMNS.join(",");
  const body = rows.map((row) => SUMMARY_COLUMNS.map((column) => csvCell(row[column])).join(","));
  return new TextEncoder().encode(`\uFEFF${[header, ...body].join("\r\n")}\r\n`);
}

export async function writeSummary(directory: DirectoryPort, rows: SummaryRow[]) {
  await writeAtomically(directory, "summary.csv", serializeSummary(rows));
}

export async function verifyPngOutput(file: File, expectedSize: { width: number; height: number }): Promise<boolean> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.byteLength < 24) return false;
  for (let index = 0; index < PNG_SIGNATURE.byteLength; index += 1) {
    if (bytes[index] !== PNG_SIGNATURE[index]) return false;
  }
  const width = readUint32(bytes, 16);
  const height = readUint32(bytes, 20);
  return width === expectedSize.width && height === expectedSize.height;
}

export function pngDimensions(bytes: Uint8Array) {
  for (let index = 0; index < PNG_SIGNATURE.byteLength; index += 1) {
    if (bytes[index] !== PNG_SIGNATURE[index]) return null;
  }
  return { width: readUint32(bytes, 16), height: readUint32(bytes, 20) };
}

function buildPng(width: number, height: number, rawRgbaRows: Uint8Array) {
  const ihdr = new Uint8Array(13);
  writeUint32(ihdr, 0, width);
  writeUint32(ihdr, 4, height);
  ihdr[8] = 8;
  ihdr[9] = 6;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  return concat([
    PNG_SIGNATURE,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", zlibSync(rawRgbaRows)),
    pngChunk("IEND", new Uint8Array())
  ]);
}

function pngChunk(type: string, data: Uint8Array) {
  const typeBytes = new TextEncoder().encode(type);
  const chunk = new Uint8Array(12 + data.byteLength);
  writeUint32(chunk, 0, data.byteLength);
  chunk.set(typeBytes, 4);
  chunk.set(data, 8);
  writeUint32(chunk, 8 + data.byteLength, crc32(concat([typeBytes, data])));
  return chunk;
}

function csvCell(value: string | number | null | undefined) {
  const raw = value === null || value === undefined ? "" : String(value);
  return /[",\r\n]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
}

function concat(parts: Uint8Array[]) {
  const length = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const result = new Uint8Array(length);
  let offset = 0;
  parts.forEach((part) => {
    result.set(part, offset);
    offset += part.byteLength;
  });
  return result;
}

function writeUint32(bytes: Uint8Array, offset: number, value: number) {
  bytes[offset] = (value >>> 24) & 0xff;
  bytes[offset + 1] = (value >>> 16) & 0xff;
  bytes[offset + 2] = (value >>> 8) & 0xff;
  bytes[offset + 3] = value & 0xff;
}

function readUint32(bytes: Uint8Array, offset: number) {
  return ((bytes[offset] << 24) | (bytes[offset + 1] << 16) | (bytes[offset + 2] << 8) | bytes[offset + 3]) >>> 0;
}

const CRC_TABLE = new Uint32Array(256).map((_, index) => {
  let crc = index;
  for (let bit = 0; bit < 8; bit += 1) {
    crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  }
  return crc >>> 0;
});

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (let index = 0; index < bytes.byteLength; index += 1) {
    crc = CRC_TABLE[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
