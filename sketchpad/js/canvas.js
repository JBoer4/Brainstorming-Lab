// Drawing engine: an unbounded whiteboard canvas with vector strokes, two
// erasers, pan/zoom, pressure, undo/redo.
//
// Model: every mark is a vector Stroke {tool,color,size,pressure,points} in
// unbounded document space. The view is a pan/zoom transform (no page bounds).
// A "true eraser" stroke paints with destination-out into an isolated ink layer,
// so it reveals the background rather than punching through to nothing. The
// "stroke eraser" hit-tests and removes whole strokes.
//
// Rendering: each frame we repaint the background (solid color + infinite
// pattern) across the viewport, then redraw all strokes into a viewport-sized
// ink layer (transparent; erases are holes) and composite it on top. This full
// redraw keeps an infinite, freely-panned canvas simple and correct.

import { drawBackground } from './backgrounds.js';

const RENDER_SCALE = 2;   // export supersampling for crisp lines
const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const ERASE_HIT = 10;     // minimum stroke-eraser hit radius (document units)
const EDGE = 64;          // auto-expand margin near the viewport edge (CSS px)

export class CanvasEngine {
  constructor(canvas, stage, { onChange, onZoom } = {}) {
    this.canvas = canvas;
    this.stage = stage;
    this.ctx = canvas.getContext('2d');
    this.onChange = onChange || (() => {});
    this.onZoom = onZoom || (() => {});

    this.strokes = [];
    this.undoStack = [];
    this.redoStack = [];
    this.background = 'blank';
    this.bgColor = '#ffffff';
    this.patternOpacity = 0.25;   // grid/dot strength (global preference)

    this.tool = 'pen';
    this.color = '#111318';
    this.penSize = 4;
    this.eraserSize = 24;     // independent of the pen
    this.pressure = false;
    this.fingerMode = 'erase';

    // View transform (document -> CSS px): screen = doc * scale + offset
    this.scale = 1;
    this.offsetX = 0;
    this.offsetY = 0;

    // Isolated strokes layer (transparent; true-eraser punches holes here)
    this.ink = document.createElement('canvas');
    this.inkCtx = this.ink.getContext('2d');

    this.pointers = new Map();   // pointerId -> {x,y,type}
    this.active = null;          // in-progress draw/erase
    this.gesture = null;         // touch pan/zoom gesture
    this.mousePan = null;        // middle/right-mouse drag pan
    this._raf = 0;

    this._bindInput();
    window.addEventListener('resize', () => this.resize());
  }

  // ---------- document ----------
  load(doc) {
    this.strokes = (doc.strokes || []).map((s) => ({ ...s, points: s.points.slice() }));
    this.background = doc.background || 'blank';
    this.bgColor = doc.bgColor || '#ffffff';
    this.undoStack = [];
    this.redoStack = [];
    this.active = null;
    this.gesture = null;
    this.fitToContent();
  }

  serialize() {
    return { strokes: this.strokes, background: this.background, bgColor: this.bgColor };
  }

  setBackground(type) {
    this.background = type;
    this.requestDraw();
    this.onChange();
  }

  setBgColor(color) {
    this.bgColor = color;
    this.requestDraw();
    this.onChange();
  }

  setPatternOpacity(v) {
    this.patternOpacity = v;
    this.requestDraw();
  }

