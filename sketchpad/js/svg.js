// SVG export. Produces a standalone, scalable vector image of the board, for
// opening/editing in other vector tools (Inkscape, Illustrator, browsers).
//
// This is a one-way IMAGE export, not the round-trip format — use .sketch to
// keep editing in Sketchpad.
//
// The true-eraser is reproduced faithfully by honouring draw order: an eraser
// only affects strokes drawn before it. We split the strokes into draw-batches
// separated by each run of erases, then nest the batches inside per-run <mask>s.
// Nested masks compose as an intersection of visibility, i.e. a pixel is hidden
// if ANY applicable eraser covers it — exactly the canvas's destination-out
// behaviour, so drawing over a previously-erased spot renders correctly.

const GRID = 40;
const DOT_R = 1.4;

export function buildSVG(strokes, bounds, opts = {}) {
  const {
    background = 'blank',
    bgColor = '#ffffff',
    patternOpacity = 0.25,
    includeBackground = true,
  } = opts;

  const pad = 24;
  const minX = bounds.minX - pad;
  const minY = bounds.minY - pad;
  const w = (bounds.maxX - bounds.minX) + pad * 2;
  const h = (bounds.maxY - bounds.minY) + pad * 2;

  // Split into draw-batches separated by maximal runs of consecutive erases.
  // batchList[i] is the draws between erase-run i-1 and erase-run i; it is
  // affected by erase-runs i, i+1, ... (every erase that comes after it).
  const batchList = [];
  const eraseRuns = [];
  let curDraws = [];
  let curRun = null;
  for (const s of strokes) {
    if (s.tool === 'erase') {
      if (curRun === null) { batchList.push(curDraws); curDraws = []; curRun = [s]; }
      else curRun.push(s);
    } else {
      if (curRun !== null) { eraseRuns.push(curRun); curRun = null; }
      curDraws.push(s);
    }
  }
  if (curRun !== null) eraseRuns.push(curRun);
  batchList.push(curDraws);

  const region = `x="${r(minX)}" y="${r(minY)}" width="${r(w)}" height="${r(h)}"`;
  const defs = [];
  const renderBatch = (batch) => batch.map((s) => strokeSVG(s, null)).join('');

  // Build outward: each step wraps the accumulated content in the next erase
  // run's mask, then appends the following batch on top (outside that mask).
  let acc = renderBatch(batchList[0]);
  for (let j = 0; j < eraseRuns.length; j++) {
    const id = 'erase' + j;
    const body = [`<rect ${region} fill="white"/>`];
    for (const e of eraseRuns[j]) body.push(strokeSVG(e, 'black'));
    defs.push(`<mask id="${id}" maskUnits="userSpaceOnUse" ${region}>${body.join('')}</mask>`);
    acc = `<g mask="url(#${id})">${acc}</g>` + renderBatch(batchList[j + 1]);
  }

  const out = [];
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${r(minX)} ${r(minY)} ${r(w)} ${r(h)}" width="${r(w)}" height="${r(h)}">`);
  if (includeBackground) {
    out.push(`<rect ${region} fill="${bgColor}"/>`);
    if (background !== 'blank') out.push(patternSVG(background, bgColor, patternOpacity, minX, minY, w, h));
  }
  if (defs.length) out.push(`<defs>${defs.join('')}</defs>`);
  out.push(acc);
  out.push('</svg>');
  return out.join('\n');
}

function strokeSVG(s, colorOverride) {
  const pts = s.points;
  if (!pts || !pts.length) return '';
  const color = colorOverride || s.color;

  if (s.shape) {
    const p0 = pts[0], p1 = pts[1] || pts[0];
    const base = `fill="none" stroke="${color}" stroke-width="${r(s.size)}"`;
    if (s.shape === 'line') {
      return `<line x1="${r(p0.x)}" y1="${r(p0.y)}" x2="${r(p1.x)}" y2="${r(p1.y)}" ${base} stroke-linecap="round"/>`;
    }
    const x0 = Math.min(p0.x, p1.x), y0 = Math.min(p0.y, p1.y);
    const ww = Math.abs(p1.x - p0.x), hh = Math.abs(p1.y - p0.y);
    if (s.shape === 'rect') {
      return `<rect x="${r(x0)}" y="${r(y0)}" width="${r(ww)}" height="${r(hh)}" ${base} stroke-linejoin="round"/>`;
    }
    if (s.shape === 'ellipse') {
      return `<ellipse cx="${r(x0 + ww / 2)}" cy="${r(y0 + hh / 2)}" rx="${r(ww / 2)}" ry="${r(hh / 2)}" ${base}/>`;
    }
  }

  if (pts.length === 1) {
    return `<circle cx="${r(pts[0].x)}" cy="${r(pts[0].y)}" r="${r(widthAt(s, pts[0]) / 2)}" fill="${color}"/>`;
  }

  if (s.pressure) {
    // variable width -> one line per segment, matching the canvas renderer
    let out = '';
    for (let i = 1; i < pts.length; i++) {
      out += `<line x1="${r(pts[i - 1].x)}" y1="${r(pts[i - 1].y)}" x2="${r(pts[i].x)}" y2="${r(pts[i].y)}" fill="none" stroke="${color}" stroke-width="${r(widthAt(s, pts[i]))}" stroke-linecap="round"/>`;
    }
    return out;
  }

  let d = `M ${r(pts[0].x)} ${r(pts[0].y)}`;
  for (let i = 1; i < pts.length; i++) d += ` L ${r(pts[i].x)} ${r(pts[i].y)}`;
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${r(s.size)}" stroke-linecap="round" stroke-linejoin="round"/>`;
}

function patternSVG(type, bgColor, opacity, minX, minY, w, h) {
  const ink = patternColor(bgColor);
  const maxX = minX + w, maxY = minY + h;
  const startX = Math.floor(minX / GRID) * GRID;
  const startY = Math.floor(minY / GRID) * GRID;

  if (type === 'grid') {
    let d = '';
    for (let x = startX; x <= maxX; x += GRID) d += `M ${r(x)} ${r(minY)} L ${r(x)} ${r(maxY)} `;
    for (let y = startY; y <= maxY; y += GRID) d += `M ${r(minX)} ${r(y)} L ${r(maxX)} ${r(y)} `;
    return `<path d="${d.trim()}" stroke="${ink}" stroke-width="1" stroke-opacity="${opacity}" fill="none"/>`;
  }
  // dots
  let out = '';
  for (let x = startX; x <= maxX; x += GRID) {
    for (let y = startY; y <= maxY; y += GRID) {
      out += `<circle cx="${r(x)}" cy="${r(y)}" r="${DOT_R}" fill="${ink}" fill-opacity="${opacity}"/>`;
    }
  }
  return out;
}

function patternColor(bg) {
  const { r: rr, g, b } = hexToRgb(bg);
  const lum = (0.299 * rr + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.5 ? '#000000' : '#ffffff';
}

function hexToRgb(hex) {
  let h = (hex || '#ffffff').replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function widthAt(s, pt) {
  if (!s.pressure) return s.size;
  const p = pt.p == null ? 0.5 : pt.p;
  return s.size * (0.2 + 0.8 * p);
}

function r(n) {
  return Math.round(n * 100) / 100;
}
