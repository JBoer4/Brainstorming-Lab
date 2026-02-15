import { useState, useEffect } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { navigate } from '../router.js';
import { syncAfterMutation } from '../sync.js';
import { uuid, now } from '../utils.js';

const DEFAULT_CATEGORIES = [
  { name: 'Sleep', color: '#6366f1', targetHours: 56 },
  { name: 'Work', color: '#f59e0b', targetHours: 40 },
  { name: 'Exercise', color: '#10b981', targetHours: 5 },
  { name: 'Leisure', color: '#ec4899', targetHours: 10 },
];

async function seedBudget() {
  const ts = now();
  const budget = {
    id: uuid(),
    name: 'Weekly Time Budget',
    type: 'time',
    periodType: 'weekly',
    periodStartDay: 0,
    createdAt: ts,
    updatedAt: ts,
  };
  await db.putBudget(budget);

  for (let i = 0; i < DEFAULT_CATEGORIES.length; i++) {
    const cat = DEFAULT_CATEGORIES[i];
    await db.putCategory({
      id: uuid(),
      budgetId: budget.id,
      name: cat.name,
      color: cat.color,
      targetHours: cat.targetHours,
      sortOrder: i,
      createdAt: ts,
      updatedAt: ts,
    });
  }
  syncAfterMutation();
  return budget;
}

export function Dashboard() {
  const [budgets, setBudgets] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    let list = await db.getBudgets();
    if (list.length === 0) {
      await seedBudget();
      list = await db.getBudgets();
    }
    setBudgets(list);
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  if (loading) return html`<div class="loading">Loading...</div>`;

  return html`
    <div class="dashboard">
      <div class="card-grid">
        ${budgets.map(b => html`
          <button class="budget-card" key=${b.id} onClick=${() => navigate('/budget/' + b.id)}>
            <div class="card-icon">${b.type === 'time' ? '⏱' : '$'}</div>
            <div class="card-name">${b.name}</div>
            <div class="card-type">${b.periodType}</div>
          </button>
        `)}
        <button class="budget-card add-card" onClick=${async () => {
          const ts = now();
          const budget = {
            id: uuid(),
            name: 'New Budget',
            type: 'time',
            periodType: 'weekly',
            periodStartDay: 0,
            createdAt: ts,
            updatedAt: ts,
          };
          await db.putBudget(budget);
          syncAfterMutation();
          navigate('/budget/' + budget.id);
        }}>
          <div class="card-icon">+</div>
          <div class="card-name">New Budget</div>
        </button>
      </div>
    </div>
  `;
}
