// Infinite background: a solid color fill plus an optional grid/dots pattern that
// tiles across the whole viewport and tracks the pan/zoom transform. The pattern
// color auto-adapts to stay visible against whatever background color is chosen.

const GRID = 40;    // pattern spacing in document units
const DOT_R = 1.4;  // dot radius in document units

// ox/oy/scale map document units -> screen px (screen = doc*scale + offset).
// viewW/viewH is the area to fill (CSS px on screen, or pixels for export).
// opacity sets how strong the grid/dot pattern is (0..1).
export function drawBackground(ctx, type, bgColor, ox, oy, scale, viewW, viewH, opacity = 0.25) {
  ctx.fillStyle = bgColor || '#ffffff';
  ctx.fillRect(0, 0, viewW, viewH);
  if (type === 'blank') return;

  const leftDoc = (0 - ox) / scale;
  const topDoc = (0 - oy) / scale;
  const rightDoc = (viewW - ox) / scale;
  const bottomDoc = (viewH - oy) / scale;
  const startX = Math.floor(leftDoc / GRID) * GRID;
  const startY = Math.floor(topDoc / GRID) * GRID;
  const ink = patternColor(bgColor || '#ffffff', opacity);

  if (type === 'grid') {
    ctx.strokeStyle = ink;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = startX; x <= rightDoc; x += GRID) {
      const sx = Math.round(ox + x * scale) + 0.5;
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, viewH);
    }
    for (let y = startY; y <= bottomDoc; y += GRID) {
      const sy = Math.round(oy + y * scale) + 0.5;
      ctx.moveTo(0, sy);
      ctx.lineTo(viewW, sy);
    }
    ctx.stroke();
  } else if (type === 'dots') {
    ctx.fillStyle = ink;
    const r = Math.max(0.8, DOT_R * scale);
    for (let x = startX; x <= rightDoc; x += GRID) {
      for (let y = startY; y <= bottomDoc; y += GRID) {
        ctx.beginPath();
        ctx.arc(ox + x * scale, oy + y * scale, r, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

// Pattern ink: dark on light backgrounds, light on dark ones, at the given
// opacity (white-on-dark is nudged up slightly since it reads fainter).
function patternColor(bg, opacity = 0.25) {
  const { r, g, b } = hexToRgb(bg);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.5
    ? `rgba(0,0,0,${opacity})`
    : `rgba(255,255,255,${Math.min(1, opacity * 1.15)})`;
}

function hexToRgb(hex) {
  let h = (hex || '#ffffff').replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}
