import { Lightbulb, RefreshCw } from "lucide-react";
import { statsApi } from "../api/endpoints";
import { DashboardShell } from "../components/Layout";
import { Button, ErrorState, PageHeader, Skeleton } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { money } from "../utils/format";
import { AiInsightsPage } from "./AiInsights";

/*
 * Insights are deterministic rules applied to the caller's real /statistics data.
 * CampusBite has no AI/LLM service, so nothing here is generated or invented: every sentence
 * quotes numbers the backend returned.
 */
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

function ownerInsights(s) {
  const out = [];
  if (!s.total_orders) return ["No orders yet. Make sure at least one restaurant is open and has available dishes."];
  const delivered = s.orders_by_status.delivered || 0;
  const lost = (s.orders_by_status.cancelled || 0) + (s.orders_by_status.rejected || 0);
  out.push(`${pct(delivered, s.total_orders)}% of your ${s.total_orders} orders were delivered.`);
  if (lost) out.push(`${lost} order(s) (${pct(lost, s.total_orders)}%) were cancelled or rejected — reviewing why could recover revenue.`);
  const waiting = s.orders_by_status.placed || 0;
  if (waiting) out.push(`${waiting} order(s) are waiting for you to accept them.`);
  if (Number(s.refunded) > 0) out.push(`Refunds cost ${money(s.refunded)} of ${money(s.revenue)} delivered revenue.`);
  const rated = s.restaurants.filter((r) => r.average_rating != null);
  if (rated.length > 1) {
    const best = rated.reduce((a, b) => (b.average_rating > a.average_rating ? b : a));
    out.push(`Best rated: ${best.name} (${best.average_rating}★ from ${best.review_count} review(s)).`);
  }
  if (s.top_items[0]) out.push(`Your best seller is ${s.top_items[0].name} (${s.top_items[0].quantity} delivered).`);
  const idle = s.restaurants.filter((r) => r.total_orders === 0);
  if (idle.length) out.push(`${idle.map((r) => r.name).join(", ")} ha${idle.length > 1 ? "ve" : "s"} no orders yet.`);
  return out;
}

function customerInsights(s) {
  if (!s.total_orders) return ["You haven't ordered yet. Browse restaurants to place your first order."];
  const out = [`You've placed ${s.total_orders} order(s) and spent ${money(s.net_spent)} after refunds.`];
  if (s.top_restaurants[0]) out.push(`Your most-ordered restaurant is ${s.top_restaurants[0].name} (${s.top_restaurants[0].order_count} order(s)).`);
  const pending = s.orders_by_status.pending_payment || 0;
  if (pending) out.push(`${pending} order(s) are still awaiting payment.`);
  if (Number(s.total_refunded) > 0) out.push(`You've been refunded ${money(s.total_refunded)} in total.`);
  return out;
}

function courierInsights(s) {
  const out = [`You've completed ${s.completed_deliveries} deliver${s.completed_deliveries === 1 ? "y" : "ies"}.`];
  if (s.active_deliveries) out.push(`${s.active_deliveries} delivery(ies) are in progress.`);
  out.push(s.available_orders ? `${s.available_orders} ready order(s) are waiting for a courier.` : "No orders are waiting for a courier right now.");
  return out;
}

export function InsightsPage() {
  const { user } = useAuth();
  return user.role === "customer" ? <AiInsightsPage /> : <StatsInsights user={user} />;
}

function StatsInsights({ user }) {
  const load = { owner: statsApi.owner, delivery_partner: statsApi.me }[user.role];
  const { data, error, reload, loading } = useAsync(() => load(), [user.role]);
  const insights = data && { owner: ownerInsights, customer: customerInsights, delivery_partner: courierInsights }[user.role](data);
  const body = (
    <>
      <PageHeader title="Insights" subtitle="Plain-language takeaways computed from your live CampusBite statistics."
        actions={<Button variant="ghost" size="sm" onClick={reload} loading={loading}><RefreshCw size={16} /> Refresh</Button>} />
      {error ? <ErrorState error={error} onRetry={reload} /> : !insights ? <Skeleton h={160} /> : (
        <ul className="insights">
          {insights.map((t) => <li className="card" key={t}><Lightbulb size={18} className="accent" /> {t}</li>)}
        </ul>
      )}
    </>
  );
  return <DashboardShell>{body}</DashboardShell>;
}
