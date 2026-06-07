// Wires the UI to the engine and the document library.
import { CanvasEngine } from './canvas.js';
import { exportPDF } from './pdf.js';
import * as store from './storage.js';

const $ = (id) => document.getElementById(id);

const engine = new CanvasEngine($('canvas'), $('stage'), {
  onChange: () => { onDocChanged(); },
  onZoom: (s) => updateZoomLabel(s),
});

const SHAPE_TOOLS = ['line', 'rect', 'ellipse'];
const ERASER_TOOLS = ['erase', 'stroke-erase'];

let currentDoc = null;
let saveTimer = 0;

// ---------- boot ----------
async function boot() {
  engine.resize();

  // restore settings
  const fingerMode = (await store.getMeta('fingerMode')) || 'erase';
  engine.fingerMode = fingerMode;
  $('finger-mode').value = fingerMode;
  $('include-bg').checked = (await store.getMeta('includeBg')) !== false;

  const savedOpacity = await store.getMeta('patternOpacity');
  if (typeof savedOpacity === 'number') engine.patternOpacity = savedOpacity;
  $('pattern-strength').value = Math.round(engine.patternOpacity * 100);

  loadRecentColors();
  setColor(engine.color);
  selectTool('pen'); // also syncs the size slider to the pen's size

  // open last document, or create one
  let docs = await store.listDocs();
  if (docs.length === 0) {
    currentDoc = await createDoc('Untitled');
  } else {
    const lastId = await store.getMeta('lastOpenId');
    currentDoc = docs.find((d) => d.id === lastId) || docs[0];
  }
  openDoc(currentDoc);

  registerSW();
}

function openDoc(doc) {
  currentDoc = doc;
  $('doc-name').value = doc.name;
  $('bg-select').value = doc.background || 'blank';
  const bgColor = doc.bgColor || '#ffffff';
  $('bg-color').value = bgColor;
  $('bg-color-dot').style.background = bgColor;
  engine.load(doc);
  store.setMeta('lastOpenId', doc.id);
  updateUndoRedo();
}

async function createDoc(name) {
  const doc = {
    id: store.newId(),
    name: name || 'Untitled',
    background: 'blank',
    bgColor: '#ffffff',
    strokes: [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
  await store.saveDoc(doc);
  return doc;
}

// ---------- autosave ----------
function onDocChanged() {
  updateUndoRedo();
  scheduleSave();
}

function scheduleSave() {
  if (!currentDoc) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const data = engine.serialize();
    currentDoc.strokes = data.strokes;
    currentDoc.background = data.background;
    currentDoc.bgColor = data.bgColor;
    await store.saveDoc(currentDoc);
  }, 500);
}

async function saveNow() {
  if (!currentDoc) return;
  clearTimeout(saveTimer);
  const data = engine.serialize();
  currentDoc.strokes = data.strokes;
  currentDoc.background = data.background;
  currentDoc.bgColor = data.bgColor;
  await store.saveDoc(currentDoc);
}

// ---------- tools ----------
function selectTool(tool) {
  engine.tool = tool;
  document.querySelectorAll('.tool').forEach((b) => {
    b.classList.toggle('active', b.dataset.tool === tool);
  });
  engine.canvas.style.cursor = tool === 'hand' ? 'grab' : 'crosshair';
  syncSizeForTool(tool);
}

// The single slider edits whichever tool is active; pen and eraser sizes are
// stored independently on the engine. (Shapes use the pen size.)
function syncSizeForTool(tool) {
  const v = ERASER_TOOLS.includes(tool) ? engine.eraserSize : engine.penSize;
  $('size-input').value = v;
  updateSizeDot(v);
}

document.querySelectorAll('.tool').forEach((btn) => {
  btn.addEventListener('click', () => selectTool(btn.dataset.tool));
});

// ---------- color ----------
function setColor(hex) {
  engine.color = hex;
  $('color-input').value = hex;
  document.documentElement.style.setProperty('--current-color', hex);
}

$('color-input').addEventListener('input', (e) => {
  setColor(e.target.value);
});
$('color-input').addEventListener('change', (e) => {
  addRecentColor(e.target.value);
});

