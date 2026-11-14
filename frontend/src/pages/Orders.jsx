import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { CheckCircle2, Circle, RefreshCw, ReceiptText } from "lucide-react";
import { errorMessage, statusOf } from "../api/client";
import { orderApi, refundApi, reviewApi } from "../api/endpoints";
import {
  Alert, Button, EmptyState, ErrorState, Input, Modal, PageHeader, Pagination, Select, Skeleton,
  StatusBadge, Textarea,
} from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import {
  ACTIVE_STATUSES, ORDER_STATUS, PAYMENT_METHODS, PAYMENT_STATUS, REFUND_STATUS, TIMELINE, dateTime, money,
} from "../utils/format";

const LIMIT = 10;
const STATUS_OPTIONS = [{ value: "", label: "All statuses" },
  ...Object.entries(ORDER_STATUS).map(([value, s]) => ({ value, label: s.label }))];

export function OrdersPage() {
  const [f, setF] = useState({ status: "", created_from: "", created_to: "" });
  const [offset, setOffset] = useState(0);
  const { data, loading, error, reload } = useAsync(() => orderApi.mine({ ...f, limit: LIMIT, offset }), [f, offset]);
  const set = (k) => (e) => { setF({ ...f, [k]: e.target.value }); setOffset(0); };

  return (
    <>
      <PageHeader title="Your orders" actions={<>
        <Link to="/refunds" className="btn btn-ghost btn-sm">Refund requests</Link>
        <Button variant="ghost" size="sm" onClick={reload} loading={loading}><RefreshCw size={16} /> Refresh</Button>
      </>} />
      <div className="filters">
        <Select name="status" value={f.status} onChange={set("status")} options={STATUS_OPTIONS} aria-label="Status" />
        <Input name="created_from" type="date" label="From" value={f.created_from} onChange={set("created_from")} />
        <Input name="created_to" type="date" label="To" value={f.created_to} onChange={set("created_to")} />
      </div>
      {error ? <ErrorState error={error} onRetry={reload} />
        : !data ? <Skeleton h={200} />
        : data.items.length === 0 ? (
          <EmptyState title="No orders yet" icon={ReceiptText}>
            {f.status || f.created_from || f.created_to ? "Nothing matches these filters." : <Link to="/">Find something tasty</Link>}
          </EmptyState>
        ) : (
          <>
            <div className={`list ${loading ? "dim" : ""}`}>
              {data.items.map((o) => (
                <Link key={o.id} to={`/orders/${o.id}`} className="card order-row">
                  <div>
                    <strong>{o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</strong>
                    <div className="muted small">{dateTime(o.created_at)} · #{o.id.slice(-8)}</div>
                  </div>
                  <div className="row">
                    <StatusBadge status={o.status} map={ORDER_STATUS} />
                    <strong>{money(o.total_amount)}</strong>
                  </div>
                </Link>
              ))}
            </div>
            <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
    </>
  );
}

function Timeline({ order }) {
  if (["cancelled", "rejected"].includes(order.status) || order.status === "pending_payment") return null;
  const stamps = order.status_timestamps || {};
  const reached = TIMELINE.indexOf(order.status);
  const assigned = Boolean(order.delivery_partner_id);
  const label = { assigned: "Courier assigned", ...Object.fromEntries(Object.entries(ORDER_STATUS).map(([k, v]) => [k, v.label])) };
  return (
    <ol className="timeline">
      {TIMELINE.map((s, i) => {
        const done = s === "assigned" ? assigned : i <= reached;
        return (
          <li key={s} className={done ? "done" : ""}>
            {done ? <CheckCircle2 size={18} /> : <Circle size={18} />}
            <span>{label[s]}</span>
            {stamps[s] && <small className="muted">{dateTime(stamps[s])}</small>}
          </li>
        );
      })}
    </ol>
  );
}

export function OrderDetailPage() {
  const { id } = useParams();
  const location = useLocation();
  const order = useAsync(() => orderApi.get(id), [id]);
  const refunds = useAsync(() => refundApi.mine({ limit: 100 }), [id]);
  const [modal, setModal] = useState(null); // "cancel" | "review" | "refund" | "pay"
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ tone: "ok", text: location.state?.placed ? "Order placed and paid. 🎉" : "" });
  const [review, setReview] = useState({ rating: "5", comment: "" });
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState("upi");
  const o = order.data;

  // Live tracking: poll the backend while the order is still moving.
  useEffect(() => {
    if (!o || !ACTIVE_STATUSES.includes(o.status)) return;
    const t = setInterval(order.reload, 20000);
    return () => clearInterval(t);
  }, [o, order.reload]);

  if (order.error)
    return statusOf(order.error) === 404
      ? <EmptyState title="Order not found"><Link to="/orders">Back to your orders</Link></EmptyState>
      : <ErrorState error={order.error} onRetry={order.reload} />;
  if (!o) return <Skeleton h={300} />;

  const myRefunds = (refunds.data?.items || []).filter((r) => r.order_id === o.id);
  const openRefund = myRefunds.find((r) => ["requested", "approved"].includes(r.status));
  const canCancel = ["pending_payment", "placed"].includes(o.status);
  const canRefund = o.status === "delivered" && o.payment?.status === "paid" && !openRefund;

  const run = async (fn, ok) => {
    setBusy(true);
    try {
      await fn();
      setMsg({ tone: "ok", text: ok });
      setModal(null);
      order.reload();
      refunds.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: errorMessage(err) });
      setModal(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title={`Order #${o.id.slice(-8)}`}
        subtitle={`Placed ${dateTime(o.created_at)}`}
        actions={<>
          <StatusBadge status={o.status} map={ORDER_STATUS} />
          {o.payment && <StatusBadge status={o.payment.status} map={PAYMENT_STATUS} />}
          <Button variant="ghost" size="sm" onClick={order.reload} loading={order.loading}><RefreshCw size={16} /> Refresh</Button>
        </>}
      />
      <Alert tone={msg.tone}>{msg.text}</Alert>
      <div className="two-col">
        <div className="card">
          <h3>Tracking</h3>
          {o.status === "pending_payment" && <p className="muted">Waiting for payment.</p>}
          {o.status === "cancelled" && <p className="muted">This order was cancelled.</p>}
          {o.status === "rejected" && <p className="muted">The restaurant could not accept this order.</p>}
          <Timeline order={o} />
          <h3>History</h3>
          <ul className="events">
            {o.events.map((e, i) => (
              <li key={i}><StatusBadge status={e.status} map={ORDER_STATUS} /> <small className="muted">{dateTime(e.created_at)}</small></li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h3>Items</h3>
          {o.items.map((i) => (
            <div className="row between" key={i.id}><span>{i.quantity}× {i.name}</span><span>{money(i.subtotal)}</span></div>
          ))}
          <div className="cart-total"><span>Total</span><strong>{money(o.total_amount)}</strong></div>
          <p className="muted small">Deliver to: {o.delivery_address}{o.notes && <><br />Notes: {o.notes}</>}</p>
          {o.payment && (
            <p className="small">
              Payment: <StatusBadge status={o.payment.status} map={PAYMENT_STATUS} /> {o.payment.method.toUpperCase()}
              {o.payment.transaction_ref && <span className="muted"> · ref {o.payment.transaction_ref}</span>}
            </p>
          )}
          {myRefunds.map((r) => (
            <p className="small" key={r.id}><StatusBadge status={r.status} map={REFUND_STATUS} /> <span className="muted">{r.reason}</span></p>
          ))}
          <div className="row wrap">
            {o.status === "pending_payment" && <Button onClick={() => setModal("pay")}>Pay now</Button>}
            {canCancel && <Button variant="danger" onClick={() => setModal("cancel")}>Cancel order</Button>}
            {o.status === "delivered" && <Button variant="ghost" onClick={() => setModal("review")}>Write a review</Button>}
            {canRefund && <Button variant="ghost" onClick={() => setModal("refund")}>Request refund</Button>}
          </div>
        </div>
      </div>

      <Modal open={modal === "cancel"} title="Cancel this order?" onClose={() => setModal(null)}
        footer={<><Button variant="ghost" onClick={() => setModal(null)}>Keep order</Button>
          <Button variant="danger" loading={busy} onClick={() => run(() => orderApi.cancel(o.id), "Order cancelled. Any payment is refunded.")}>Cancel order</Button></>}>
        {o.payment?.status === "paid" ? "You'll be refunded the full amount." : "Nothing has been charged yet."}
      </Modal>

      <Modal open={modal === "pay"} title="Pay for this order" onClose={() => setModal(null)}
        footer={<Button loading={busy} onClick={() => run(() => orderApi.pay(o.id, method).then((p) => {
          if (p.status !== "paid") throw { response: { data: { detail: p.failure_reason || "Payment failed" } } };
        }), "Payment successful.")}>Pay {money(o.total_amount)}</Button>}>
        <Select name="method" label="Method (simulated)" value={method} onChange={(e) => setMethod(e.target.value)} options={PAYMENT_METHODS} />
      </Modal>

      <Modal open={modal === "review"} title="Rate your order" onClose={() => setModal(null)}
        footer={<Button loading={busy} onClick={() => run(() => reviewApi.create({
          order_id: o.id, rating: Number(review.rating), ...(review.comment.trim() ? { comment: review.comment.trim() } : {}),
        }), "Thanks for your review!")}>Submit review</Button>}>
        <Select name="rating" label="Rating" value={review.rating} onChange={(e) => setReview({ ...review, rating: e.target.value })}
          options={[5, 4, 3, 2, 1].map((n) => ({ value: String(n), label: "★".repeat(n) }))} />
        <Textarea name="comment" label="Comment (optional)" maxLength={1000} value={review.comment}
          onChange={(e) => setReview({ ...review, comment: e.target.value })} />
      </Modal>

      <Modal open={modal === "refund"} title="Request a refund" onClose={() => setModal(null)}
        footer={<Button loading={busy} disabled={!reason.trim()} onClick={() => run(() => refundApi.request(o.id, reason.trim()), "Refund requested. The restaurant will review it.")}>Send request</Button>}>
        <Textarea name="reason" label="What went wrong?" maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Modal>
    </>
  );
}

export function RefundsPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useAsync(() => refundApi.mine({ limit: LIMIT, offset }), [offset]);
  return (
    <>
      <PageHeader title="Refund requests" />
      {error ? <ErrorState error={error} onRetry={reload} />
        : !data ? <Skeleton h={120} />
        : data.items.length === 0 ? <EmptyState title="No refund requests">You can request one from a delivered order.</EmptyState>
        : (
          <>
            {data.items.map((r) => (
              <Link key={r.id} to={`/orders/${r.order_id}`} className="card order-row">
                <div><strong>{r.reason}</strong><div className="muted small">{dateTime(r.created_at)} · order #{r.order_id.slice(-8)}</div></div>
                <StatusBadge status={r.status} map={REFUND_STATUS} />
              </Link>
            ))}
            <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
    </>
  );
}
