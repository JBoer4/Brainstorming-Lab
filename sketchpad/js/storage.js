// Local document library backed by IndexedDB. Everything stays on the device;
// nothing is ever sent anywhere.

const DB_NAME = 'sketchpad';
const DB_VERSION = 1;
const STORE_DOCS = 'documents';
const STORE_META = 'meta';

let dbPromise = null;

function openDB() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_DOCS)) {
        db.createObjectStore(STORE_DOCS, { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains(STORE_META)) {
        db.createObjectStore(STORE_META, { keyPath: 'key' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function tx(store, mode) {
  return openDB().then((db) => db.transaction(store, mode).objectStore(store));
}

function reqToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function listDocs() {
  const store = await tx(STORE_DOCS, 'readonly');
  const docs = await reqToPromise(store.getAll());
  return docs.sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function getDoc(id) {
  const store = await tx(STORE_DOCS, 'readonly');
  return reqToPromise(store.get(id));
}

export async function saveDoc(doc) {
  doc.updatedAt = Date.now();
  const store = await tx(STORE_DOCS, 'readwrite');
  await reqToPromise(store.put(doc));
  return doc;
}

export async function deleteDoc(id) {
  const store = await tx(STORE_DOCS, 'readwrite');
  await reqToPromise(store.delete(id));
}

export async function getMeta(key) {
  const store = await tx(STORE_META, 'readonly');
  const row = await reqToPromise(store.get(key));
  return row ? row.value : undefined;
}

export async function setMeta(key, value) {
  const store = await tx(STORE_META, 'readwrite');
  await reqToPromise(store.put({ key, value }));
}

export function newId() {
  return 'd-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}
