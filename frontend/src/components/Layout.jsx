import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Bike, ClipboardList, Home, LayoutDashboard, LogIn, LogOut, ReceiptText, Search, ShoppingBag,
  Sparkles, Store, UtensilsCrossed,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useCart } from "../contexts/CartContext";
import { ROLE_LABEL } from "../utils/format";

/** Navigation entries per role (guests see the customer browsing links). */
export function navFor(role) {
  if (role === "owner")
    return [
      { to: "/owner", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/owner/orders", label: "Orders", icon: ClipboardList },
      { to: "/owner/restaurants", label: "Restaurants", icon: Store },
      { to: "/insights", label: "Insights", icon: Sparkles },
    ];
  if (role === "delivery_partner")
    return [
      { to: "/delivery", label: "Deliveries", icon: Bike, end: true },
      { to: "/insights", label: "Insights", icon: Sparkles },
    ];
  const items = [
    { to: "/", label: "Restaurants", icon: Home, end: true },
    { to: "/search", label: "Dishes", icon: Search },
  ];
  if (role === "customer")
    items.push(
      { to: "/orders", label: "Orders", icon: ReceiptText },
      { to: "/insights", label: "AI Insights", icon: Sparkles }
    );
  return items;
}

function Header() {
  const { user, logout } = useAuth();
  const { count } = useCart();
  const navigate = useNavigate();
  const showCart = !user || user.role === "customer";
  return (
    <header className="header">
      <div className="container header-inner">
        <Link to="/" className="brand"><UtensilsCrossed size={22} /> CampusBite</Link>
        <nav className="header-nav">
          {navFor(user?.role).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
          ))}
        </nav>
        <div className="row">
          {showCart && (
            <Link to="/cart" className="icon-btn cart-btn" aria-label={`Cart, ${count} items`}>
              <ShoppingBag size={20} />
              {count > 0 && <span className="cart-count">{count}</span>}
            </Link>
          )}
          {user ? (
            <>
              <span className="user-chip" title={ROLE_LABEL[user.role]}>{user.name}</span>
              <button className="icon-btn" aria-label="Log out" onClick={() => { logout(); navigate("/login"); }}>
                <LogOut size={20} />
              </button>
            </>
          ) : (
            <Link to="/login" className="btn btn-primary btn-sm"><LogIn size={16} /> Log in</Link>
          )}
        </div>
      </div>
    </header>
  );
}

function MobileNavigation() {
  const { user } = useAuth();
  return (
    <nav className="mobile-nav" aria-label="Main">
      {navFor(user?.role).map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}><Icon size={20} /><span>{label}</span></NavLink>
      ))}
    </nav>
  );
}

const Footer = () => (
  <footer className="footer">
    <div className="container muted">CampusBite · campus food, delivered · payments are simulated</div>
  </footer>
);

export function Layout() {
  return (
    <div className="app">
      <Header />
      <main className="container main"><Outlet /></main>
      <Footer />
      <MobileNavigation />
    </div>
  );
}

/** Dashboard pages (owner / courier): sidebar + content. */
export function Sidebar() {
  const { user } = useAuth();
  return (
    <aside className="sidebar">
      {navFor(user?.role).map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end}><Icon size={18} /> {label}</NavLink>
      ))}
    </aside>
  );
}

export const DashboardShell = ({ children }) => (
  <div className="dashboard"><Sidebar /><div className="dashboard-main">{children}</div></div>
);
