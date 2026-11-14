import { useState } from "react";
import { Bike, MapPin, PackageCheck, RefreshCw } from "lucide-react";
import { errorMessage } from "../../api/client";
import { orderApi, statsApi } from "../../api/endpoints";
import { DashboardShell } from "../../components/Layout";
import {
  Alert, Button, EmptyState, ErrorState, PageHeader, Pagination, Skeleton, Stat, StatusBadge, useConfirm,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { ORDER_STATUS, dateTime, money } from "../../utils/format";

// Only the ASSIGNED courier may do these (backend: order_lifecycle.py).
const NEXT = {
  assigned: ["out_for_delivery", "Picked up – out for delivery"],
  out_for_delivery: ["delivered", "Mark delivered"],
};
const TABS = [
  ["", "All assigned"],
  ["assigned", "Assigned to me"],
  ["out_for_delivery", "Out for delivery"],
  ["delivered", "Delivered (history)"],
];
const LIMIT = 10;

export function DeliveryPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const stats = useAsync(() => statsApi.me(), []);
  // GET /deliveries/me only ever returns orders assigned to the signed-in courier.
  const list = useAsync(() => orderApi.myDeliveries({ status, limit: LIMIT, offset }), [status, offset]);
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [confirm, dialog] = useConfirm();

  const advance = async (o) => {
    const [next, label] = NEXT[o.status];
    if (next === "delivered" && !(await confirm({
      title: "Confirm delivery", message: `Mark order #${o.id.slice(-8)} as delivered to ${o.delivery_address}?`, confirmLabel: "Delivered",
    }))) return;
    setBusy(o.id);
    try {
      await orderApi.setStatus(o.id, next);
      setMsg({ tone: "ok", text: `${label}: #${o.id.slice(-8)}` });
      list.reload();
      stats.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: errorMessage(err) }); // e.g. 409 invalid transition, 403 not yours
      list.reload();
    } finally {
      setBusy(null);
    }
  };

  return (
    <DashboardShell>
      {dialog}
      <PageHeader title="My deliveries" actions={<Button variant="ghost" size="sm" onClick={() => { list.reload(); stats.reload(); }}><RefreshCw size={16} /> Refresh</Button>} />
      {stats.data && (
        <div className="stats">
          <Stat icon={Bike} label="Active" value={stats.data.active_deliveries} />
          <Stat icon={PackageCheck} label="Completed" value={stats.data.completed_deliveries} />
        </div>
      )}
      <Alert tone={msg?.tone}>{msg?.text}</Alert>
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={status === k} className={status === k ? "active" : ""}
            onClick={() => { setStatus(k); setOffset(0); }}>{label}</button>
        ))}
      </div>
      {list.error ? <ErrorState error={list.error} onRetry={list.reload} />
        : !list.data ? <Skeleton h={200} />
        : list.data.items.length === 0 ? <EmptyState title="No deliveries here" icon={Bike}>Restaurants assign ready orders to you.</EmptyState>
        : (
          <>
            <div className="grid">
              {list.data.items.map((o) => (
                <div className="card" key={o.id}>
                  <div className="row between wrap">
                    <strong>#{o.id.slice(-8)}</strong>
                    <StatusBadge status={o.status} map={ORDER_STATUS} />
                  </div>
                  <p className="small"><MapPin size={14} /> {o.delivery_address}</p>
                  {o.notes && <p className="muted small">Note: {o.notes}</p>}
                  <p className="small">{o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</p>
                  <p className="muted small">{dateTime(o.created_at)} · {money(o.total_amount)}</p>
                  {NEXT[o.status] && (
                    <Button size="sm" className="block" loading={busy === o.id} onClick={() => advance(o)}>{NEXT[o.status][1]}</Button>
                  )}
                </div>
              ))}
            </div>
            <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
    </DashboardShell>
  );
}
