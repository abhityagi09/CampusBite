import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { Skeleton } from "../components/ui";

/** Signed in, and (optionally) one of `roles`. Guests go to /login and come back after. */
export function RequireRole({ roles }) {
  const { user, booting } = useAuth();
  const location = useLocation();
  if (booting) return <Skeleton h={200} />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/unauthorized" replace />;
  return <Outlet />;
}
