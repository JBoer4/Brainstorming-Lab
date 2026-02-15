import { render } from 'preact';
import { useState, useEffect } from 'preact/hooks';
import { html } from 'htm/preact';
import { useRoute, navigate } from './router.js';
import { startSyncLoop, onSyncStatus } from './sync.js';
import { Dashboard } from './components/Dashboard.js';
import { BudgetHome } from './components/BudgetHome.js';
import { DailyLog } from './components/DailyLog.js';
import { Categories } from './components/Categories.js';
import { History } from './components/History.js';

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
    view = html`<${Categories} budgetId=${params.id} />`;
  } else if ((params = match('/budget/:id/history'))) {
    view = html`<${History} budgetId=${params.id} />`;
  } else if ((params = match('/budget/:id'))) {
    view = html`<${BudgetHome} budgetId=${params.id} />`;
  } else {
    view = html`<${Dashboard} />`;
  }

  const isHome = !match('/budget/:id') && !match('/budget/:id/log') &&
    !match('/budget/:id/log/:date') && !match('/budget/:id/categories') &&
    !match('/budget/:id/history');

  // Extract budgetId for back navigation
  const budgetMatch = match('/budget/:id/log') || match('/budget/:id/log/:date') ||
    match('/budget/:id/categories') || match('/budget/:id/history');

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
