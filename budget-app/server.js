const express = require('express');
const https = require('https');
const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');

const app = express();
const PORT = 3000;
const DB_DIR = path.join(__dirname, 'server-data');
const DB_PATH = path.join(DB_DIR, 'budget.db');

app.use(express.json({ limit: '5mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// --- Database setup ---

fs.mkdirSync(DB_DIR, { recursive: true });
const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS budgets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'time',
    periodType TEXT NOT NULL DEFAULT 'weekly',
    periodStartDay INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    createdAt INTEGER NOT NULL,
    updatedAt INTEGER NOT NULL
  );

  CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    budgetId TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#888888',
    targetHours REAL NOT NULL DEFAULT 0,
    sortOrder INTEGER NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    createdAt INTEGER NOT NULL,
    updatedAt INTEGER NOT NULL,
    FOREIGN KEY (budgetId) REFERENCES budgets(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    budgetId TEXT NOT NULL,
    categoryId TEXT NOT NULL,
    date TEXT NOT NULL,
    hours REAL NOT NULL DEFAULT 0,
    startTime TEXT,
    endTime TEXT,
    note TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    createdAt INTEGER NOT NULL,
    updatedAt INTEGER NOT NULL,
    FOREIGN KEY (budgetId) REFERENCES budgets(id) ON DELETE CASCADE,
    FOREIGN KEY (categoryId) REFERENCES categories(id) ON DELETE CASCADE
  );

  CREATE TABLE IF NOT EXISTS period_overrides (
    id TEXT PRIMARY KEY,
    budgetId TEXT NOT NULL,
    categoryId TEXT NOT NULL,
    periodStart TEXT NOT NULL,
    targetHours REAL NOT NULL DEFAULT 0,
    deleted INTEGER NOT NULL DEFAULT 0,
    createdAt INTEGER NOT NULL,
    updatedAt INTEGER NOT NULL,
    FOREIGN KEY (budgetId) REFERENCES budgets(id) ON DELETE CASCADE,
    FOREIGN KEY (categoryId) REFERENCES categories(id) ON DELETE CASCADE
  );

  CREATE INDEX IF NOT EXISTS idx_categories_budget ON categories(budgetId);
  CREATE INDEX IF NOT EXISTS idx_entries_budget ON entries(budgetId);
  CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(date);
  CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(categoryId);
  CREATE INDEX IF NOT EXISTS idx_period_overrides_budget ON period_overrides(budgetId);
`);

// Migrate: add deleted column to existing tables if missing
const tables = ['budgets', 'categories', 'entries', 'period_overrides'];
for (const table of tables) {
  const cols = db.prepare(`PRAGMA table_info(${table})`).all();
  if (!cols.find(c => c.name === 'deleted')) {
    db.exec(`ALTER TABLE ${table} ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0`);
  }
}

// --- Helper: upsert by id (updatedAt wins) ---

function upsertRow(table, row, columns) {
  const setClauses = columns.filter(c => c !== 'id').map(c => `${c} = excluded.${c}`).join(', ');
  const placeholders = columns.map(() => '?').join(', ');
  const stmt = db.prepare(`
    INSERT INTO ${table} (${columns.join(', ')})
    VALUES (${placeholders})
    ON CONFLICT(id) DO UPDATE SET ${setClauses}
    WHERE excluded.updatedAt > ${table}.updatedAt
  `);
  stmt.run(...columns.map(c => row[c] ?? null));
}

// --- Budgets ---

const BUDGET_COLS = ['id', 'name', 'type', 'periodType', 'periodStartDay', 'deleted', 'createdAt', 'updatedAt'];

app.get('/api/budgets', (req, res) => {
  res.json(db.prepare('SELECT * FROM budgets WHERE deleted = 0 ORDER BY createdAt').all());
});

app.post('/api/budgets', (req, res) => {
  const row = { deleted: 0, ...req.body };
  upsertRow('budgets', row, BUDGET_COLS);
  res.json(db.prepare('SELECT * FROM budgets WHERE id = ?').get(row.id));
});

app.get('/api/budgets/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM budgets WHERE id = ? AND deleted = 0').get(req.params.id);
  if (!row) return res.status(404).json({ error: 'Not found' });
  res.json(row);
});

app.put('/api/budgets/:id', (req, res) => {
  const row = { deleted: 0, ...req.body, id: req.params.id };
  upsertRow('budgets', row, BUDGET_COLS);
  res.json(db.prepare('SELECT * FROM budgets WHERE id = ?').get(req.params.id));
});

app.delete('/api/budgets/:id', (req, res) => {
  const now = Date.now();
  // Soft-delete budget and all its children
  db.prepare('UPDATE budgets SET deleted = 1, updatedAt = ? WHERE id = ?').run(now, req.params.id);
  db.prepare('UPDATE categories SET deleted = 1, updatedAt = ? WHERE budgetId = ?').run(now, req.params.id);
  db.prepare('UPDATE entries SET deleted = 1, updatedAt = ? WHERE budgetId = ?').run(now, req.params.id);
  db.prepare('UPDATE period_overrides SET deleted = 1, updatedAt = ? WHERE budgetId = ?').run(now, req.params.id);
  res.json({ ok: true });
});

// --- Categories ---

const CATEGORY_COLS = ['id', 'budgetId', 'name', 'color', 'targetHours', 'sortOrder', 'deleted', 'createdAt', 'updatedAt'];

app.get('/api/budgets/:id/categories', (req, res) => {
  res.json(db.prepare('SELECT * FROM categories WHERE budgetId = ? AND deleted = 0 ORDER BY sortOrder').all(req.params.id));
});

app.post('/api/budgets/:id/categories', (req, res) => {
  const row = { deleted: 0, ...req.body, budgetId: req.params.id };
  upsertRow('categories', row, CATEGORY_COLS);
  res.json(db.prepare('SELECT * FROM categories WHERE id = ?').get(row.id));
});

app.put('/api/categories/:id', (req, res) => {
  const row = { deleted: 0, ...req.body, id: req.params.id };
  upsertRow('categories', row, CATEGORY_COLS);
  res.json(db.prepare('SELECT * FROM categories WHERE id = ?').get(req.params.id));
});

app.delete('/api/categories/:id', (req, res) => {
  const now = Date.now();
  db.prepare('UPDATE categories SET deleted = 1, updatedAt = ? WHERE id = ?').run(now, req.params.id);
  res.json({ ok: true });
});

// --- Entries ---

const ENTRY_COLS = ['id', 'budgetId', 'categoryId', 'date', 'hours', 'startTime', 'endTime', 'note', 'deleted', 'createdAt', 'updatedAt'];

app.get('/api/budgets/:id/entries', (req, res) => {
  const { from, to } = req.query;
  let sql = 'SELECT * FROM entries WHERE budgetId = ? AND deleted = 0';
  const params = [req.params.id];
  if (from) { sql += ' AND date >= ?'; params.push(from); }
  if (to) { sql += ' AND date <= ?'; params.push(to); }
  sql += ' ORDER BY date, createdAt';
  res.json(db.prepare(sql).all(...params));
});

app.post('/api/budgets/:id/entries', (req, res) => {
  const row = { deleted: 0, ...req.body, budgetId: req.params.id };
  upsertRow('entries', row, ENTRY_COLS);
  res.json(db.prepare('SELECT * FROM entries WHERE id = ?').get(row.id));
});

app.put('/api/entries/:id', (req, res) => {
  const row = { deleted: 0, ...req.body, id: req.params.id };
  upsertRow('entries', row, ENTRY_COLS);
  res.json(db.prepare('SELECT * FROM entries WHERE id = ?').get(req.params.id));
});

app.delete('/api/entries/:id', (req, res) => {
  const now = Date.now();
  db.prepare('UPDATE entries SET deleted = 1, updatedAt = ? WHERE id = ?').run(now, req.params.id);
  res.json({ ok: true });
});

// --- Sync endpoint ---
// Returns ALL records changed since lastSyncAt, including soft-deleted ones.
// This is how deletions propagate to other devices.

app.post('/api/sync', (req, res) => {
  const { lastSyncAt = 0, budgets: cBudgets = [], categories: cCategories = [], entries: cEntries = [], periodOverrides: cOverrides = [] } = req.body;
  const now = Date.now();

  const syncTransaction = db.transaction(() => {
    // Upsert client records (including soft-deleted ones)
    for (const r of cBudgets) upsertRow('budgets', { deleted: 0, ...r }, BUDGET_COLS);
    for (const r of cCategories) upsertRow('categories', { deleted: 0, ...r }, CATEGORY_COLS);
    for (const r of cEntries) upsertRow('entries', { deleted: 0, ...r }, ENTRY_COLS);
    for (const r of cOverrides) upsertRow('period_overrides', { deleted: 0, ...r }, OVERRIDE_COLS);

    // Return ALL server records changed since lastSyncAt (including deleted)
    const sBudgets = db.prepare('SELECT * FROM budgets WHERE updatedAt > ?').all(lastSyncAt);
    const sCategories = db.prepare('SELECT * FROM categories WHERE updatedAt > ?').all(lastSyncAt);
    const sEntries = db.prepare('SELECT * FROM entries WHERE updatedAt > ?').all(lastSyncAt);
    const sOverrides = db.prepare('SELECT * FROM period_overrides WHERE updatedAt > ?').all(lastSyncAt);

    return { budgets: sBudgets, categories: sCategories, entries: sEntries, periodOverrides: sOverrides, syncedAt: now };
  });

  res.json(syncTransaction());
});

// --- Period Overrides ---

const OVERRIDE_COLS = ['id', 'budgetId', 'categoryId', 'periodStart', 'targetHours', 'deleted', 'createdAt', 'updatedAt'];

// --- SPA fallback ---

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// --- Start server ---

const server = https.createServer({
  cert: fs.readFileSync(path.join(__dirname, 'cert.pem')),
  key: fs.readFileSync(path.join(__dirname, 'key.pem'))
}, app);

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Budget app running at https://localhost:${PORT}`);
});
