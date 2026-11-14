import { Link } from "react-router-dom";
import { Compass, ShieldAlert } from "lucide-react";
import { EmptyState } from "../components/ui";

export const NotFoundPage = () => (
  <EmptyState title="Page not found" icon={Compass}>
    That page doesn't exist. <Link to="/">Back to restaurants</Link>
  </EmptyState>
);

export const UnauthorizedPage = () => (
  <EmptyState title="Not allowed" icon={ShieldAlert}>
    Your account role can't open this page. <Link to="/">Go home</Link>
  </EmptyState>
);
