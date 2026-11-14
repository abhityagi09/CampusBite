import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AuthProvider } from "./contexts/AuthContext";
import { CartProvider } from "./contexts/CartContext";
import { RequireRole } from "./routes/guards";
import { LoginPage, RegisterPage } from "./pages/Auth";
import { CartPage } from "./pages/Cart";
import { InsightsPage } from "./pages/Insights";
import { NotFoundPage, UnauthorizedPage } from "./pages/Misc";
import { OrderDetailPage, OrdersPage, RefundsPage } from "./pages/Orders";
import { DishSearchPage, RestaurantDetailPage, RestaurantsPage } from "./pages/Restaurants";
import { OwnerDashboardPage, OwnerOrdersPage, OwnerRestaurantsPage } from "./pages/owner/OwnerPages";
import { DeliveryPage } from "./pages/delivery/DeliveryPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <CartProvider>
          <Routes>
            <Route element={<Layout />}>
              {/* public */}
              <Route index element={<RestaurantsPage />} />
              <Route path="restaurants/:id" element={<RestaurantDetailPage />} />
              <Route path="search" element={<DishSearchPage />} />
              <Route path="cart" element={<CartPage />} />
              <Route path="login" element={<LoginPage />} />
              <Route path="register" element={<RegisterPage />} />
              <Route path="unauthorized" element={<UnauthorizedPage />} />

              {/* any signed-in role */}
              <Route element={<RequireRole />}>
                <Route path="insights" element={<InsightsPage />} />
              </Route>
              <Route element={<RequireRole roles={["customer"]} />}>
                <Route path="orders" element={<OrdersPage />} />
                <Route path="orders/:id" element={<OrderDetailPage />} />
                <Route path="refunds" element={<RefundsPage />} />
              </Route>
              <Route element={<RequireRole roles={["owner"]} />}>
                <Route path="owner" element={<OwnerDashboardPage />} />
                <Route path="owner/orders" element={<OwnerOrdersPage />} />
                <Route path="owner/restaurants" element={<OwnerRestaurantsPage />} />
              </Route>
              <Route element={<RequireRole roles={["delivery_partner"]} />}>
                <Route path="delivery" element={<DeliveryPage />} />
              </Route>
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </CartProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
