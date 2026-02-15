// Thin fetch wrapper for server API

const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

export const api = {
  // Budgets
  getBudgets: () => request('/budgets'),
  createBudget: (data) => request('/budgets', { method: 'POST', body: data }),
  getBudget: (id) => request(`/budgets/${id}`),
  updateBudget: (id, data) => request(`/budgets/${id}`, { method: 'PUT', body: data }),
  deleteBudget: (id) => request(`/budgets/${id}`, { method: 'DELETE' }),

  // Categories
  getCategories: (budgetId) => request(`/budgets/${budgetId}/categories`),
  createCategory: (budgetId, data) => request(`/budgets/${budgetId}/categories`, { method: 'POST', body: data }),
  updateCategory: (id, data) => request(`/categories/${id}`, { method: 'PUT', body: data }),
  deleteCategory: (id) => request(`/categories/${id}`, { method: 'DELETE' }),

  // Entries
  getEntries: (budgetId, from, to) => {
    let path = `/budgets/${budgetId}/entries`;
    const params = new URLSearchParams();
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    const qs = params.toString();
    if (qs) path += `?${qs}`;
    return request(path);
  },
  createEntry: (budgetId, data) => request(`/budgets/${budgetId}/entries`, { method: 'POST', body: data }),
  updateEntry: (id, data) => request(`/entries/${id}`, { method: 'PUT', body: data }),
  deleteEntry: (id) => request(`/entries/${id}`, { method: 'DELETE' }),

  // Sync
  sync: (payload) => request('/sync', { method: 'POST', body: payload }),
};
