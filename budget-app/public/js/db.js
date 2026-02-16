// IndexedDB schema, CRUD, dirty tracking
// Uses soft deletes (deleted flag) so deletions propagate via sync.

const DB_NAME = 'budget-app';
const DB_VERSION = 3;
const STORES = ['budgets', 'categories', 'entries', 'periodOverrides', 'transactions', 'meta'];

let dbInstance = null;

function openDB() {
  if (dbInstance) return Promise.resolve(dbInstance);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = req.result;
      // Clean up old v1 store
      if (e.oldVersion < 2) {
        if (db.objectStoreNames.contains('kv')) db.deleteObjectStore('kv');
      }
      for (const name of STORES) {
        if (!db.objectStoreNames.contains(name)) {
          const store = db.createObjectStore(name, { keyPath: name === 'meta' ? 'key' : 'id' });
          if (name === 'categories') store.createIndex('budgetId', 'budgetId');
          if (name === 'entries') {
            store.createIndex('budgetId', 'budgetId');
            store.createIndex('date', 'date');
            store.createIndex('categoryId', 'categoryId');
          }
          if (name === 'periodOverrides') store.createIndex('budgetId', 'budgetId');
          if (name === 'transactions') {
            store.createIndex('budgetId', 'budgetId');
            store.createIndex('date', 'date');
            store.createIndex('categoryId', 'categoryId');
          }
        }
      }
    };
    req.onsuccess = () => { dbInstance = req.result; resolve(dbInstance); };
    req.onerror = () => reject(req.error);
  });
}

async function tx(storeName, mode = 'readonly') {
  const db = await openDB();
  const t = db.transaction(storeName, mode);
  return t.objectStore(storeName);
}

function promisify(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

// --- Generic CRUD ---

// Get all non-deleted records
async function getAll(storeName) {
  const store = await tx(storeName);
  const all = await promisify(store.getAll());
  return all.filter(r => !r.deleted);
}

// Get all records including deleted (for sync/dirty tracking)
async function getAllRaw(storeName) {
  const store = await tx(storeName);
  return promisify(store.getAll());
}

async function getById(storeName, id) {
  const store = await tx(storeName);
  const r = await promisify(store.get(id));
  return (r && !r.deleted) ? r : undefined;
}

// Get non-deleted records by index
async function getAllByIndex(storeName, indexName, value) {
  const store = await tx(storeName);
  const index = store.index(indexName);
  const all = await promisify(index.getAll(value));
  return all.filter(r => !r.deleted);
}

async function put(storeName, record) {
  const store = await tx(storeName, 'readwrite');
  return promisify(store.put({ ...record, _dirty: 1 }));
}

async function putClean(storeName, record) {
  const store = await tx(storeName, 'readwrite');
  return promisify(store.put({ ...record, _dirty: 0 }));
}

// Soft delete: mark as deleted + dirty, with new updatedAt
async function softDelete(storeName, id, updatedAt) {
  const store = await tx(storeName, 'readwrite');
  const existing = await promisify(store.get(id));
  if (!existing) return;
  return promisify(store.put({ ...existing, deleted: 1, updatedAt, _dirty: 1 }));
}

// Hard remove (only used internally after sync confirms deletion)
async function hardRemove(storeName, id) {
  const store = await tx(storeName, 'readwrite');
  return promisify(store.delete(id));
}

// --- Meta (lastSyncAt, etc) ---

async function getMeta(key) {
  const store = await tx('meta');
  const row = await promisify(store.get(key));
  return row ? row.value : null;
}

async function setMeta(key, value) {
  const store = await tx('meta', 'readwrite');
  return promisify(store.put({ key, value }));
}

// --- Dirty records ---

async function getDirty(storeName) {
  const all = await getAllRaw(storeName);
  return all.filter(r => r._dirty);
}

// Strip _dirty before sending to server
function cleanRecord(r) {
  const { _dirty, ...rest } = r;
  return rest;
}

// --- Public API ---

export const db = {
  // Budgets
  getBudgets: () => getAll('budgets'),
  getBudget: (id) => getById('budgets', id),
  putBudget: (record) => put('budgets', record),
  putBudgetClean: (record) => putClean('budgets', record),
  deleteBudget: (id, ts) => softDelete('budgets', id, ts),

  // Categories
  getCategories: (budgetId) => getAllByIndex('categories', 'budgetId', budgetId),
  getCategory: (id) => getById('categories', id),
  putCategory: (record) => put('categories', record),
  putCategoryClean: (record) => putClean('categories', record),
  deleteCategory: (id, ts) => softDelete('categories', id, ts),

  // Entries
  getEntries: (budgetId) => getAllByIndex('entries', 'budgetId', budgetId),
  getEntry: (id) => getById('entries', id),
  putEntry: (record) => put('entries', record),
  putEntryClean: (record) => putClean('entries', record),
  deleteEntry: (id, ts) => softDelete('entries', id, ts),

  // Period Overrides
  getOverrides: (budgetId) => getAllByIndex('periodOverrides', 'budgetId', budgetId),
  putOverride: (record) => put('periodOverrides', record),
  putOverrideClean: (record) => putClean('periodOverrides', record),

  // Transactions
  getTransactions: (budgetId) => getAllByIndex('transactions', 'budgetId', budgetId),
  getTransaction: (id) => getById('transactions', id),
  putTransaction: (record) => put('transactions', record),
  putTransactionClean: (record) => putClean('transactions', record),
  deleteTransaction: (id, ts) => softDelete('transactions', id, ts),

  // Meta
  getMeta,
  setMeta,

  // Dirty
  getDirtyBudgets: () => getDirty('budgets'),
  getDirtyCategories: () => getDirty('categories'),
  getDirtyEntries: () => getDirty('entries'),
  getDirtyOverrides: () => getDirty('periodOverrides'),
  getDirtyTransactions: () => getDirty('transactions'),
  cleanRecord,
};
