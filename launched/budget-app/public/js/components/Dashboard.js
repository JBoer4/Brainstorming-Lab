import { useState, useEffect } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { navigate } from '../router.js';
import { syncAfterMutation } from '../sync.js';
import { uuid, now } from '../utils.js';

const DEFAULT_TIME_CATEGORIES = [
  { name: 'Sleep', color: '#6366f1', targetHours: 56 },
  { name: 'Work', color: '#f59e0b', targetHours: 40 },
  { name: 'Exercise', color: '#10b981', targetHours: 5 },
  { name: 'Leisure', color: '#ec4899', targetHours: 10 },
];

const DEFAULT_MONEY_CATEGORIES = [
  { name: 'Housing', color: '#6366f1', targetHours: 0 },
  { name: 'Groceries', color: '#10b981', targetHours: 0 },
  { name: 'Transport', color: '#f59e0b', targetHours: 0 },
  { name: 'Dining Out', color: '#ec4899', targetHours: 0 },
  { name: 'Utilities', color: '#06b6d4', targetHours: 0 },
  { name: 'Entertainment', color: '#8b5cf6', targetHours: 0 },
  { name: 'Other', color: '#64748b', targetHours: 0 },
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

  for (let i = 0; i < DEFAULT_TIME_CATEGORIES.length; i++) {
    const cat = DEFAULT_TIME_CATEGORIES[i];
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
  const [showTypePicker, setShowTypePicker] = useState(false);

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

  async function createBudget(type) {
    const ts = now();
    const isMoney = type === 'money';
    const budget = {
      id: uuid(),
      name: isMoney ? 'Monthly Money Budget' : 'New Budget',
      type,
      periodType: isMoney ? 'monthly' : 'weekly',
      periodStartDay: 0,
      createdAt: ts,
      updatedAt: ts,
    };
    await db.putBudget(budget);

    if (isMoney) {
      for (let i = 0; i < DEFAULT_MONEY_CATEGORIES.length; i++) {
        const cat = DEFAULT_MONEY_CATEGORIES[i];
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
    }

    syncAfterMutation();
    setShowTypePicker(false);
    navigate('/budget/' + budget.id);
  }

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
        <button class="budget-card add-card" onClick=${() => setShowTypePicker(true)}>
          <div class="card-icon">+</div>
          <div class="card-name">New Budget</div>
        </button>
      </div>

      ${showTypePicker && html`
        <div class="type-picker-overlay" onClick=${(e) => { if (e.target === e.currentTarget) setShowTypePicker(false); }}>
          <div class="type-picker">
            <h3>Choose budget type</h3>
            <div class="type-picker-options">
              <button class="type-picker-btn" onClick=${() => createBudget('time')}>
                <div class="type-picker-icon">⏱</div>
                <div class="type-picker-label">Time</div>
                <div class="type-picker-desc">Track hours per week</div>
              </button>
              <button class="type-picker-btn" onClick=${() => createBudget('money')}>
                <div class="type-picker-icon">$</div>
                <div class="type-picker-label">Money</div>
                <div class="type-picker-desc">Track spending per month</div>
              </button>
            </div>
          </div>
        </div>
      `}
    </div>
  `;
}
