// PDF export via the vendored jsPDF (offline). The page is sized to the drawn
// content's aspect ratio (the canvas is unbounded, so there's no fixed page).

export function exportPDF(engine, name, includeBackground) {
  const jsPDFCtor = window.jspdf && window.jspdf.jsPDF;
  if (!jsPDFCtor) {
    alert('PDF library failed to load.');
    return;
  }
  const canvas = engine.renderExportCanvas(includeBackground);
  const imgData = canvas.toDataURL('image/png');

  // Fit the content to a page whose longest side is a fixed number of points.
  const MAX_SIDE = 1000; // pt
  const s = MAX_SIDE / Math.max(canvas.width, canvas.height);
  const wPt = canvas.width * s;
  const hPt = canvas.height * s;

  const pdf = new jsPDFCtor({
    unit: 'pt',
    orientation: wPt >= hPt ? 'landscape' : 'portrait',
    format: [wPt, hPt],
  });
  const pw = pdf.internal.pageSize.getWidth();
  const ph = pdf.internal.pageSize.getHeight();
  pdf.addImage(imgData, 'PNG', 0, 0, pw, ph);

  const safe = (name || 'sketch').replace(/[^\w\-. ]+/g, '_').trim() || 'sketch';
  pdf.save(safe + '.pdf');
}
