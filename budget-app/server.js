const express = require('express');
const https = require('https');
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
  let existing = null;
  try {
    existing = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {}

  const incoming = req.body;

  // If server has newer data, keep it and tell the client
  if (existing && existing.updatedAt && incoming.updatedAt
      && existing.updatedAt > incoming.updatedAt) {
    return res.json({ ok: true, kept: 'server', data: existing });
  }

  fs.writeFileSync(DATA_FILE, JSON.stringify(incoming, null, 2));
  res.json({ ok: true, kept: 'client' });
});

const server = https.createServer({
  cert: fs.readFileSync(path.join(__dirname, 'cert.pem')),
  key: fs.readFileSync(path.join(__dirname, 'key.pem'))
}, app);

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Budget app running at https://localhost:${PORT}`);
});