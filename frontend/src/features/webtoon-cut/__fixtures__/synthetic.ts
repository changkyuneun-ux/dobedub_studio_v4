import type { PixelRegion } from "../types";

export function blankImage(width: number, height: number, color: [number, number, number] = [255, 255, 255]): ImageData {
  const data = new Uint8ClampedArray(width * height * 4);
  fillRect(data, width, { x0: 0, y0: 0, x1: width, y1: height }, color);
  return { data, width, height, colorSpace: "srgb" } as ImageData;
}

export function verticalBands(width: number, height: number, bands: Array<[number, number]>): ImageData {
  const image = blankImage(width, height);
  bands.forEach(([y0, y1]) => {
    fillRect(image.data, width, { x0: 0, y0, x1: width, y1 }, [20, 20, 20]);
  });
  return image;
}

export function threeSceneStrip(width: number, height: number, boundaries: [number, number]): ImageData {
  const image = blankImage(width, height, [20, 20, 20]);
  fillRect(image.data, width, { x0: 0, y0: boundaries[0], x1: width, y1: boundaries[1] }, [230, 230, 230]);
  fillRect(image.data, width, { x0: 0, y0: boundaries[1], x1: width, y1: height }, [40, 70, 180]);
  return image;
}

export function insetFrameEdge(width: number, height: number, y: number, coverage: number): ImageData {
  const image = blankImage(width, height, [40, 40, 40]);
  const edgeWidth = Math.floor(width * coverage);
  const inset = Math.floor((width - edgeWidth) / 2);
  fillRect(image.data, width, { x0: inset, y0: y, x1: inset + edgeWidth, y1: y + 1 }, [240, 240, 240]);
  return image;
}

export function fourPanelPage(width: number, height: number): ImageData {
  const image = blankImage(width, height);
  const panels: PixelRegion[] = [
    { x0: 80, y0: 80, x1: 360, y1: 300 },
    { x0: 440, y0: 80, x1: 720, y1: 300 },
    { x0: 80, y0: 380, x1: 360, y1: 600 },
    { x0: 440, y0: 380, x1: 720, y1: 600 }
  ];
  panels.forEach((panel) => {
    drawBorder(image.data, width, panel, [20, 20, 20], 4);
    fillRect(image.data, width, {
      x0: panel.x0 + 48,
      y0: panel.y0 + 48,
      x1: panel.x0 + 108,
      y1: panel.y0 + 108
    }, [20, 20, 20]);
  });
  return image;
}

export function borderlessInfographic(width: number, height: number): ImageData {
  const image = blankImage(width, height, [245, 245, 245]);
  fillRect(image.data, width, { x0: 100, y0: 100, x1: width - 100, y1: height - 100 }, [220, 235, 250]);
  return image;
}

export function decorativeBlob(width: number, height: number, cx: number, cy: number, radius: number): ImageData {
  const image = blankImage(width, height);
  const y0 = Math.max(0, cy - radius);
  const y1 = Math.min(height - 1, cy + radius);
  const x0 = Math.max(0, cx - radius);
  const x1 = Math.min(width - 1, cx + radius);
  for (let y = y0; y <= y1; y += 1) {
    for (let x = x0; x <= x1; x += 1) {
      if (Math.abs(x - cx) + Math.abs(y - cy) <= radius) {
        const offset = (y * width + x) * 4;
        image.data[offset] = 20;
        image.data[offset + 1] = 20;
        image.data[offset + 2] = 20;
        image.data[offset + 3] = 255;
      }
    }
  }
  return image;
}

export function fourPanelPageWithDecoration(width: number, height: number): ImageData {
  const image = fourPanelPage(width, height);
  const decoration = decorativeBlob(width, height, Math.round(width / 2), height - 150, 90);
  for (let i = 0; i < image.data.length; i += 4) {
    if (decoration.data[i] < 128) {
      image.data[i] = decoration.data[i];
      image.data[i + 1] = decoration.data[i + 1];
      image.data[i + 2] = decoration.data[i + 2];
    }
  }
  return image;
}

function drawBorder(data: Uint8ClampedArray, width: number, region: PixelRegion, color: [number, number, number], thickness: number) {
  fillRect(data, width, { x0: region.x0, y0: region.y0, x1: region.x1, y1: region.y0 + thickness }, color);
  fillRect(data, width, { x0: region.x0, y0: region.y1 - thickness, x1: region.x1, y1: region.y1 }, color);
  fillRect(data, width, { x0: region.x0, y0: region.y0, x1: region.x0 + thickness, y1: region.y1 }, color);
  fillRect(data, width, { x0: region.x1 - thickness, y0: region.y0, x1: region.x1, y1: region.y1 }, color);
}

function fillRect(
  data: Uint8ClampedArray,
  width: number,
  region: PixelRegion,
  color: [number, number, number]
) {
  const [r, g, b] = color;
  for (let y = region.y0; y < region.y1; y += 1) {
    for (let x = region.x0; x < region.x1; x += 1) {
      const offset = (y * width + x) * 4;
      data[offset] = r;
      data[offset + 1] = g;
      data[offset + 2] = b;
      data[offset + 3] = 255;
    }
  }
}
