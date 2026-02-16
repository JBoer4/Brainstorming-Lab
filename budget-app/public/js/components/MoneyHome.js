import { useState, useEffect, useRef } from 'preact/hooks';
import { html } from 'htm/preact';
import { db } from '../db.js';
import { navigate } from '../router.js';
import { syncAfterMutation } from '../sync.js';
import { now, getMonthDates, getMonthLabel, formatCurrency } from '../utils.js';

export function MoneyHome({ budgetId }) {
  const [budget, setBudget] = useState(null);
  const [categories, setCategories] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [monthOffset, setMonthOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const nameRef = useRef(null);

  const monthDate = new Date();
  monthDate.setMonth(monthDate.getMonth() + monthOffset);
  const { start: monthStart, end: monthEnd } = getMonthDates(monthDate);
  const monthLabel = getMonthLabel(monthDate);

  async function load() {
    const b = await db.getBudget(budgetId);
    setBudget(b);

    const cats = await db.getCategories(budgetId);
    cats.sort((a, b) => a.sortOrder - b.sortOrder);
    setCategories(cats);

    const allTxns = await db.getTransactions(budgetId);
    const monthTxns = allTxns.filter(t => t.date >= monthStart && t.date <= monthEnd);
    setTransactions(monthTxns);
    setLoading(false);
  }

  useEffect(() => { setLoading(true); load(); }, [budgetId, monthOffset]);

  async function renameBudget(newName) {
    if (!budget || !newName.trim()) return;
    const updated = { ...budget, name: newName.trim(), updatedAt: now() };
    delete updated._dirty;
    await db.putBudget(updated);
    setBudget(updated);
    setEditing(false);
    syncAfterMutation();
  }

  async function deleteBudget() {
    const ts = now();
    const cats = await db.getCategories(budgetId);
    const txns = await db.getTransactions(budgetId);
    for (const t of txns) await db.deleteTransaction(t.id, ts);
    for (const c of cats) await db.deleteCategory(c.id, ts);
    await db.deleteBudget(budgetId, ts);
    syncAfterMutation();
    navigate('/');
  }

  if (loading) return html`<div class="loading">Loading...</div>`;

  // Compute spending per category (expenses only, amounts are negative)
  const catSpending = {};
  let uncategorizedSpending = 0;
  for (const cat of categories) catSpending[cat.id] = 0;
  for (const t of transactions) {
    if (t.amount >= 0) continue; // skip income
    const amt = Math.abs(t.amount);
    if (t.categoryId && catSpending[t.categoryId] !== undefined) {
      catSpending[t.categoryId] += amt;
    } else {
      uncategorizedSpending += amt;
    }
  }

  const totalSpent = Object.values(catSpending).reduce((s, v) => s + v, 0) + uncategorizedSpending;
  const totalBudgeted = categories.reduce((s, c) => s + (c.targetHours || 0), 0);
  const maxSpending = Math.max(...Object.values(catSpending), uncategorizedSpending, 1);

  const uncatCount = transactions.filter(t => !t.categoryId).length;

  return html`
    <div class="budget-home">
      <div class="budget-title-row">
        ${editing ? html`
          <input class="budget-title-input" type="text" ref=${nameRef}
            value=${budget?.name || ''}
            onKeyDown=${(e) => { if (e.key === 'Enter') renameBudget(e.target.value); if (e.key === 'Escape') setEditing(false); }}
            onBlur=${(e) => renameBudget(e.target.value)} />
        ` : html`
          <h2 class="budget-title" onClick=${() => { setEditing(true); setTimeout(() => nameRef.current?.select(), 0); }}>
            ${budget?.name || 'Budget'}
          </h2>
        `}
        <button class="budget-delete-btn" onClick=${() => setConfirmDelete(true)}>Delete</button>
      </div>

      ${confirmDelete && html`
        <div class="confirm-bar">
          <span>Delete this budget and all its data?</span>
          <button class="btn btn-danger" onClick=${deleteBudget}>Yes, delete</button>
          <button class="btn btn-secondary" onClick=${() => setConfirmDelete(false)}>Cancel</button>
        </div>
      `}

      <div class="month-nav">
        <button class="nav-arrow" onClick=${() => setMonthOffset(m => m - 1)}>‹</button>
        <span class="month-label">${monthLabel}</span>
        <button class="nav-arrow" onClick=${() => setMonthOffset(m => m + 1)}>›</button>
      </div>

      ${transactions.length === 0 && html`
        <div class="empty-state">
          <p>No transactions this month</p>
          <button class="btn" onClick=${() => navigate('/budget/' + budgetId + '/import')}>Import OFX File</button>
        </div>
      `}

      ${transactions.length > 0 && html`
        <!-- Category Spending Chart -->
        <div class="spending-chart">
          <h3>Spending by Category</h3>
          ${categories.map(cat => {
            const spent = catSpending[cat.id] || 0;
            if (spent === 0) return null;
            const pct = (spent / maxSpending) * 100;
            return html`
              <div class="spending-row" key=${cat.id}>
                <div class="spending-label">
                  <span class="spending-dot" style=${{ background: cat.color }}></span>
                  <span class="spending-name">${cat.name}</span>
                </div>
                <div class="spending-bar-wrap">
                  <div class="spending-bar" style=${{ width: `${pct}%`, background: cat.color }}></div>
                </div>
                <span class="spending-amount">${formatCurrency(spent)}</span>
              </div>
            `;
          })}
          ${uncategorizedSpending > 0 && html`
            <div class="spending-row">
              <div class="spending-label">
                <span class="spending-dot" style=${{ background: '#555' }}></span>
                <span class="spending-name">Uncategorized</span>
              </div>
              <div class="spending-bar-wrap">
                <div class="spending-bar" style=${{ width: `${(uncategorizedSpending / maxSpending) * 100}%`, background: '#555' }}></div>
              </div>
              <span class="spending-amount">${formatCurrency(uncategorizedSpending)}</span>
            </div>
          `}
        </div>

        <!-- Budget vs Actual -->
        <div class="budget-vs-actual">
          <h3>Budget vs Actual</h3>
          ${categories.map(cat => {
            const actual = catSpending[cat.id] || 0;
            const target = cat.targetHours || 0;
            const pct = target > 0 ? Math.min((actual / target) * 100, 150) : 0;
            const over = target > 0 && actual > target;
            return html`
              <div class="bva-row" key=${cat.id}>
                <div class="bva-label">
                  <span class="bva-dot" style=${{ background: cat.color }}></span>
                  <span class="bva-name">${cat.name}</span>
                </div>
                <div class="bva-bar-wrap">
                  <div class="bva-bar ${over ? 'over' : ''}" style=${{
                    width: `${Math.min(pct, 100)}%`,
                    background: cat.color,
                  }}></div>
                  ${over && html`<div class="bva-bar-over" style=${{
                    width: `${pct - 100}%`,
                    background: cat.color,
                    opacity: 0.4,
                  }}></div>`}
                </div>
                <div class="bva-nums">${formatCurrency(actual)} / ${formatCurrency(target)}</div>
              </div>
            `;
          })}
          <div class="bva-row bva-total">
            <div class="bva-label"><span class="bva-name">Total</span></div>
            <div class="bva-bar-wrap">
              <div class="bva-bar" style=${{
                width: `${totalBudgeted > 0 ? Math.min((totalSpent / totalBudgeted) * 100, 100) : 0}%`,
                background: '#64748b',
              }}></div>
            </div>
            <div class="bva-nums">${formatCurrency(totalSpent)} / ${formatCurrency(totalBudgeted)}</div>
          </div>
        </div>
      `}

      ${uncatCount > 0 && html`
        <div class="uncat-notice">
          ${uncatCount} uncategorized transaction${uncatCount !== 1 ? 's' : ''}
        </div>
      `}

      <!-- Quick actions -->
      <div class="budget-actions">
        <button class="btn" onClick=${() => navigate('/budget/' + budgetId + '/import')}>Import</button>
        <button class="btn btn-secondary" onClick=${() => navigate('/budget/' + budgetId + '/transactions')}>Transactions</button>
        <button class="btn btn-secondary" onClick=${() => navigate('/budget/' + budgetId + '/categories')}>Categories</button>
      </div>
    </div>
  `;
}
