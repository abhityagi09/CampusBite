import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { centsToStr, toCents } from "../utils/format";

const CART_KEY = "campusbite.cart";
const EMPTY = { restaurant: null, items: [] }; // items: [{id, name, price, quantity}]
const CartContext = createContext(null);

function load() {
  try {
    const c = JSON.parse(localStorage.getItem(CART_KEY));
    return c && Array.isArray(c.items) ? c : EMPTY;
  } catch {
    return EMPTY;
  }
}

export function CartProvider({ children }) {
  const [cart, setCart] = useState(load);

  useEffect(() => {
    try {
      localStorage.setItem(CART_KEY, JSON.stringify(cart));
    } catch {
      /* storage unavailable: cart still works for this tab */
    }
  }, [cart]);

  /** Returns "added" | "unavailable" | "conflict" (different restaurant: ask, then replace=true). */
  const addItem = useCallback((restaurant, item, { replace = false } = {}) => {
    if (!item.is_available) return "unavailable";
    if (cart.restaurant && cart.restaurant.id !== restaurant.id && cart.items.length && !replace) {
      return "conflict";
    }
    setCart((c) => {
      const base = c.restaurant?.id === restaurant.id ? c : { restaurant, items: [] };
      const existing = base.items.find((i) => i.id === item.id);
      const items = existing
        ? base.items.map((i) => (i.id === item.id ? { ...i, quantity: Math.min(50, i.quantity + 1) } : i))
        : [...base.items, { id: item.id, name: item.name, price: item.price, quantity: 1 }];
      return { restaurant: { id: restaurant.id, name: restaurant.name }, items };
    });
    return "added";
  }, [cart]);

  const setQuantity = useCallback((id, quantity) => {
    setCart((c) => {
      const items = quantity <= 0
        ? c.items.filter((i) => i.id !== id)
        : c.items.map((i) => (i.id === id ? { ...i, quantity: Math.min(50, quantity) } : i));
      return items.length ? { ...c, items } : EMPTY;
    });
  }, []);

  const replaceItems = useCallback((items) => setCart((c) => (items.length ? { ...c, items } : EMPTY)), []);
  const clear = useCallback(() => setCart(EMPTY), []);

  const value = useMemo(() => {
    const totalCents = cart.items.reduce((s, i) => s + toCents(i.price) * i.quantity, 0);
    return {
      ...cart,
      count: cart.items.reduce((s, i) => s + i.quantity, 0),
      totalCents,
      totalStr: centsToStr(totalCents),
      addItem,
      setQuantity,
      replaceItems,
      clear,
    };
  }, [cart, addItem, setQuantity, replaceItems, clear]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export const useCart = () => useContext(CartContext);
