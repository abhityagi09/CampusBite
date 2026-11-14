import { useState } from "react";
import { Bike, PackageCheck, RefreshCw } from "lucide-react";
import { errorMessage } from "../../api/client";
import { orderApi, statsApi } from "../../api/endpoints";
import { DashboardShell } from "../../components/Layout";
import { Alert, Button, EmptyState, ErrorState, PageHeader, Pagination, Skeleton, Stat, StatusBadge } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { ORDER_STATUS, dateTime, money } from "../../utils/format";

// Courier actions per status (only the ASSIGNED courier may do these).
const NEXT = {
  ready_for_pickup: ["out_for_delivery", "Picked up"],
  out_for_delivery: ["delivered", "Mark delivered"],
};
const LIMIT = 10;

function OrderCard({ o, children }) {
  return (
    <div className="card">
      <div className="row between wrap">
        <div><strong>#{o.id.slice(-8)}</strong> <span className="muted small">{dateTime(o.created_at)}</span></div>
        <div className="row"><StatusBadge status={o.status} map={ORDER_STATUS} /><strong>{money(o.total_amount)}</strong></div>
      </div>
      <p className="small">{o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</p>
      <p className="muted small">Deliver to: {o.delivery_address}</p>
      <div className="row wrap">{children}</div>
    </div>
  );
}

export function DeliveryPage() {
  const [tab, setTab] = useState("mine");
  const [offset, setOffset] = useState(0);
  const stats = useAsync(() => statsApi.me(), []);
  const list = useAsync(
    () => (tab === "mine" ? orderApi.myDeliveries({ limit: LIMIT, offset }) : orderApi.available({ limit: LIMIT, offset })),
    [tab, offset]
  );
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);

  const act = async (id, fn, ok) => {
    setBusy(id);
    try { await fn(); setMsg({ tone: "ok", text: ok }); list.reload(); stats.reload(); }
    catch (err) { setMsg({ tone: "bad", text: errorMessage(err) }); }
    finally { setBusy(null); }
  };
  const items = tab === "mine" ? list.data?.items : list.data;

  return (
    <DashboardShell>
      <PageHeader title="Deliveries" actions={<Button variant="ghost" size="sm" onClick={() => { list.reload(); stats.reload(); }}><RefreshCw size={16} /> Refresh</Button>} />
      {stats.data && (
        <div className="stats">
          <Stat icon={Bike} label="Active" value={stats.data.active_deliveries} />
          <Stat icon={PackageCheck} label="Completed" value={stats.data.completed_deliveries} />
          <Stat label="Waiting for a courier" value={stats.data.available_orders} />
        </div>
      )}
      <Alert tone={msg?.tone}>{msg?.text}</Alert>
      <div className="tabs" role="tablist">
        {[["mine", "Assigned to me"], ["available", "Ready, unassigned"]].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""}
            onClick={() => { setTab(k); setOffset(0); }}>{label}</button>
        ))}
      </div>
      {list.error ? <ErrorState error={list.error} onRetry={list.reload} />
        : !items ? <Skeleton h={200} />
        : items.length === 0 ? <EmptyState title={tab === "mine" ? "No deliveries assigned" : "Nothing waiting for pickup"} icon={Bike} />
        : (
          <>
            {items.map((o) => (
              <OrderCard o={o} key={o.id}>
                {tab === "mine" && NEXT[o.status] && (
                  <Button size="sm" loading={busy === o.id}
                    onClick={() => act(o.id, () => orderApi.setStatus(o.id, NEXT[o.status][0]), `Order ${ORDER_STATUS[NEXT[o.status][0]].label.toLowerCase()}.`)}>
                    {NEXT[o.status][1]}</Button>
                )}
                {tab === "available" && (
                  <Button size="sm" loading={busy === o.id} onClick={() => act(o.id, () => orderApi.claim(o.id), "Order claimed. It's in your list.")}>Claim</Button>
                )}
              </OrderCard>
            ))}
            {tab === "mine"
              ? <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              : <Pagination limit={LIMIT} offset={offset} hasMore={items.length === LIMIT} onChange={setOffset} />}
          </>
        )}
    </DashboardShell>
  );
}
