// Every backend call the UI makes. See API_ENDPOINT_MAP.md for the contract of each route.
import { api } from "./client";

const d = (p) => p.then((r) => r.data);
const clean = (params) =>
  Object.fromEntries(Object.entries(params || {}).filter(([, v]) => v !== "" && v !== null && v !== undefined && v !== false));

export const authApi = {
  login: (email, password) => d(api.post("/auth/login/json", { email, password })),
  register: (body, staffKey) =>
    d(api.post("/auth/register", body, staffKey ? { headers: { "X-Registration-Key": staffKey } } : undefined)),
  me: () => d(api.get("/auth/me")),
};

export const restaurantApi = {
  list: (params) => d(api.get("/restaurants", { params: clean(params) })),
  get: (id) => d(api.get(`/restaurants/${id}`)),
  menu: (id, params) => d(api.get(`/restaurants/${id}/menu`, { params: clean(params) })),
  reviews: (id, params) => d(api.get(`/restaurants/${id}/reviews`, { params: clean(params) })),
  searchItems: (params) => d(api.get("/menu-items", { params: clean(params) })),
  // owner
  mine: (params) => d(api.get("/restaurants/mine", { params: clean(params) })),
  create: (body) => d(api.post("/restaurants", body)),
  update: (id, body) => d(api.patch(`/restaurants/${id}`, body)),
  addItem: (id, body) => d(api.post(`/restaurants/${id}/menu`, body)),
  updateItem: (id, itemId, body) => d(api.patch(`/restaurants/${id}/menu/${itemId}`, body)),
  setItemAvailable: (id, itemId, on) => d(api.post(`/restaurants/${id}/menu/${itemId}/${on ? "enable" : "disable"}`)),
  deleteItem: (id, itemId) => d(api.delete(`/restaurants/${id}/menu/${itemId}`)),
};

export const orderApi = {
  checkout: (body, idempotencyKey) => api.post("/orders", body, { headers: { "Idempotency-Key": idempotencyKey } }),
  mine: (params) => d(api.get("/orders/me", { params: clean(params) })),
  list: (params) => d(api.get("/orders", { params: clean(params) })), // owner / courier scoped list
  get: (id) => d(api.get(`/orders/${id}`)),
  cancel: (id) => d(api.post(`/orders/${id}/cancel`)),
  setStatus: (id, status) => d(api.patch(`/orders/${id}/status`, { status })),
  assign: (id, deliveryPartnerId) =>
    d(api.post(`/orders/${id}/assign-delivery`, { delivery_partner_id: deliveryPartnerId })),
  available: (params) => d(api.get("/orders/available", { params: clean(params) })),
  claim: (id) => d(api.post(`/orders/${id}/claim`)),
  myDeliveries: (params) => d(api.get("/deliveries/me", { params: clean(params) })),
  pay: (id, method) => d(api.post(`/payments/orders/${id}/pay`, { method })),
  ledger: (id) => d(api.get(`/payments/orders/${id}/ledger`)),
};

export const refundApi = {
  request: (orderId, reason) => d(api.post(`/orders/${orderId}/refund-requests`, { reason })),
  mine: (params) => d(api.get("/refund-requests/me", { params: clean(params) })),
  incoming: (params) => d(api.get("/refund-requests/incoming", { params: clean(params) })),
  decide: (id, decision) => d(api.post(`/refund-requests/${id}/decision`, { decision })),
};

export const reviewApi = {
  create: (body) => d(api.post("/reviews", body)),
};

export const statsApi = {
  customer: () => d(api.get("/statistics/customer")),
  owner: () => d(api.get("/statistics/owner")),
  me: () => d(api.get("/statistics/me")),
};

export const aiApi = {
  ask: (question) => d(api.post("/ai/insights", question ? { question } : {}, { timeout: 60000 })),
  summary: () => d(api.get("/ai/summary", { timeout: 60000 })),
};

export const reminderApi = {
  list: (params) => d(api.get("/owner/reminders", { params: clean(params) })),
  unreadCount: () => d(api.get("/owner/reminders/unread-count")),
  markRead: (id) => d(api.patch(`/owner/reminders/${id}/read`)),
};

export const userApi = {
  deliveryPartners: () => d(api.get("/users/delivery-partners")),
};
