import { useState, useEffect, useRef } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { syncAfterMutation } from '../sync.js';
import { uuid, now, formatCurrency } from '../utils.js';

const PALETTE = ['#6366f1', '#f59e0b', '#10b981', '#ec4899', '#8b5cf6', '#06b6d4', '#f97316', '#84cc16', '#e11d48', '#64748b'];

export function MoneyCategories({ budgetId }) {
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const saveTimer = useRef(null);

  async function load() {
    const cats = await db.getCategories(budgetId);
    cats.sort((a, b) => a.sortOrder - b.sortOrder);
    setCategories(cats);
    setLoading(false);
  }

  useEffect(() => { load(); }, [budgetId]);

  function scheduleSync() {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => syncAfterMutation(), 500);
  }

  async function updateCat(id, field, value) {
    const cat = categories.find(c => c.id === id);
    if (!cat) return;
    const updated = { ...cat, [field]: value, updatedAt: now() };
    await db.putCategory(updated);
    setCategories(prev => prev.map(c => c.id === id ? updated : c));
    scheduleSync();
  }

  async function addCategory() {
    const ts = now();
    const cat = {
      id: uuid(),
      budgetId,
      name: '',
      color: PALETTE[categories.length % PALETTE.length],
      targetHours: 0,
      sortOrder: categories.length,
      createdAt: ts,
      updatedAt: ts,
    };
    await db.putCategory(cat);
    setCategories(prev => [...prev, cat]);
    scheduleSync();
  }

  async function removeCat(id) {
    await db.deleteCategory(id, now());
    setCategories(prev => prev.filter(c => c.id !== id));
    syncAfterMutation();
  }

  async function moveCat(id, dir) {
    const idx = categories.findIndex(c => c.id === id);
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= categories.length) return;

    const reordered = [...categories];
    [reordered[idx], reordered[newIdx]] = [reordered[newIdx], reordered[idx]];

    const ts = now();
    const updated = reordered.map((c, i) => ({ ...c, sortOrder: i, updatedAt: ts }));
    for (const c of updated) await db.putCategory(c);
    setCategories(updated);
    scheduleSync();
  }

  if (loading) return html`<div class="loading">Loading...</div>`;

  const totalTarget = categories.reduce((s, c) => s + (c.targetHours || 0), 0);

  return html`
    <div class="categories-view">
      <h2>Spending Categories</h2>
      <p class="subtitle">Total: ${formatCurrency(totalTarget)} / month</p>

      <div class="cat-list">
        ${categories.map((cat, i) => html`
          <div class="cat-row" key=${cat.id}>
            <div class="cat-color-wrap">
              <input type="color" class="cat-color" value=${cat.color}
                onInput=${(e) => updateCat(cat.id, 'color', e.target.value)} />
            </div>
            <input class="cat-name-input" type="text" value=${cat.name}
              placeholder="Category name"
              onInput=${(e) => updateCat(cat.id, 'name', e.target.value)} />
            <div class="cat-hours-wrap">
              <span class="cat-hours-label">$</span>
              <input class="cat-hours-input cat-amount-input" type="number" value=${cat.targetHours}
                min="0" step="1"
                onInput=${(e) => updateCat(cat.id, 'targetHours', parseFloat(e.target.value) || 0)} />
            </div>
            <div class="cat-actions">
              <button class="cat-move" onClick=${() => moveCat(cat.id, -1)} disabled=${i === 0}>↑</button>
              <button class="cat-move" onClick=${() => moveCat(cat.id, 1)} disabled=${i === categories.length - 1}>↓</button>
              <button class="cat-delete" onClick=${() => removeCat(cat.id)}>×</button>
            </div>
          </div>
        `)}
      </div>

      <button class="btn btn-add" onClick=${addCategory}>+ Add Category</button>
    </div>
  `;
}
