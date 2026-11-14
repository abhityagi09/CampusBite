import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { errorMessage, fieldErrors, statusOf } from "../api/client";
import { orderApi, restaurantApi } from "../api/endpoints";
import { Alert, Button, EmptyState, PageHeader, Select, Textarea } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useCart } from "../contexts/CartContext";
import { PAYMENT_METHODS, money, newKey, toCents } from "../utils/format";

export function CartPage() {
  const cart = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [check, setCheck] = useState({ state: "idle", notes: [], closed: false });
  const [form, setForm] = useState({ delivery_address: "", notes: "", payment_method: "upi" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const keyRef = useRef({ body: null, key: null });

  /** Re-check every line against the live menu: drop unavailable items, update prices. */
  const revalidate = useCallback(async () => {
    if (!cart.restaurant) return true;
    setCheck((c) => ({ ...c, state: "checking" }));
    try {
      const r = await restaurantApi.get(cart.restaurant.id); // lists AVAILABLE items only
      const live = new Map(r.menu_items.map((m) => [m.id, m]));
      const notes = [];
      const items = [];
      for (const i of cart.items) {
        const m = live.get(i.id);
        if (!m) { notes.push(`${i.name} is no longer available and was removed.`); continue; }
        if (toCents(m.price) !== toCents(i.price)) notes.push(`${m.name} now costs ${money(m.price)} (was ${money(i.price)}).`);
        items.push({ ...i, name: m.name, price: m.price });
      }
      if (notes.length) cart.replaceItems(items);
      setCheck({ state: "ok", notes, closed: !r.is_open });
      return notes.length === 0 && r.is_open;
    } catch (err) {
      if (statusOf(err) === 404) {
        setCheck({ state: "ok", notes: [`${cart.restaurant.name} is no longer on CampusBite. Your cart was cleared.`], closed: true });
        cart.clear();
      } else setCheck({ state: "error", notes: [errorMessage(err)], closed: false });
      return false;
    }
  }, [cart]);

  // Validate once when the cart page opens (prices may have changed since items were added).
  useEffect(() => { revalidate(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [cart.restaurant?.id]);

  const placeOrder = async (e) => {
    e.preventDefault();
    if (submitting) return; // no double submits
    const errs = {};
    if (form.delivery_address.trim().length < 5) errs.delivery_address = "Enter a delivery address (at least 5 characters)";
    if (form.notes.length > 500) errs.notes = "At most 500 characters";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    setSubmitting(true);
    setError("");
    try {
      if (!(await revalidate())) {
        setError("Your cart changed. Review it and place the order again.");
        return;
      }
      const body = {
        restaurant_id: cart.restaurant.id,
        items: cart.items.map((i) => ({ menu_item_id: i.id, quantity: i.quantity })),
        delivery_address: form.delivery_address.trim(),
        payment_method: form.payment_method,
        expected_total: cart.totalStr, // compared server-side, never charged
        ...(form.notes.trim() ? { notes: form.notes.trim() } : {}),
      };
      // Same body => same Idempotency-Key, so a retry after a timeout cannot double-order.
      const sig = JSON.stringify(body);
      if (keyRef.current.body !== sig) keyRef.current = { body: sig, key: newKey() };
      const res = await orderApi.checkout(body, keyRef.current.key);
      cart.clear(); // only after the server confirmed the order
      navigate(`/orders/${res.data.id}`, { replace: true, state: { placed: true } });
    } catch (err) {
      const s = statusOf(err);
      setErrors(fieldErrors(err));
      if (s === 402) setError("Payment was declined. Nothing was charged and no order was created.");
      else if (s === 409 || s === 400) { setError(errorMessage(err)); revalidate(); }
      else setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (!cart.items.length)
    return (
      <EmptyState title="Your cart is empty" icon={ShoppingBag}>
        {check.notes.map((n) => <p key={n}>{n}</p>)}
        <Link to="/" className="btn btn-primary">Browse restaurants</Link>
      </EmptyState>
    );

  return (
    <>
      <PageHeader title="Your cart" subtitle={<>From <Link to={`/restaurants/${cart.restaurant.id}`}>{cart.restaurant.name}</Link></>} />
      {check.notes.length > 0 && <Alert tone="warn">{check.notes.map((n) => <div key={n}>{n}</div>)}</Alert>}
      {check.closed && <Alert tone="warn">This restaurant is closed right now, so orders can't be placed.</Alert>}
      <div className="two-col">
        <div className="card">
          {cart.items.map((i) => (
            <div className="cart-line" key={i.id}>
              <div>
                <strong>{i.name}</strong>
                <div className="muted small">{money(i.price)} each</div>
              </div>
              <div className="qty">
                <button className="icon-btn" aria-label={`Decrease ${i.name}`} onClick={() => cart.setQuantity(i.id, i.quantity - 1)}><Minus size={16} /></button>
                <span aria-live="polite">{i.quantity}</span>
                <button className="icon-btn" aria-label={`Increase ${i.name}`} disabled={i.quantity >= 50} onClick={() => cart.setQuantity(i.id, i.quantity + 1)}><Plus size={16} /></button>
              </div>
              <strong>{money(toCents(i.price) * i.quantity)}</strong>
              <button className="icon-btn" aria-label={`Remove ${i.name}`} onClick={() => cart.setQuantity(i.id, 0)}><Trash2 size={16} /></button>
            </div>
          ))}
          <div className="cart-total"><span>Total</span><strong>{money(cart.totalCents)}</strong></div>
          <p className="muted small">The final amount is calculated by CampusBite from current menu prices when you order.</p>
        </div>

        <form className="card" onSubmit={placeOrder} noValidate>
          <h3>Checkout</h3>
          {!user ? (
            <p>
              <Link to="/login" state={{ from: "/cart" }} className="btn btn-primary block">Log in to check out</Link>
            </p>
          ) : user.role !== "customer" ? (
            <Alert tone="warn">Only customer accounts can place orders.</Alert>
          ) : (
            <>
              <Alert>{error}</Alert>
              <Textarea label="Delivery address" name="delivery_address" value={form.delivery_address} maxLength={255}
                error={errors.delivery_address} placeholder="Hostel / block, room number"
                onChange={(e) => setForm({ ...form, delivery_address: e.target.value })} />
              <Textarea label="Notes for the restaurant (optional)" name="notes" value={form.notes} maxLength={500}
                error={errors.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              <Select label="Payment method" name="payment_method" value={form.payment_method} options={PAYMENT_METHODS}
                error={errors.payment_method} onChange={(e) => setForm({ ...form, payment_method: e.target.value })}
                hint="Simulated payment – no real money is charged." />
              <Button type="submit" className="block" loading={submitting || check.state === "checking"} disabled={check.closed}>
                Pay {money(cart.totalCents)} and place order
              </Button>
            </>
          )}
        </form>
      </div>
    </>
  );
}
