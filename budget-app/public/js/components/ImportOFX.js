import { useState, useRef } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { navigate } from '../router.js';
import { syncAfterMutation } from '../sync.js';
import { api } from '../api.js';
import { uuid, now, formatCurrency } from '../utils.js';

export function ImportOFX({ budgetId }) {
  const [parsed, setParsed] = useState(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const fileRef = useRef(null);

  async function handleFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    setError(null);
    setParsed(null);

    try {
      const text = await file.text();
      const transactions = await api.importOFX(budgetId, text);
      if (transactions.length === 0) {
        setError('No transactions found in file');
        return;
      }
      setParsed(transactions);
    } catch (err) {
      setError('Failed to parse file: ' + err.message);
    }
  }

  async function importAll() {
    if (!parsed || importing) return;
    setImporting(true);
    setError(null);

    try {
      const ts = now();
      const records = parsed.map(t => ({
        id: uuid(),
        budgetId,
        categoryId: null,
        date: t.date,
        amount: t.amount,
        payee: t.payee || '',
        memo: t.memo || '',
        fitid: t.fitid || '',
        trntype: t.trntype || '',
        createdAt: ts,
        updatedAt: ts,
      }));

      // Save to server via batch endpoint
      await api.batchCreateTransactions(budgetId, records);

      // Also save to local IndexedDB for offline access
      for (const r of records) {
        await db.putTransactionClean(r);
      }

      syncAfterMutation();
      setResult({ count: records.length });
    } catch (err) {
      setError('Import failed: ' + err.message);
    } finally {
      setImporting(false);
    }
  }

  if (result) {
    return html`
      <div class="import-view">
        <h2>Import Complete</h2>
        <div class="import-result">
          <p>${result.count} transactions imported</p>
          <button class="btn" onClick=${() => navigate('/budget/' + budgetId + '/transactions')}>
            View Transactions
          </button>
          <button class="btn btn-secondary" onClick=${() => { setResult(null); setParsed(null); if (fileRef.current) fileRef.current.value = ''; }}>
            Import More
          </button>
        </div>
      </div>
    `;
  }

  return html`
    <div class="import-view">
      <h2>Import OFX</h2>
      <p class="subtitle">Upload a bank statement (.ofx or .qfx file)</p>

      <div class="import-file-wrap">
        <input type="file" accept=".ofx,.qfx" ref=${fileRef}
          onChange=${handleFile} class="import-file-input" />
      </div>

      ${error && html`<div class="import-error">${error}</div>`}

      ${parsed && html`
        <div class="import-preview-wrap">
          <h3>${parsed.length} transactions found</h3>
          <div class="import-preview">
            ${parsed.map((t, i) => html`
              <div class="import-row" key=${i}>
                <span class="import-date">${t.date || '—'}</span>
                <span class="import-payee">${t.payee || t.memo || '—'}</span>
                <span class="import-amount ${t.amount < 0 ? 'negative' : 'positive'}">
                  ${formatCurrency(t.amount)}
                </span>
              </div>
            `)}
          </div>
          <button class="btn import-btn" onClick=${importAll} disabled=${importing}>
            ${importing ? 'Importing...' : `Import All (${parsed.length})`}
          </button>
        </div>
      `}
    </div>
  `;
}
