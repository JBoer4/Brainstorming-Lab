const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = 3000;
const DATA_FILE = path.join(__dirname, 'server-data', 'data.json');

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Ensure data directory exists
fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });

app.get('/api/data', (req, res) => {
  try {
    const data = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
    res.json(data);
  } catch {
    res.json({ text: 'it works' });
  }
});

app.put('/api/data', (req, res) => {
  fs.writeFileSync(DATA_FILE, JSON.stringify(req.body, null, 2));
  res.json({ ok: true });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Budget app running at http://localhost:${PORT}`);
});