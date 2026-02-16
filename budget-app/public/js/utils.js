// Week math and date formatting utilities

export function uuid() {
  return crypto.randomUUID();
}

export function now() {
  return Date.now();
}

// Get Sunday-based week start for a given date
export function getWeekStart(date = new Date()) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - d.getDay()); // Sunday = 0
  return d;
}

// Get array of 7 Date objects for the week containing `date`
export function getWeekDates(date = new Date()) {
  const start = getWeekStart(date);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });
}

// Format Date to YYYY-MM-DD
export function toDateStr(date) {
  const d = new Date(date);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

// Parse YYYY-MM-DD to Date (local timezone)
export function parseDate(str) {
  const [y, m, d] = str.split('-').map(Number);
  return new Date(y, m - 1, d);
}

// Short day names
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function dayName(date) {
  return DAYS[new Date(date).getDay()];
}

export function formatShort(date) {
  const d = new Date(date);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

export function formatRange(startDate, endDate) {
  const s = new Date(startDate);
  const e = new Date(endDate);
  if (s.getMonth() === e.getMonth()) {
    return `${MONTHS[s.getMonth()]} ${s.getDate()}–${e.getDate()}`;
  }
  return `${formatShort(s)} – ${formatShort(e)}`;
}

// Calculate hours from HH:MM start/end
export function calcHours(startTime, endTime) {
  if (!startTime || !endTime) return null;
  const [sh, sm] = startTime.split(':').map(Number);
  const [eh, em] = endTime.split(':').map(Number);
  let diff = (eh * 60 + em) - (sh * 60 + sm);
  if (diff < 0) diff += 24 * 60; // crosses midnight
  return Math.round(diff / 60 * 100) / 100;
}

export function today() {
  return toDateStr(new Date());
}

// --- Month utilities ---

const MONTHS_FULL = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

export function getMonthStart(date = new Date()) {
  const d = new Date(date);
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function getMonthEnd(date = new Date()) {
  const d = new Date(date);
  return new Date(d.getFullYear(), d.getMonth() + 1, 0);
}

export function getMonthLabel(date = new Date()) {
  const d = new Date(date);
  return `${MONTHS_FULL[d.getMonth()]} ${d.getFullYear()}`;
}

export function getMonthDates(date = new Date()) {
  const start = getMonthStart(date);
  const end = getMonthEnd(date);
  return { start: toDateStr(start), end: toDateStr(end) };
}

export function formatCurrency(amount) {
  const abs = Math.abs(amount);
  const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return amount < 0 ? `-$${formatted}` : `$${formatted}`;
}

export function parseOFXDate(dtposted) {
  if (!dtposted || dtposted.length < 8) return null;
  return `${dtposted.slice(0, 4)}-${dtposted.slice(4, 6)}-${dtposted.slice(6, 8)}`;
}
