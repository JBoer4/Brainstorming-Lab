import { useState, useEffect, useRef } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { syncAfterMutation } from '../sync.js';
import { navigate } from '../router.js';
import { uuid, now, today, toDateStr, parseDate, formatShort, dayName, calcHours } from '../utils.js';

export function DailyLog({ budgetId, date: dateProp }) {
  const currentDate = dateProp || today();
  const [categories, setCategories] = useState([]);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const saveTimer = useRef(null);

  async function load() {
    const cats = await db.getCategories(budgetId);
    cats.sort((a, b) => a.sortOrder - b.sortOrder);
    setCategories(cats);

    const allEntries = await db.getEntries(budgetId);
    setEntries(allEntries.filter(e => e.date === currentDate));
    setLoading(false);
  }

  useEffect(() => { load(); }, [budgetId, currentDate]);

  function scheduleSync() {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => syncAfterMutation(), 500);
  }

  async function addEntry(categoryId) {
    const ts = now();
    const entry = {
      id: uuid(),
      budgetId,
      categoryId,
      date: currentDate,
      hours: 0,
      startTime: null,
      endTime: null,
      note: null,
      createdAt: ts,
      updatedAt: ts,
    };
    await db.putEntry(entry);
    setEntries(prev => [...prev, entry]);
    scheduleSync();
  }

  async function updateEntry(id, field, value) {
    const entry = entries.find(e => e.id === id);
    if (!entry) return;
    const updated = { ...entry, [field]: value, updatedAt: now() };

    // Auto-calc hours from times
    if ((field === 'startTime' || field === 'endTime')) {
      const st = field === 'startTime' ? value : updated.startTime;
      const et = field === 'endTime' ? value : updated.endTime;
      const h = calcHours(st, et);
      if (h !== null) updated.hours = h;
    }

    await db.putEntry(updated);
    setEntries(prev => prev.map(e => e.id === id ? updated : e));
    scheduleSync();
  }

  async function removeEntry(id) {
    await db.deleteEntry(id, now());
    setEntries(prev => prev.filter(e => e.id !== id));
    syncAfterMutation();
  }

  function prevDay() {
    const d = parseDate(currentDate);
    d.setDate(d.getDate() - 1);
    navigate(`/budget/${budgetId}/log/${toDateStr(d)}`);
  }

  function nextDay() {
    const d = parseDate(currentDate);
    d.setDate(d.getDate() + 1);
    navigate(`/budget/${budgetId}/log/${toDateStr(d)}`);
  }

  if (loading) return html`<div class="loading">Loading...</div>`;

  const dateObj = parseDate(currentDate);
  const isToday = currentDate === today();
  const dayTotal = entries.reduce((s, e) => s + (e.hours || 0), 0);

  return html`
    <div class="daily-log">
      <div class="date-nav">
        <button class="nav-arrow" onClick=${prevDay}>‹</button>
        <div class="date-display">
          <span class="date-day">${dayName(dateObj)}</span>
          <span class="date-full">${formatShort(dateObj)}${isToday ? ' (today)' : ''}</span>
        </div>
        <button class="nav-arrow" onClick=${nextDay}>›</button>
      </div>

      <p class="day-total">${dayTotal.toFixed(1)}h logged</p>

      <div class="log-categories">
        ${categories.map(cat => {
          const catEntries = entries.filter(e => e.categoryId === cat.id);
          return html`
            <div class="log-cat" key=${cat.id}>
              <div class="log-cat-header">
                <span class="log-cat-dot" style=${{ background: cat.color }}></span>
                <span class="log-cat-name">${cat.name}</span>
                <span class="log-cat-total">${catEntries.reduce((s, e) => s + (e.hours || 0), 0).toFixed(1)}h</span>
              </div>
              <div class="log-entries">
                ${catEntries.map(entry => html`
                  <div class="log-entry" key=${entry.id}>
                    <input class="entry-hours" type="number" value=${entry.hours}
                      min="0" max="24" step="0.25" placeholder="hrs"
                      onInput=${(e) => updateEntry(entry.id, 'hours', parseFloat(e.target.value) || 0)} />
                    <input class="entry-time" type="time" value=${entry.startTime || ''}
                      onInput=${(e) => updateEntry(entry.id, 'startTime', e.target.value || null)} />
                    <span class="entry-dash">–</span>
                    <input class="entry-time" type="time" value=${entry.endTime || ''}
                      onInput=${(e) => updateEntry(entry.id, 'endTime', e.target.value || null)} />
                    <button class="entry-delete" onClick=${() => removeEntry(entry.id)}>×</button>
                  </div>
                `)}
              </div>
              <button class="btn-add-entry" onClick=${() => addEntry(cat.id)}>+ Add</button>
            </div>
          `;
        })}
      </div>
    </div>
  `;
}
