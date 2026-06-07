# Sketchpad

A no-frills, **offline-first** drawing & notes canvas that installs to your
tablet (or phone) home screen as a PWA. No account, no paywall, no server —
it's a handful of static files and all your work stays on the device.

## Features

- **Infinite whiteboard canvas** — pan/zoom anywhere; drawing near an edge opens up more space
- **Pen**, **true eraser** (erases pixels), **stroke eraser** (deletes whole strokes)
- Color picker with preset & recent swatches; independent pen & eraser sizes
- Undo / redo
- Optional **pressure sensitivity** (off by default — toggle it on for calligraphic strokes)
- Backgrounds: **blank**, **grid**, **dots** + adjustable **background color**
- **Export** to **PDF / PNG / JPG** (sized to your drawing's bounds, high resolution)
- On-device **document library** (auto-saved to IndexedDB)

## Input model (tablet)

- **Pen** → draws with the selected tool
- **One finger** → erase / draw / pan — configurable in Settings (default: erase)
- **Two fingers** → pan & zoom

A pen always uses the selected tool, so resting your palm won't leave marks.

## Run it / install it

It's pure static files — serve the folder over HTTP and open it.

**Quick local test (any machine with Python):**

```bash
cd sketchpad
python -m http.server 8000
# open http://localhost:8000
```

**Install on the Lenovo tablet (fully offline afterwards):**

1. Host the `sketchpad/` folder somewhere reachable once — e.g. push it to a
   free static host like GitHub Pages or Netlify, or serve it from any device
   on your network for the initial visit.
2. On the tablet, open the URL in Chrome.
3. Chrome menu → **Install app** / **Add to Home screen**.
4. The service worker caches everything on first load. From then on the app
   icon opens it **with no internet and no PC running**.

> A service worker only registers over HTTPS or `localhost`, so the one-time
> install needs an `https://` URL (GitHub Pages/Netlify both provide one).

## Tech

Vanilla JS + HTML Canvas, no build step. Strokes are stored as vectors (clean
undo/redo and crisp PDF export). `jsPDF` is vendored locally under
`js/vendor/` so export works offline.

## Files

```
index.html          UI + toolbar
style.css           styles
manifest.json       PWA manifest
sw.js               offline service worker
icon.svg            app icon
js/app.js           UI wiring, document library, autosave
js/canvas.js        drawing engine (strokes, erasers, pan/zoom, undo)
js/backgrounds.js   grid / dots / blank rendering
js/storage.js       IndexedDB document store
js/pdf.js           PDF export
js/vendor/          jsPDF (vendored)
```
