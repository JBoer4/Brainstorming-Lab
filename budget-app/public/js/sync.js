// Sync engine: push dirty records, pull changes

import { db } from './db.js';
import { api } from './api.js';

let syncing = false;
let syncListeners = [];

export function onSyncStatus(fn) {
  syncListeners.push(fn);
  return () => { syncListeners = syncListeners.filter(f => f !== fn); };
}

function notify(status) {
  syncListeners.forEach(fn => fn(status));
}

export async function sync() {
  if (syncing) return;
  syncing = true;
  notify('syncing');

  try {
    const lastSyncAt = (await db.getMeta('lastSyncAt')) || 0;

    // Gather dirty records
    const dirtyBudgets = await db.getDirtyBudgets();
    const dirtyCategories = await db.getDirtyCategories();
    const dirtyEntries = await db.getDirtyEntries();
    const dirtyOverrides = await db.getDirtyOverrides();
    const dirtyTransactions = await db.getDirtyTransactions();

    const payload = {
      lastSyncAt,
      budgets: dirtyBudgets.map(db.cleanRecord),
      categories: dirtyCategories.map(db.cleanRecord),
      entries: dirtyEntries.map(db.cleanRecord),
      periodOverrides: dirtyOverrides.map(db.cleanRecord),
      transactions: dirtyTransactions.map(db.cleanRecord),
    };

    const result = await api.sync(payload);

    // Merge all server records into local (clean, not dirty).
    // This covers both server-side changes AND our pushed records
    // (the server returns everything changed since lastSyncAt).
    for (const r of result.budgets || []) await db.putBudgetClean(r);
    for (const r of result.categories || []) await db.putCategoryClean(r);
    for (const r of result.entries || []) await db.putEntryClean(r);
    for (const r of result.periodOverrides || []) await db.putOverrideClean(r);
    for (const r of result.transactions || []) await db.putTransactionClean(r);

    await db.setMeta('lastSyncAt', result.syncedAt);
    notify('synced');
  } catch (e) {
    console.warn('Sync failed:', e.message);
    notify('offline');
  } finally {
    syncing = false;
  }
}

// Fire-and-forget sync attempt after a mutation
export function syncAfterMutation() {
  sync().catch(() => {});
}

// Retry loop
let retryInterval = null;

export function startSyncLoop() {
  // Initial sync
  sync().catch(() => {});

  // Retry every 30s if there are dirty records
  retryInterval = setInterval(async () => {
    const dirty = [
      ...(await db.getDirtyBudgets()),
      ...(await db.getDirtyCategories()),
      ...(await db.getDirtyEntries()),
      ...(await db.getDirtyOverrides()),
      ...(await db.getDirtyTransactions()),
    ];
    if (dirty.length > 0) sync().catch(() => {});
  }, 30000);

  // Sync when coming back online
  window.addEventListener('online', () => sync().catch(() => {}));
}

export function stopSyncLoop() {
  if (retryInterval) clearInterval(retryInterval);
}
