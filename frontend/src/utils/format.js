// Money arrives from the API as decimal strings ("13.25"). Work in integer cents for display
// math only; the server always recomputes the real total.
export const toCents = (v) => Math.round(Number.parseFloat(v || 0) * 100);
export const centsToStr = (c) => (c / 100).toFixed(2);
const CURRENCY = import.meta.env.VITE_CURRENCY_SYMBOL || "₹";
export const money = (v) => `${CURRENCY}${(typeof v === "number" ? v / 100 : Number.parseFloat(v || 0)).toFixed(2)}`;

export const dateTime = (v) =>
  v ? new Date(v).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

export const ROLE_HOME = { customer: "/", owner: "/owner", delivery_partner: "/delivery" };
export const ROLE_LABEL = { customer: "Customer", owner: "Restaurant owner", delivery_partner: "Delivery partner" };

export const ORDER_STATUS = {
  pending_payment: { label: "Awaiting payment", tone: "warn" },
  placed: { label: "Placed", tone: "info" },
  accepted: { label: "Accepted", tone: "info" },
  preparing: { label: "Preparing", tone: "info" },
  ready: { label: "Ready", tone: "info" },
  assigned: { label: "Courier assigned", tone: "info" },
  out_for_delivery: { label: "Out for delivery", tone: "info" },
  delivered: { label: "Delivered", tone: "ok" },
  cancelled: { label: "Cancelled", tone: "muted" },
  rejected: { label: "Rejected", tone: "bad" },
  refunded: { label: "Refunded", tone: "muted" },
};

export const PAYMENT_STATUS = {
  pending: { label: "Payment pending", tone: "warn" },
  mock_paid: { label: "Paid (simulated)", tone: "ok" },
  failed: { label: "Payment failed", tone: "bad" },
  refunded: { label: "Refunded", tone: "muted" },
};

export const REFUND_STATUS = {
  requested: { label: "Refund pending", tone: "warn" },
  approved: { label: "Refund approved", tone: "info" },
  rejected: { label: "Refund rejected", tone: "bad" },
  processed: { label: "Refund approved · refunded", tone: "ok" },
};

/** Customer-facing timeline (all real backend statuses). */
export const TIMELINE = ["placed", "accepted", "preparing", "ready", "assigned", "out_for_delivery", "delivered"];
export const ACTIVE_STATUSES = ["pending_payment", "placed", "accepted", "preparing", "ready", "assigned", "out_for_delivery"];
export const PAYMENT_METHODS = [
  { value: "upi", label: "UPI" },
  { value: "card", label: "Card" },
  { value: "wallet", label: "Wallet" },
];

export const newKey = () =>
  (crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_\-:.]/g, "");
