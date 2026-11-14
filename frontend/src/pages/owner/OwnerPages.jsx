import { useState } from "react";
import { ClipboardList, IndianRupee, RefreshCw, Star, Store } from "lucide-react";
import { errorMessage, fieldErrors } from "../../api/client";
import { orderApi, refundApi, restaurantApi, statsApi, userApi } from "../../api/endpoints";
import { DashboardShell } from "../../components/Layout";
import {
  Alert, Button, EmptyState, ErrorState, Input, Modal, PageHeader, Pagination, Select, Skeleton, Stat,
  StatusBadge, Textarea,
} from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { ORDER_STATUS, REFUND_STATUS, dateTime, money } from "../../utils/format";

// ------------------------------------------------------------------ dashboard

export function OwnerDashboardPage() {
  const { data: s, error, reload } = useAsync(() => statsApi.owner(), []);
  return (
    <DashboardShell>
      <PageHeader title="Dashboard" actions={<Button variant="ghost" size="sm" onClick={reload}><RefreshCw size={16} /> Refresh</Button>} />
      {error ? <ErrorState error={error} onRetry={reload} /> : !s ? <Skeleton h={240} /> : (
        <>
          <div className="stats">
            <Stat icon={Store} label="Restaurants" value={s.restaurant_count} />
            <Stat icon={ClipboardList} label="Orders" value={s.total_orders} />
            <Stat icon={IndianRupee} label="Net revenue" value={money(s.net_revenue)} />
            <Stat icon={Star} label="Rating" value={s.average_rating != null ? `${s.average_rating} (${s.review_count})` : "—"} />
          </div>
          <div className="card">
            <h3>Orders by status</h3>
            <div className="row wrap">
              {Object.keys(s.orders_by_status).length === 0 ? <span className="muted">No orders yet.</span> :
                Object.entries(s.orders_by_status).map(([k, v]) => <span key={k}><StatusBadge status={k} map={ORDER_STATUS} /> {v}</span>)}
            </div>
            <p className="muted small">Revenue {money(s.revenue)} (delivered orders) − refunds {money(s.refunded)}.</p>
          </div>
          <div className="card table-wrap">
            <h3>Restaurant performance</h3>
            {s.restaurants.length === 0 ? <p className="muted">Create a restaurant to get started.</p> : (
              <table>
                <thead><tr><th>Restaurant</th><th>Orders</th><th>Delivered</th><th>Cancelled / rejected</th><th>Revenue</th><th>Rating</th></tr></thead>
                <tbody>
                  {s.restaurants.map((r) => (
                    <tr key={r.restaurant_id}>
                      <td>{r.name} {!r.is_active && <span className="badge badge-muted">inactive</span>}</td>
                      <td>{r.total_orders}</td><td>{r.delivered_orders}</td><td>{r.cancelled_or_rejected}</td>
                      <td>{money(r.revenue)}</td><td>{r.average_rating != null ? `${r.average_rating} (${r.review_count})` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {s.top_items.length > 0 && (
            <div className="card"><h3>Top dishes (delivered)</h3>
              {s.top_items.map((t) => <div className="row between" key={t.name}><span>{t.name}</span><strong>{t.quantity}</strong></div>)}
            </div>
          )}
        </>
      )}
    </DashboardShell>
  );
}

// ------------------------------------------------------------------ orders

// Owner actions per status (mirrors backend/app/services/order_lifecycle.py).
const OWNER_NEXT = {
  placed: [["accepted", "Accept"], ["rejected", "Reject"]],
  accepted: [["preparing", "Start preparing"], ["rejected", "Reject"]],
  preparing: [["ready_for_pickup", "Mark ready"]],
};
const ASSIGNABLE = ["accepted", "preparing", "ready_for_pickup"];
const LIMIT = 15;

export function OwnerOrdersPage() {
  const [status, setStatus] = useState("placed");
  const [offset, setOffset] = useState(0);
  const orders = useAsync(() => orderApi.list({ status, limit: LIMIT, offset }), [status, offset]);
  const couriers = useAsync(() => userApi.deliveryPartners(), []);
  const refunds = useAsync(() => refundApi.incoming({ status: "requested", limit: 50 }), []);
  const [busyId, setBusyId] = useState(null);
  const [msg, setMsg] = useState(null);

  const act = async (id, fn, ok) => {
    setBusyId(id);
    try {
      await fn();
      setMsg({ tone: "ok", text: ok });
      orders.reload();
      refunds.reload();
    } catch (err) {
      setMsg({ tone: "bad", text: errorMessage(err) });
    } finally {
      setBusyId(null);
    }
  };
  const courierOptions = [{ value: "", label: "Assign courier…" },
    ...(couriers.data || []).map((c) => ({ value: c.id, label: c.name }))];

  return (
    <DashboardShell>
      <PageHeader title="Orders" actions={<Button variant="ghost" size="sm" onClick={() => { orders.reload(); refunds.reload(); }}><RefreshCw size={16} /> Refresh</Button>} />
      <Alert tone={msg?.tone}>{msg?.text}</Alert>

      {refunds.data?.items.length > 0 && (
        <div className="card">
          <h3>Refund requests awaiting your decision</h3>
          {refunds.data.items.map((r) => (
            <div className="order-row" key={r.id}>
              <div><strong>{r.reason}</strong><div className="muted small">Order #{r.order_id.slice(-8)} · {dateTime(r.created_at)}</div></div>
              <div className="row">
                <StatusBadge status={r.status} map={REFUND_STATUS} />
                <Button size="sm" loading={busyId === r.id} onClick={() => act(r.id, () => refundApi.decide(r.id, "approve"), "Refund approved and processed.")}>Approve</Button>
                <Button size="sm" variant="ghost" disabled={busyId === r.id} onClick={() => act(r.id, () => refundApi.decide(r.id, "reject"), "Refund rejected.")}>Reject</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="tabs" role="tablist">
        {["placed", "accepted", "preparing", "ready_for_pickup", "out_for_delivery", "delivered", "cancelled", "rejected", ""].map((s) => (
          <button key={s} role="tab" aria-selected={status === s} className={status === s ? "active" : ""}
            onClick={() => { setStatus(s); setOffset(0); }}>{s ? ORDER_STATUS[s].label : "All"}</button>
        ))}
      </div>
      {orders.error ? <ErrorState error={orders.error} onRetry={orders.reload} />
        : !orders.data ? <Skeleton h={200} />
        : orders.data.length === 0 ? <EmptyState title="No orders here" />
        : (
          <>
            {orders.data.map((o) => (
              <div className="card" key={o.id}>
                <div className="row between wrap">
                  <div><strong>#{o.id.slice(-8)}</strong> <span className="muted small">{dateTime(o.created_at)}</span></div>
                  <div className="row"><StatusBadge status={o.status} map={ORDER_STATUS} /><strong>{money(o.total_amount)}</strong></div>
                </div>
                <p className="small">{o.items.map((i) => `${i.quantity}× ${i.name}`).join(", ")}</p>
                <p className="muted small">To: {o.delivery_address}{o.notes && ` · “${o.notes}”`}</p>
                <div className="row wrap">
                  {(OWNER_NEXT[o.status] || []).map(([next, label]) => (
                    <Button key={next} size="sm" variant={next === "rejected" ? "danger" : "primary"} loading={busyId === o.id}
                      onClick={() => act(o.id, () => orderApi.setStatus(o.id, next), `Order ${ORDER_STATUS[next].label.toLowerCase()}.`)}>{label}</Button>
                  ))}
                  {ASSIGNABLE.includes(o.status) && (
                    <Select name={`courier-${o.id}`} aria-label="Assign courier" value={o.delivery_partner_id || ""}
                      options={courierOptions} disabled={busyId === o.id}
                      onChange={(e) => e.target.value && act(o.id, () => orderApi.assign(o.id, e.target.value), "Courier assigned.")} />
                  )}
                </div>
              </div>
            ))}
            <Pagination limit={LIMIT} offset={offset} hasMore={orders.data.length === LIMIT} onChange={setOffset} />
          </>
        )}
    </DashboardShell>
  );
}

// ------------------------------------------------------------------ restaurants & menus

const EMPTY_R = { name: "", cuisine: "", location: "", description: "", is_open: true, is_active: true };
const EMPTY_ITEM = { name: "", category: "", price: "", description: "", is_available: true };
const nul = (v) => (typeof v === "string" && !v.trim() ? null : v);

export function OwnerRestaurantsPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, reload } = useAsync(() => restaurantApi.mine({ limit: 10, offset }), [offset]);
  const [edit, setEdit] = useState(null); // {kind: "restaurant"|"item", restaurant, item?, form}
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const open = (kind, restaurant, item) => {
    setErrors({});
    const form = kind === "restaurant"
      ? { ...EMPTY_R, ...(restaurant ? Object.fromEntries(Object.keys(EMPTY_R).map((k) => [k, restaurant[k] ?? ""])) : {}) }
      : { ...EMPTY_ITEM, ...(item ? Object.fromEntries(Object.keys(EMPTY_ITEM).map((k) => [k, item[k] ?? ""])) : {}) };
    setEdit({ kind, restaurant, item, form });
  };
  const setF = (k) => (e) => setEdit({ ...edit, form: { ...edit.form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value } });

  const save = async () => {
    const f = edit.form;
    const errs = {};
    if (!f.name.trim()) errs.name = "Required";
    if (edit.kind === "item" && !(Number(f.price) > 0)) errs.price = "Enter a price above 0";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      if (edit.kind === "restaurant") {
        const body = { name: f.name.trim(), cuisine: nul(f.cuisine), location: nul(f.location), description: nul(f.description), is_open: f.is_open };
        if (edit.restaurant) await restaurantApi.update(edit.restaurant.id, { ...body, is_active: f.is_active });
        else await restaurantApi.create(body);
      } else {
        const body = { name: f.name.trim(), category: nul(f.category), description: nul(f.description), price: String(f.price), is_available: f.is_available };
        if (edit.item) await restaurantApi.updateItem(edit.restaurant.id, edit.item.id, body);
        else await restaurantApi.addItem(edit.restaurant.id, body);
      }
      setEdit(null);
      setMsg({ tone: "ok", text: "Saved." });
      reload();
    } catch (err) {
      setErrors(fieldErrors(err));
      setMsg({ tone: "bad", text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const quick = async (fn, ok) => {
    try { await fn(); setMsg({ tone: "ok", text: ok }); reload(); }
    catch (err) { setMsg({ tone: "bad", text: errorMessage(err) }); }
  };

  return (
    <DashboardShell>
      <PageHeader title="Restaurants & menus" actions={<Button onClick={() => open("restaurant")}>New restaurant</Button>} />
      <Alert tone={msg?.tone}>{msg?.text}</Alert>
      {error ? <ErrorState error={error} onRetry={reload} />
        : !data ? <Skeleton h={200} />
        : data.items.length === 0 ? <EmptyState title="No restaurants yet" icon={Store}>Create your first restaurant to start selling.</EmptyState>
        : data.items.map((r) => (
          <div className="card" key={r.id}>
            <div className="row between wrap">
              <div>
                <h3>{r.name}</h3>
                <span className="muted small">{[r.cuisine, r.location].filter(Boolean).join(" · ")}</span>
              </div>
              <div className="row wrap">
                <span className={`badge ${r.is_open ? "badge-ok" : "badge-muted"}`}>{r.is_open ? "Open" : "Closed"}</span>
                {!r.is_active && <span className="badge badge-bad">Hidden</span>}
                <Button size="sm" variant="ghost" onClick={() => quick(() => restaurantApi.update(r.id, { is_open: !r.is_open }), r.is_open ? "Closed for orders." : "Open for orders.")}>
                  {r.is_open ? "Close now" : "Open now"}</Button>
                <Button size="sm" variant="ghost" onClick={() => open("restaurant", r)}>Edit</Button>
                <Button size="sm" onClick={() => open("item", r)}>Add dish</Button>
              </div>
            </div>
            {r.menu_items.length === 0 ? <p className="muted">No dishes yet.</p> : (
              <div className="table-wrap"><table>
                <thead><tr><th>Dish</th><th>Category</th><th>Price</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {r.menu_items.map((m) => (
                    <tr key={m.id}>
                      <td>{m.name}</td><td>{m.category || "—"}</td><td>{money(m.price)}</td>
                      <td><span className={`badge ${m.is_available ? "badge-ok" : "badge-muted"}`}>{m.is_available ? "Available" : "Disabled"}</span></td>
                      <td className="row">
                        <Button size="sm" variant="ghost" onClick={() => open("item", r, m)}>Edit</Button>
                        <Button size="sm" variant="ghost" onClick={() => quick(() => restaurantApi.setItemAvailable(r.id, m.id, !m.is_available), m.is_available ? "Dish disabled." : "Dish enabled.")}>
                          {m.is_available ? "Disable" : "Enable"}</Button>
                        <Button size="sm" variant="danger" onClick={() => quick(() => restaurantApi.deleteItem(r.id, m.id), "Dish removed (kept as disabled if it was ever ordered).")}>Delete</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </div>
        ))}
      {data && <Pagination total={data.total} limit={10} offset={offset} onChange={setOffset} />}

      <Modal open={Boolean(edit)} onClose={() => setEdit(null)}
        title={edit?.kind === "restaurant" ? (edit.restaurant ? "Edit restaurant" : "New restaurant") : (edit?.item ? "Edit dish" : `Add dish to ${edit?.restaurant?.name}`)}
        footer={<Button loading={busy} onClick={save}>Save</Button>}>
        {edit?.kind === "restaurant" && (
          <>
            <Input label="Name" name="name" value={edit.form.name} error={errors.name} onChange={setF("name")} maxLength={120} />
            <Input label="Cuisine" name="cuisine" value={edit.form.cuisine} error={errors.cuisine} onChange={setF("cuisine")} maxLength={60} />
            <Input label="Location" name="location" value={edit.form.location} error={errors.location} onChange={setF("location")} maxLength={200} />
            <Textarea label="Description" name="description" value={edit.form.description} error={errors.description} onChange={setF("description")} maxLength={2000} />
            <label className="check"><input type="checkbox" checked={edit.form.is_open} onChange={setF("is_open")} /> Accepting orders</label>
            {edit.restaurant && <label className="check"><input type="checkbox" checked={edit.form.is_active} onChange={setF("is_active")} /> Listed on CampusBite</label>}
          </>
        )}
        {edit?.kind === "item" && (
          <>
            <Input label="Name" name="name" value={edit.form.name} error={errors.name} onChange={setF("name")} maxLength={120} />
            <Input label="Price" name="price" type="number" min="0.01" step="0.01" value={edit.form.price} error={errors.price} onChange={setF("price")} />
            <Input label="Category" name="category" value={edit.form.category} error={errors.category} onChange={setF("category")} maxLength={60} />
            <Textarea label="Description" name="description" value={edit.form.description} error={errors.description} onChange={setF("description")} maxLength={1000} />
            <label className="check"><input type="checkbox" checked={edit.form.is_available} onChange={setF("is_available")} /> Available</label>
          </>
        )}
      </Modal>
    </DashboardShell>
  );
}