function loadRecentColors() {
  const stored = JSON.parse(localStorage.getItem('recentColors') || '[]');
  const defaults = ['#111318', '#e0564f', '#2e7d32', '#1565c0', '#f9a825'];
  const colors = (stored.length ? stored : defaults).slice(0, 6);
  renderRecentColors(colors);
}

function addRecentColor(hex) {
  let colors = JSON.parse(localStorage.getItem('recentColors') || '[]');
  colors = [hex, ...colors.filter((c) => c.toLowerCase() !== hex.toLowerCase())].slice(0, 6);
  localStorage.setItem('recentColors', JSON.stringify(colors));
  renderRecentColors(colors);
}

function renderRecentColors(colors) {
  const wrap = $('recent-colors');
  wrap.innerHTML = '';
  colors.forEach((c) => {
    const s = document.createElement('span');
    s.className = 'swatch';
    s.style.background = c;
    s.title = c;
    s.addEventListener('click', () => { setColor(c); selectTool('pen'); });
    wrap.appendChild(s);
  });
}

// ---------- size ----------
function updateSizeDot(v) {
  const dot = $('size-dot');
  const d = Math.max(2, Math.min(24, Number(v)));
  dot.style.width = d + 'px';
  dot.style.height = d + 'px';
}
$('size-input').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  if (ERASER_TOOLS.includes(engine.tool)) engine.eraserSize = v;
  else engine.penSize = v;
  updateSizeDot(v);
});

// ---------- background ----------
$('bg-select').addEventListener('change', (e) => {
  engine.setBackground(e.target.value);
});
$('bg-color').addEventListener('input', (e) => {
  engine.setBgColor(e.target.value);
  $('bg-color-dot').style.background = e.target.value;
});

// ---------- undo / redo ----------
function updateUndoRedo() {
  $('btn-undo').disabled = !engine.canUndo();
  $('btn-redo').disabled = !engine.canRedo();
}
$('btn-undo').addEventListener('click', () => engine.undo());
$('btn-redo').addEventListener('click', () => engine.redo());

document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  const k = e.key.toLowerCase();
  if (k === 'z' && !e.shiftKey) { e.preventDefault(); engine.undo(); }
  else if ((k === 'z' && e.shiftKey) || k === 'y') { e.preventDefault(); engine.redo(); }
});

// ---------- pressure ----------
$('btn-pressure').addEventListener('click', () => {
  engine.pressure = !engine.pressure;
  const btn = $('btn-pressure');
  btn.classList.toggle('on', engine.pressure);
  btn.title = 'Pressure sensitivity (' + (engine.pressure ? 'on' : 'off') + ')';
});

// ---------- settings ----------
$('btn-settings').addEventListener('click', () => $('settings').classList.remove('hidden'));
$('btn-close-settings').addEventListener('click', () => $('settings').classList.add('hidden'));
$('finger-mode').addEventListener('change', (e) => {
  engine.fingerMode = e.target.value;
  store.setMeta('fingerMode', e.target.value);
});
$('include-bg').addEventListener('change', (e) => {
  store.setMeta('includeBg', e.target.checked);
});
$('pattern-strength').addEventListener('input', (e) => {
  const v = Number(e.target.value) / 100;
  engine.setPatternOpacity(v);
  store.setMeta('patternOpacity', v);
});

// ---------- export ----------
const exportMenu = $('export-menu');
$('btn-export').addEventListener('click', (e) => {
  e.stopPropagation();
  exportMenu.classList.toggle('hidden');
});
document.addEventListener('click', () => exportMenu.classList.add('hidden'));
exportMenu.querySelectorAll('.menu-item').forEach((btn) => {
  btn.addEventListener('click', async () => {
    exportMenu.classList.add('hidden');
    await saveNow();
    const name = currentDoc?.name || 'sketch';
    const includeBg = $('include-bg').checked;
    if (btn.dataset.fmt === 'pdf') exportPDF(engine, name, includeBg);
    else exportImage(name, btn.dataset.fmt, includeBg);
  });
});