  // ---------- sizing & view ----------
  resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.stage.clientWidth;
    const h = this.stage.clientHeight;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.cssW = w;
    this.cssH = h;
    this.requestDraw();
  }

  // Start centered on the origin of the infinite plane.
  resetView() {
    this.scale = 1;
    this.offsetX = Math.round(this.cssW / 2);
    this.offsetY = Math.round(this.cssH / 2);
    this.onZoom(this.scale);
    this.requestDraw();
  }

  // Frame the existing content (or center the origin if the board is empty).
  fitToContent() {
    const b = this._contentBounds();
    if (!b) { this.resetView(); return; }
    const pad = 40;
    const w = (b.maxX - b.minX) + pad * 2;
    const h = (b.maxY - b.minY) + pad * 2;
    this.scale = clamp(Math.min(this.cssW / w, this.cssH / h), MIN_SCALE, MAX_SCALE);
    this.offsetX = (this.cssW - (b.minX + b.maxX) * this.scale) / 2;
    this.offsetY = (this.cssH - (b.minY + b.maxY) * this.scale) / 2;
    this.onZoom(this.scale);
    this.requestDraw();
  }

  screenToDoc(clientX, clientY) {
    const r = this.canvas.getBoundingClientRect();
    return {
      x: (clientX - r.left - this.offsetX) / this.scale,
      y: (clientY - r.top - this.offsetY) / this.scale,
    };
  }

  // ---------- rendering ----------
  requestDraw() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this.draw();
    });
  }

  draw() {
    const ctx = this.ctx;
    // background (solid color + infinite pattern), drawn in CSS px
    drawBackground(ctx, this.background, this.bgColor,
      this.offsetX, this.offsetY, this.scale, this.cssW, this.cssH, this.patternOpacity);

    // strokes, composited from the isolated ink layer
    this._renderInk();
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0); // blit ink 1:1 in device px
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(this.ink, 0, 0);
    ctx.restore();
  }

  _renderInk() {
    const dpr = window.devicePixelRatio || 1;
    const iw = Math.round(this.cssW * dpr);
    const ih = Math.round(this.cssH * dpr);
    if (this.ink.width !== iw || this.ink.height !== ih) {
      this.ink.width = iw;
      this.ink.height = ih;
    }
    const ictx = this.inkCtx;
    ictx.setTransform(1, 0, 0, 1, 0, 0);
    ictx.clearRect(0, 0, iw, ih);
    // document -> device px
    ictx.setTransform(dpr * this.scale, 0, 0, dpr * this.scale,
      dpr * this.offsetX, dpr * this.offsetY);
    for (const s of this.strokes) this._paintStroke(ictx, s);
    if (this.active && this.active.stroke) this._paintStroke(ictx, this.active.stroke);
  }

  // Paint a stroke in document coordinates (the context already carries the
  // doc -> device transform, so widths are in document units).
  _paintStroke(ctx, stroke) {
    const pts = stroke.points;
    if (pts.length === 0) return;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    if (stroke.tool === 'erase') {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.strokeStyle = '#000';
      ctx.fillStyle = '#000';
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = stroke.color;
      ctx.fillStyle = stroke.color;
    }

    if (stroke.shape) {
      const p0 = pts[0], p1 = pts[1] || pts[0];
      ctx.lineWidth = stroke.size;
      ctx.beginPath();
      if (stroke.shape === 'line') {
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
      } else if (stroke.shape === 'rect') {
        ctx.rect(Math.min(p0.x, p1.x), Math.min(p0.y, p1.y),
          Math.abs(p1.x - p0.x), Math.abs(p1.y - p0.y));
      } else if (stroke.shape === 'ellipse') {
        ctx.ellipse((p0.x + p1.x) / 2, (p0.y + p1.y) / 2,
          Math.abs(p1.x - p0.x) / 2, Math.abs(p1.y - p0.y) / 2, 0, 0, Math.PI * 2);
      }
      ctx.stroke();
      ctx.restore();
      return;
    }

    if (pts.length === 1) {
      const w = this._widthAt(stroke, pts[0]);
      ctx.beginPath();
      ctx.arc(pts[0].x, pts[0].y, w / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      return;
    }

    if (stroke.pressure) {
      for (let i = 1; i < pts.length; i++) {
        ctx.lineWidth = this._widthAt(stroke, pts[i]);
        ctx.beginPath();
        ctx.moveTo(pts[i - 1].x, pts[i - 1].y);
        ctx.lineTo(pts[i].x, pts[i].y);
        ctx.stroke();
      }
    } else {
      ctx.lineWidth = stroke.size;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.stroke();
    }
    ctx.restore();
  }

  _widthAt(stroke, pt) {
    if (!stroke.pressure) return stroke.size;
    const p = pt.p == null ? 0.5 : pt.p;
    return stroke.size * (0.2 + 0.8 * p);
  }

  // ---------- input ----------
  _bindInput() {
    const c = this.canvas;
    const opts = { passive: false };
    c.addEventListener('pointerdown', (e) => this._onDown(e), opts);
    c.addEventListener('pointermove', (e) => this._onMove(e), opts);
    c.addEventListener('pointerup', (e) => this._onUp(e), opts);
    c.addEventListener('pointercancel', (e) => this._onUp(e), opts);
    // block context menu (right-drag is a tool) and middle-click autoscroll
    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('mousedown', (e) => { if (e.button === 1) e.preventDefault(); });
  }

  _touchCount() {
    let n = 0;
    for (const p of this.pointers.values()) if (p.type === 'touch') n++;
    return n;
  }

  _onDown(e) {
    e.preventDefault();
    this.canvas.setPointerCapture?.(e.pointerId);
    this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, type: e.pointerType });

    const isPen = e.pointerType === 'pen';
    const isTouch = e.pointerType === 'touch';

    // Two or more touches -> pan/zoom gesture (cancel any finger stroke)
    if (isTouch && this._touchCount() >= 2) {
      this.mousePan = null;
      this._discardActiveIfTouch();
      this._startGesture();
      return;
    }

    // A pen is drawing -> ignore stray touches (palm rejection)
    if (this.active && this.active.type === 'pen' && isTouch) return;

    // Hand tool: any single-pointer drag pans the canvas
    if (this.tool === 'hand') {
      this._startMousePan(e);
      return;
    }

    if (isPen) {
      this._startStroke(e, this.tool, 'pen');
      return;
    }

    if (e.pointerType === 'mouse') {
      if (e.button === 1) {            // middle button == two fingers == pan
        this._startMousePan(e);
      } else if (e.button === 2) {     // right button == one finger
        if (this.fingerMode === 'pan') this._startMousePan(e);
        else this._startStroke(e, this.fingerMode === 'erase' ? 'erase' : 'pen', 'mouse');
      } else {                          // left button == selected tool
        this._startStroke(e, this.tool, 'mouse');
      }
      return;
    }

    if (isTouch) {
      if (this.fingerMode === 'pan') {
        this._startGesture();
      } else {
        this._startStroke(e, this.fingerMode === 'erase' ? 'erase' : 'pen', 'touch');
      }
    }
  }

  _onMove(e) {
    if (this.pointers.has(e.pointerId)) {
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, type: e.pointerType });
    }

    if (this.mousePan) {
      this.offsetX += e.clientX - this.mousePan.last.x;
      this.offsetY += e.clientY - this.mousePan.last.y;
      this.mousePan.last = { x: e.clientX, y: e.clientY };
      this.requestDraw();
      return;
    }

    if (this.gesture) {
      this._updateGesture();
      return;
    }

    if (!this.active || this.active.pointerId !== e.pointerId) return;

    // coalesced events give smoother strokes on high-rate pens
    const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of events) this._extendStroke(ev);
    this._maybeAutoPan(e);
    this.requestDraw();
  }

  _onUp(e) {
    this.pointers.delete(e.pointerId);
    this.canvas.releasePointerCapture?.(e.pointerId);

    if (this.mousePan) { this.mousePan = null; return; }

    if (this.gesture) {
      if (this._touchCount() < 2) this.gesture = null;
      return;
    }

    if (this.active && this.active.pointerId === e.pointerId) {
      this._finishStroke();
    }
  }

  // ----- drawing strokes -----
  _startStroke(e, tool, type) {
    const pt = this._point(e);
    if (tool === 'stroke-erase') {
      this.active = { pointerId: e.pointerId, type, tool: 'stroke-erase', removed: [] };
      this._strokeEraseAt(pt);
      return;
    }
    const isShape = tool === 'line' || tool === 'rect' || tool === 'ellipse';
    const isErase = tool === 'erase';
    const stroke = {
      tool: isErase ? 'erase' : 'pen',
      shape: isShape ? tool : null,
      color: this.color,
      size: isErase ? this.eraserSize : this.penSize,
      pressure: !isShape && this.pressure && type === 'pen',
      points: isShape ? [pt, { ...pt }] : [pt],
    };
    this.active = { pointerId: e.pointerId, type, tool: isShape ? 'shape' : stroke.tool, stroke };
    this.requestDraw();
  }

  _extendStroke(e) {
    const a = this.active;
    if (!a) return;
    const pt = this._point(e);
    if (a.tool === 'stroke-erase') {
      this._strokeEraseAt(pt);
      return;
    }
    if (a.tool === 'shape') {
      a.stroke.points[1] = pt; // shapes are defined by their two drag corners
      return;
    }
    const s = a.stroke;
    const last = s.points[s.points.length - 1];
    // skip near-duplicate points (in document units)
    if (last && Math.hypot(pt.x - last.x, pt.y - last.y) < 0.6 / this.scale) {
      last.p = pt.p;
      return;
    }
    s.points.push(pt);
  }

  // Gently scroll the view when an active draw stroke nears a viewport edge, so
  // the canvas "opens up" into fresh space. Stroke points stay in document
  // space, so the line continues seamlessly as the view moves under the pointer.
  _maybeAutoPan(e) {
    const a = this.active;
    if (!a || a.tool === 'stroke-erase' || !a.stroke) return;
    const r = this.canvas.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    let dx = 0, dy = 0;
    if (x < EDGE) dx = EDGE - x;
    else if (x > this.cssW - EDGE) dx = (this.cssW - EDGE) - x;
    if (y < EDGE) dy = EDGE - y;
    else if (y > this.cssH - EDGE) dy = (this.cssH - EDGE) - y;
    if (dx || dy) {
      this.offsetX += dx * 0.3;
      this.offsetY += dy * 0.3;
    }
  }

  _finishStroke() {
    const a = this.active;
    this.active = null;
    if (!a) return;
    if (a.tool === 'stroke-erase') {
      if (a.removed.length) {
        this.undoStack.push({ type: 'delete', items: a.removed });
        this.redoStack = [];
        this.onChange();
      }
      return;
    }
    const s = a.stroke;
    if (s.points.length === 0) return;
    this.strokes.push(s);
    this.undoStack.push({ type: 'add', stroke: s });
    this.redoStack = [];
    this.requestDraw();
    this.onChange();
  }

  _discardActiveIfTouch() {
    if (this.active && this.active.type === 'touch') {
      this.active = null;
      this.requestDraw();
    }
  }

  _point(e) {
    const d = this.screenToDoc(e.clientX, e.clientY);
    let p = 0.5;
    if (e.pointerType === 'pen' && e.pressure > 0) p = e.pressure;
    return { x: d.x, y: d.y, p };
  }

  // ----- stroke eraser -----
  _strokeEraseAt(pt) {
    const r = Math.max(ERASE_HIT, this.eraserSize / 2);
    let changed = false;
    for (let i = this.strokes.length - 1; i >= 0; i--) {
      if (this._strokeHit(this.strokes[i], pt, r)) {
        this.active.removed.push({ index: i, stroke: this.strokes[i] });
        this.strokes.splice(i, 1);
        changed = true;
      }
    }
    if (changed) this.requestDraw();
  }

  _strokeHit(stroke, pt, r) {
    if (stroke.shape) return this._shapeHit(stroke, pt, r);
    const pad = r + stroke.size / 2;
    const pts = stroke.points;
    if (pts.length === 1) {
      return Math.hypot(pts[0].x - pt.x, pts[0].y - pt.y) <= pad;
    }
    for (let i = 1; i < pts.length; i++) {
      if (distToSeg(pt, pts[i - 1], pts[i]) <= pad) return true;
    }
    return false;
  }

  _shapeHit(stroke, pt, r) {
    const pad = r + stroke.size / 2;
    const p0 = stroke.points[0], p1 = stroke.points[1] || stroke.points[0];
    if (stroke.shape === 'line') return distToSeg(pt, p0, p1) <= pad;
    const x0 = Math.min(p0.x, p1.x), y0 = Math.min(p0.y, p1.y);
    const x1 = Math.max(p0.x, p1.x), y1 = Math.max(p0.y, p1.y);
    if (stroke.shape === 'rect') {
      const c = [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }];
      for (let i = 0; i < 4; i++) if (distToSeg(pt, c[i], c[(i + 1) % 4]) <= pad) return true;
      return false;
    }
    // ellipse: test distance to a sampled outline
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, rx = (x1 - x0) / 2, ry = (y1 - y0) / 2;
    let prev = null;
    for (let i = 0; i <= 24; i++) {
      const a = (i / 24) * Math.PI * 2;
      const q = { x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
      if (prev && distToSeg(pt, prev, q) <= pad) return true;
      prev = q;
    }
    return false;
  }

  // ----- undo / redo -----
  undo() {
    const op = this.undoStack.pop();
    if (!op) return;
    if (op.type === 'add') {
      const idx = this.strokes.lastIndexOf(op.stroke);
      if (idx !== -1) this.strokes.splice(idx, 1);
    } else if (op.type === 'delete') {
      const items = op.items.slice().sort((a, b) => a.index - b.index);
      for (const it of items) this.strokes.splice(it.index, 0, it.stroke);
    }
    this.redoStack.push(op);
    this.requestDraw();
    this.onChange();
  }

  redo() {
    const op = this.redoStack.pop();
    if (!op) return;
    if (op.type === 'add') {
      this.strokes.push(op.stroke);
    } else if (op.type === 'delete') {
      const items = op.items.slice().sort((a, b) => b.index - a.index);
      for (const it of items) {
        const idx = this.strokes.indexOf(it.stroke);
        if (idx !== -1) this.strokes.splice(idx, 1);
      }
    }
    this.undoStack.push(op);
    this.requestDraw();
    this.onChange();
  }

  canUndo() { return this.undoStack.length > 0; }
  canRedo() { return this.redoStack.length > 0; }

  // ----- pan / zoom -----
  _startMousePan(e) {
    this.mousePan = { last: { x: e.clientX, y: e.clientY } };
  }

  panBy(dx, dy) {
    this.offsetX += dx;
    this.offsetY += dy;
    this.requestDraw();
  }

  _startGesture() {
    const touches = [...this.pointers.values()].filter((p) => p.type === 'touch');
    if (touches.length === 1) {
      this.gesture = { mode: 'pan', last: { x: touches[0].x, y: touches[0].y } };
    } else if (touches.length >= 2) {
      this.gesture = {
        mode: 'pinch',
        center: midpoint(touches[0], touches[1]),
        dist: dist(touches[0], touches[1]),
      };
    }
  }

  _updateGesture() {
    const touches = [...this.pointers.values()].filter((p) => p.type === 'touch');
    if (!this.gesture) return;
    if (this.gesture.mode === 'pan' && touches.length >= 1) {
      const t = touches[0];
      this.offsetX += t.x - this.gesture.last.x;
      this.offsetY += t.y - this.gesture.last.y;
      this.gesture.last = { x: t.x, y: t.y };
      this.requestDraw();
    } else if (touches.length >= 2) {
      if (this.gesture.mode !== 'pinch') {
        this.gesture = { mode: 'pinch', center: midpoint(touches[0], touches[1]), dist: dist(touches[0], touches[1]) };
        return;
      }
      const c = midpoint(touches[0], touches[1]);
      const d = dist(touches[0], touches[1]);
      const r = this.canvas.getBoundingClientRect();
      const newScale = clamp(this.scale * (d / (this.gesture.dist || d)), MIN_SCALE, MAX_SCALE);
      const realFactor = newScale / this.scale;
      const ax = c.x - r.left, ay = c.y - r.top;
      const lastAx = this.gesture.center.x - r.left, lastAy = this.gesture.center.y - r.top;
      // 1) pan by how far the two-finger center moved
      this.offsetX += ax - lastAx;
      this.offsetY += ay - lastAy;
      // 2) zoom about the current center, keeping that document point fixed
      this.offsetX = ax - (ax - this.offsetX) * realFactor;
      this.offsetY = ay - (ay - this.offsetY) * realFactor;
      this.scale = newScale;
      this.gesture.center = c;
      this.gesture.dist = d;
      this.onZoom(this.scale);
      this.requestDraw();
    }
  }

  zoomBy(factor, cx, cy) {
    const newScale = clamp(this.scale * factor, MIN_SCALE, MAX_SCALE);
    const realFactor = newScale / this.scale;
    this.offsetX = cx - (cx - this.offsetX) * realFactor;
    this.offsetY = cy - (cy - this.offsetY) * realFactor;
    this.scale = newScale;
    this.onZoom(this.scale);
    this.requestDraw();
  }

  // ----- export -----
  // Bounding box of all stroke geometry (document units), or null if empty.
  _contentBounds() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of this.strokes) {
      if (s.tool === 'erase') continue; // erases don't define content extents
      const half = s.size / 2 + 1;
      for (const p of s.points) {
        if (p.x - half < minX) minX = p.x - half;
        if (p.y - half < minY) minY = p.y - half;
        if (p.x + half > maxX) maxX = p.x + half;
        if (p.y + half > maxY) maxY = p.y + half;
      }
    }
    if (!isFinite(minX)) return null;
    return { minX, minY, maxX, maxY };
  }

  // Render the drawn content (its bounding box) to a canvas for PDF/PNG/JPG.
  renderExportCanvas(includeBackground) {
    const out = document.createElement('canvas');
    const ctx = out.getContext('2d');
    const bbox = this._contentBounds();

    if (!bbox) {
      out.width = out.height = 64;
      if (includeBackground) { ctx.fillStyle = this.bgColor; ctx.fillRect(0, 0, 64, 64); }
      return out;
    }

    const pad = 24;
    const minX = bbox.minX - pad, minY = bbox.minY - pad;
    const wDoc = (bbox.maxX - bbox.minX) + pad * 2;
    const hDoc = (bbox.maxY - bbox.minY) + pad * 2;

    // cap output resolution so huge boards don't blow up memory
    let rs = RENDER_SCALE;
    const MAX_DIM = 5000;
    if (Math.max(wDoc, hDoc) * rs > MAX_DIM) rs = MAX_DIM / Math.max(wDoc, hDoc);

    out.width = Math.max(1, Math.round(wDoc * rs));
    out.height = Math.max(1, Math.round(hDoc * rs));

    if (includeBackground) {
      drawBackground(ctx, this.background, this.bgColor, -minX * rs, -minY * rs, rs, out.width, out.height, this.patternOpacity);
    }
    ctx.setTransform(rs, 0, 0, rs, -minX * rs, -minY * rs);
    for (const s of this.strokes) this._paintStroke(ctx, s);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    return out;
  }
}

// ---------- geometry helpers ----------
function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
function midpoint(a, b) { return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function distToSeg(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}
