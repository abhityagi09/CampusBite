import { useState } from "react";
import { Plus } from "lucide-react";
import { Button, Modal } from "./ui";
import { useCart } from "../contexts/CartContext";
import { useAuth } from "../contexts/AuthContext";
import { money } from "../utils/format";

/** Hook: add(restaurant, item) with the "switch restaurant?" confirmation built in. */
export function useAddToCart() {
  const cart = useCart();
  const [pending, setPending] = useState(null);
  const [toast, setToast] = useState("");

  const flash = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2200);
  };
  const add = (restaurant, item) => {
    const r = cart.addItem(restaurant, item);
    if (r === "conflict") setPending({ restaurant, item });
    else if (r === "unavailable") flash(`${item.name} is currently unavailable`);
    else flash(`Added ${item.name}`);
  };

  const ui = (
    <>
      <Modal
        open={Boolean(pending)}
        title="Start a new cart?"
        onClose={() => setPending(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPending(null)}>Keep current cart</Button>
            <Button onClick={() => {
              cart.addItem(pending.restaurant, pending.item, { replace: true });
              flash(`Added ${pending.item.name}`);
              setPending(null);
            }}>Clear and add</Button>
          </>
        }
      >
        Your cart has items from <b>{cart.restaurant?.name}</b>. An order can only contain dishes from
        one restaurant. Clear it and add <b>{pending?.item.name}</b> from <b>{pending?.restaurant.name}</b>?
      </Modal>
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
  return { add, ui };
}

export function DishCard({ item, onAdd, subtitle }) {
  const { user } = useAuth();
  const canOrder = !user || user.role === "customer";
  return (
    <div className="card dish">
      <div className="dish-body">
        <div className="dish-title">
          <strong>{item.name}</strong>
          <span className="price">{money(item.price)}</span>
        </div>
        {subtitle && <div className="muted small">{subtitle}</div>}
        {item.category && <span className="chip">{item.category}</span>}
        {item.description && <p className="muted small">{item.description}</p>}
      </div>
      {canOrder && (
        <Button size="sm" disabled={!item.is_available} onClick={() => onAdd(item)}
          aria-label={`Add ${item.name} to cart`}>
          <Plus size={16} /> {item.is_available ? "Add" : "Unavailable"}
        </Button>
      )}
    </div>
  );
}
