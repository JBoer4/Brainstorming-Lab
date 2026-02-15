// IndexedDB schema, CRUD, dirty tracking

const DB_NAME = 'budget-app';
const DB_VERSION = 2;
const STORES = ['budgets', 'categories', 'entries', 'periodOverrides', 'meta'];

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

async function getAll(storeName) {
  const store = await tx(storeName);
  return promisify(store.getAll());
}

async function getById(storeName, id) {
  const store = await tx(storeName);
  return promisify(store.get(id));
}

async function getAllByIndex(storeName, indexName, value) {
  const store = await tx(storeName);
  const index = store.index(indexName);
  return promisify(index.getAll(value));
}

async function put(storeName, record) {
  const store = await tx(storeName, 'readwrite');
  return promisify(store.put({ ...record, _dirty: 1 }));
}

async function putClean(storeName, record) {
  const store = await tx(storeName, 'readwrite');
  return promisify(store.put({ ...record, _dirty: 0 }));
}

async function remove(storeName, id) {
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
  const all = await getAll(storeName);
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
  deleteBudget: (id) => remove('budgets', id),

  // Categories
  getCategories: (budgetId) => getAllByIndex('categories', 'budgetId', budgetId),
  getCategory: (id) => getById('categories', id),
  putCategory: (record) => put('categories', record),
  putCategoryClean: (record) => putClean('categories', record),
  deleteCategory: (id) => remove('categories', id),

  // Entries
  getEntries: (budgetId) => getAllByIndex('entries', 'budgetId', budgetId),
  getEntry: (id) => getById('entries', id),
  putEntry: (record) => put('entries', record),
  putEntryClean: (record) => putClean('entries', record),
  deleteEntry: (id) => remove('entries', id),

  // Period Overrides
  getOverrides: (budgetId) => getAllByIndex('periodOverrides', 'budgetId', budgetId),
  putOverride: (record) => put('periodOverrides', record),
  putOverrideClean: (record) => putClean('periodOverrides', record),

  // Meta
  getMeta,
  setMeta,

  // Dirty
  getDirtyBudgets: () => getDirty('budgets'),
  getDirtyCategories: () => getDirty('categories'),
  getDirtyEntries: () => getDirty('entries'),
  getDirtyOverrides: () => getDirty('periodOverrides'),
  cleanRecord,
};
