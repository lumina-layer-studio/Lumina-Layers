import type { CalibrationPreview, LutBoardPage } from "./calibrationPreview";

// Millimetres in the face-down single-stage kit, turned clockwise to stand
// the two 67 × 34 mm boards beside each other in a square thumbnail.
export const cardPair = { size: 80, width: 34, height: 67, top: 6.5, left: [4, 42] } as const;
export interface CardFootprint { x: number; y: number; width: number; height: number; light: boolean }
export const materialFaces: readonly CardFootprint[] = cardPair.left.map((x, i) => (
  { x, y: cardPair.top, width: cardPair.width, height: cardPair.height, light: i === 1 }
));
export const lutFace: readonly CardFootprint[] = [{ x: 4, y: 4, width: 72, height: 72, light: true }];
export const lutStack: readonly CardFootprint[] = [
  { x: 13, y: 3, width: 64, height: 64, light: true },
  { x: 3, y: 13, width: 64, height: 64, light: true },
];
const stepLayers = [...Array.from({ length: 17 }, (_, i) => i), 25];
const textureCache = new Map<string, string>();

function boardFace(preview: CalibrationPreview, side: 0 | 1): string {
  const colors = side === 0 ? preview.black : preview.white;
  const base = side === 0 ? "#222426" : "#f5f5f1";
  const outline = side === 0 ? "#787b7e" : "#969893";
  const cellColors = new Map<number, string>();
  if (preview.kind === "illustrative" && colors.length === 1) {
    stepLayers.forEach((_, i) => cellColors.set(i, colors[Math.floor(i * colors.length / stepLayers.length)]));
  } else if (preview.kind !== "unknown") {
    colors.forEach((color, i) => cellColors.set(Math.round(i * (stepLayers.length - 1) / (colors.length - 1)), color));
  }
  const singleColor = preview.kind === "illustrative" && colors.length === 1;
  const cells = stepLayers.map((layers, i) => {
    const x = 1 + (2 - Math.floor(i / 6)) * 11;
    const y = 1 + (i % 6) * 11;
    const color = cellColors.get(i);
    const ink = color ? `fill="${color}"` : `fill="none" stroke="${outline}" stroke-opacity=".48" stroke-width=".4"`;
    const opacity = singleColor ? ` opacity="${Math.sqrt(layers / 25).toFixed(3)}"` : "";
    return `<path d="M${x} ${y}h10v10h-10Z" ${ink}${opacity}/>`;
  }).join("");
  return `<g transform="translate(${cardPair.left[side]} ${cardPair.top})"><rect width="${cardPair.width}" height="${cardPair.height}" fill="${base}" stroke="${outline}" stroke-width=".45"/>${cells}</g>`;
}

export function calibrationCardTexture(preview: CalibrationPreview): string {
  const key = [preview.kind, ...preview.black, "/", ...preview.white].join("|");
  const cached = textureCache.get(key);
  if (cached) return cached;
  return saveTexture(key, boardFace(preview, 0) + boardFace(preview, 1));
}

function saveTexture(key: string, content: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">${content}</svg>`;
  const url = "data:image/svg+xml," + encodeURIComponent(svg);
  if (textureCache.size >= 512) textureCache.delete(textureCache.keys().next().value!);
  textureCache.set(key, url);
  return url;
}

// Clockwise from top left, following the corners printed by core/calibration.py.
function registrationSlots(preview: CalibrationPreview, page: LutBoardPage): number[] {
  const family = preview.lutBoard?.family;
  if (family === "five") return page.number === 1 ? [0, 1, 3, 2] : [3, 1, 4, 2];
  if (family === "eight" || family === "full") return [0, page.number % 2 ? 1 : 2, 5, 4];
  if (family !== "board") return [];
  if (page.count === 32) return [0, 1, 1, 1];
  if (preview.lutVariant === "rybw") return [0, 1, 3, 2];
  if (preview.lutVariant === "cmyw") return [0, 1, 2, page.count === 1296 ? 4 : 3];
  return [];
}

function squareFace(face: CardFootprint, page: LutBoardPage, preview: CalibrationPreview): string {
  const { x, y, width, height } = face;
  const outline = `<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="#fff" stroke="#a6a8a5" stroke-width=".4"/>`;
  // Coordinates are expressed in printed cell pitches, including the outer padding.
  const { padding, rows, cols } = page;
  const boardWidth = cols + 2 * padding;
  const boardHeight = rows + 2 * padding;
  const region = `x="${padding}" y="${padding}" width="${cols}" height="${rows}"`;
  const pixels = `<image ${region} preserveAspectRatio="none" style="image-rendering:pixelated" href="data:image/png;base64,${page.png}"/>`;
  let grid = "", corners = "";
  if (preview.lutBoard?.family !== "index") {
    // The standard UI prints a 5 mm patch and a 0.84 mm gap, or 11 + 2 voxels.
    const block = preview.lutBoard?.blockFraction ?? 11 / 13;
    const id = `gap-${x}`;
    grid = `<defs><pattern id="${id}" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M${block} 0H1V1H0V${block}H${block}Z" fill="#fff"/></pattern></defs><rect ${region} fill="url(#${id})"/>`;
    const coords = [[0, 0], [boardWidth - 1, 0], [boardWidth - 1, boardHeight - 1], [0, boardHeight - 1]];
    corners = registrationSlots(preview, page).map((slot, i) => preview.black[slot]
      ? `<rect x="${coords[i][0]}" y="${coords[i][1]}" width="${block}" height="${block}" fill="${preview.black[slot]}"/>` : "").join("");
  }
  return `${outline}<svg x="${x}" y="${y}" width="${width}" height="${height}" viewBox="0 0 ${boardWidth} ${boardHeight}" preserveAspectRatio="none">${pixels}${grid}${corners}</svg>`;
}

export function lutBoardTexture(preview: CalibrationPreview, pageIndex: number, stacked: boolean): string {
  const board = preview.lutBoard;
  const page = board?.pages[pageIndex];
  if (!page) return "";
  const back = stacked ? board?.pages[pageIndex + 1] : undefined;
  const key = JSON.stringify(["lut", board?.family, board?.blockFraction, preview.lutVariant, page, back, board && preview.black]);
  const cached = textureCache.get(key);
  if (cached) return cached;
  const content = back
    ? squareFace(lutStack[0], back, preview) + squareFace(lutStack[1], page, preview)
    : squareFace(lutFace[0], page, preview);
  return saveTexture(key, content);
}