function exportImage(name, fmt, includeBg) {
  // JPEG has no transparency, so always bake a background for it.
  const canvas = engine.renderExportCanvas(fmt === 'jpg' ? true : includeBg);
  const mime = fmt === 'jpg' ? 'image/jpeg' : 'image/png';
  const data = canvas.toDataURL(mime, fmt === 'jpg' ? 0.92 : undefined);
  const safe = (name || 'sketch').replace(/[^\w\-. ]+/g, '_').trim() || 'sketch';
  const a = document.createElement('a');
  a.href = data;
  a.download = safe + '.' + fmt;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---------- document name ----------
$('doc-name').addEventListener('change', async (e) => {
  if (!currentDoc) return;
  currentDoc.name = e.target.value.trim() || 'Untitled';
  e.target.value = currentDoc.name;
  await store.saveDoc(currentDoc);
});

// ---------- library ----------
$('btn-library').addEventListener('click', async () => {
  await saveNow();
  await renderLibrary();
  $('library').classList.remove('hidden');
});
$('btn-close-library').addEventListener('click', () => $('library').classList.add('hidden'));
$('btn-new-doc').addEventListener('click', async () => {
  await saveNow();
  const doc = await createDoc('Untitled');
  openDoc(doc);
  $('library').classList.add('hidden');
});

async function renderLibrary() {
  const list = $('doc-list');
  list.innerHTML = '';
  const docs = await store.listDocs();
  if (docs.length === 0) {
    list.innerHTML = '<li class="doc-meta">No documents yet.</li>';
    return;
  }
  docs.forEach((doc) => {
    const li = document.createElement('li');
    li.className = 'doc-item' + (doc.id === currentDoc?.id ? ' current' : '');

    const info = document.createElement('div');
    info.className = 'doc-info';
    const title = document.createElement('div');
    title.className = 'doc-title';
    title.textContent = doc.name;
    const meta = document.createElement('div');
    meta.className = 'doc-meta';
    const count = (doc.strokes || []).length;
    meta.textContent = `${count} stroke${count === 1 ? '' : 's'} · ${formatDate(doc.updatedAt)}`;
    info.appendChild(title);
    info.appendChild(meta);
    info.addEventListener('click', async () => {
      await saveNow();
      openDoc(doc);
      $('library').classList.add('hidden');
    });

    const renameBtn = iconButton('✎', 'Rename', async () => {
      const name = prompt('Rename document', doc.name);
      if (name && name.trim()) {
        doc.name = name.trim();
        await store.saveDoc(doc);
        if (doc.id === currentDoc?.id) $('doc-name').value = doc.name;
        renderLibrary();
      }
    });
    const delBtn = iconButton('🗑', 'Delete', async () => {
      if (!confirm(`Delete "${doc.name}"? This cannot be undone.`)) return;
      await store.deleteDoc(doc.id);
      if (doc.id === currentDoc?.id) {
        const docs2 = await store.listDocs();
        currentDoc = docs2[0] || (await createDoc('Untitled'));
        openDoc(currentDoc);
      }
      renderLibrary();
    });
    delBtn.classList.add('del');

    li.appendChild(info);
    li.appendChild(renameBtn);
    li.appendChild(delBtn);
    list.appendChild(li);
  });
}

function iconButton(label, title, onClick) {
  const b = document.createElement('button');
  b.className = 'icon-btn';
  b.textContent = label;
  b.title = title;
  b.addEventListener('click', onClick);
  return b;
}

// ---------- zoom ----------
function updateZoomLabel(scale) {
  $('zoom-level').textContent = Math.round(scale * 100) + '%';
}

// Scroll wheel zooms about the cursor.
$('stage').addEventListener('wheel', (e) => {
  e.preventDefault();
  const r = engine.canvas.getBoundingClientRect();
  engine.zoomBy(e.deltaY < 0 ? 1.1 : 0.9, e.clientX - r.left, e.clientY - r.top);
}, { passive: false });

// +/- buttons zoom about the viewport center.
$('zoom-in').addEventListener('click', () => engine.zoomBy(1.2, engine.cssW / 2, engine.cssH / 2));
$('zoom-out').addEventListener('click', () => engine.zoomBy(1 / 1.2, engine.cssW / 2, engine.cssH / 2));

function formatDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) +
    ' ' + d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

function registerSW() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch((err) => console.warn('SW failed', err));
  }
}

window.addEventListener('beforeunload', () => { saveNow(); });

boot();
