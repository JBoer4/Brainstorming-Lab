import { render } from 'preact';
import { useState, useEffect } from 'preact/hooks';
import { html } from 'htm/preact';
import { useRoute, navigate } from './router.js';
import { startSyncLoop, onSyncStatus } from './sync.js';
import { db } from './db.js';
import { Dashboard } from './components/Dashboard.js';
import { BudgetHome } from './components/BudgetHome.js';
import { DailyLog } from './components/DailyLog.js';
import { Categories } from './components/Categories.js';
import { History } from './components/History.js';
import { MoneyHome } from './components/MoneyHome.js';
import { MoneyCategories } from './components/MoneyCategories.js';
import { Transactions } from './components/Transactions.js';
import { ImportOFX } from './components/ImportOFX.js';

// Wrapper that loads budget and routes to time or money component
function BudgetRouter({ budgetId, view: viewName }) {
  const [budget, setBudget] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    db.getBudget(budgetId).then(b => { setBudget(b); setLoading(false); });
  }, [budgetId]);

  if (loading) return html`<div class="loading">Loading...</div>`;
  if (!budget) return html`<div class="empty-state">Budget not found</div>`;

  const isMoney = budget.type === 'money';

  if (viewName === 'home') {
    return isMoney
      ? html`<${MoneyHome} budgetId=${budgetId} />`
      : html`<${BudgetHome} budgetId=${budgetId} />`;
  }
  if (viewName === 'categories') {
    return isMoney
      ? html`<${MoneyCategories} budgetId=${budgetId} />`
      : html`<${Categories} budgetId=${budgetId} />`;
  }
  if (viewName === 'transactions') {
    return html`<${Transactions} budgetId=${budgetId} />`;
  }
  if (viewName === 'import') {
    return html`<${ImportOFX} budgetId=${budgetId} />`;
  }
  return null;
}

function App() {
  const { match } = useRoute();
  const [syncStatus, setSyncStatus] = useState('');

  useEffect(() => {
    startSyncLoop();
    return onSyncStatus(setSyncStatus);
  }, []);

  // Route matching
  let params;
  let view;

  if ((params = match('/budget/:id/log/:date'))) {
    view = html`<${DailyLog} budgetId=${params.id} date=${params.date} />`;
  } else if ((params = match('/budget/:id/log'))) {
    view = html`<${DailyLog} budgetId=${params.id} />`;
  } else if ((params = match('/budget/:id/categories'))) {
    view = html`<${BudgetRouter} budgetId=${params.id} view="categories" />`;
  } else if ((params = match('/budget/:id/history'))) {
    view = html`<${History} budgetId=${params.id} />`;
  } else if ((params = match('/budget/:id/transactions'))) {
    view = html`<${BudgetRouter} budgetId=${params.id} view="transactions" />`;
  } else if ((params = match('/budget/:id/import'))) {
    view = html`<${BudgetRouter} budgetId=${params.id} view="import" />`;
  } else if ((params = match('/budget/:id'))) {
    view = html`<${BudgetRouter} budgetId=${params.id} view="home" />`;
  } else {
    view = html`<${Dashboard} />`;
  }

  const isHome = !match('/budget/:id') && !match('/budget/:id/log') &&
    !match('/budget/:id/log/:date') && !match('/budget/:id/categories') &&
    !match('/budget/:id/history') && !match('/budget/:id/transactions') &&
    !match('/budget/:id/import');

  // Extract budgetId for back navigation
  const budgetMatch = match('/budget/:id/log') || match('/budget/:id/log/:date') ||
    match('/budget/:id/categories') || match('/budget/:id/history') ||
    match('/budget/:id/transactions') || match('/budget/:id/import');

  return html`
    <div class="app-shell">
      <header class="app-header">
        ${!isHome && html`
          <button class="back-btn" onClick=${() => {
            if (budgetMatch) {
              navigate('/budget/' + budgetMatch.id);
            } else {
              navigate('/');
            }
          }}>←</button>
        `}
        <h1 class="app-title">Budget</h1>
        <div class="sync-indicator ${syncStatus}"
          title=${syncStatus === 'syncing' ? 'Syncing...' : syncStatus === 'synced' ? 'Synced' : syncStatus === 'offline' ? 'Offline' : ''}>
        </div>
      </header>
      <main class="app-main">
        ${view}
      </main>
    </div>
  `;
}

render(html`<${App} />`, document.getElementById('app'));
