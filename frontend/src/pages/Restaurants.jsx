import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { MapPin, Search, Star } from "lucide-react";
import { restaurantApi } from "../api/endpoints";
import { statusOf } from "../api/client";
import { DishCard, useAddToCart } from "../components/AddToCart";
import {
  CardSkeletons, EmptyState, ErrorState, Input, PageHeader, Pagination, Select, Skeleton,
} from "../components/ui";
import { useAsync, useDebounced } from "../hooks/useAsync";
import { dateTime } from "../utils/format";

const LIMIT = 12;

const Rating = ({ avg, count }) =>
  count ? (
    <span className="rating"><Star size={14} fill="currentColor" /> {avg?.toFixed(1)} <span className="muted">({count})</span></span>
  ) : (
    <span className="muted small">No reviews yet</span>
  );

export function RestaurantsPage() {
  const [q, setQ] = useState("");
  const [cuisine, setCuisine] = useState("");
  const [openOnly, setOpenOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const dq = useDebounced(q);
  const dc = useDebounced(cuisine);
  const { data, loading, error, reload } = useAsync(
    () => restaurantApi.list({ q: dq.trim(), cuisine: dc.trim(), open_only: openOnly, limit: LIMIT, offset }),
    [dq, dc, openOnly, offset]
  );
  const reset = (fn) => (e) => { fn(e.target.type === "checkbox" ? e.target.checked : e.target.value); setOffset(0); };

  return (
    <>
      <section className="hero">
        <h1>Hungry? Your campus kitchens are a tap away.</h1>
        <p>Order from restaurants around campus and track every step to your door.</p>
      </section>
      <div className="filters">
        <Input name="q" placeholder="Search restaurants, cuisines…" value={q} onChange={reset(setQ)} aria-label="Search restaurants" />
        <Input name="cuisine" placeholder="Cuisine (exact)" value={cuisine} onChange={reset(setCuisine)} aria-label="Cuisine" />
        <label className="check"><input type="checkbox" checked={openOnly} onChange={reset(setOpenOnly)} /> Open now</label>
      </div>
      {error ? <ErrorState error={error} onRetry={reload} />
        : !data ? <CardSkeletons />
        : data.items.length === 0 ? <EmptyState title="No restaurants found">Try a different search or filter.</EmptyState>
        : (
          <>
            <div className={`grid ${loading ? "dim" : ""}`}>
              {data.items.map((r) => (
                <Link key={r.id} to={`/restaurants/${r.id}`} className="card restaurant-card">
                  <div className="cover">{r.name.slice(0, 1)}</div>
                  <div className="row between">
                    <strong>{r.name}</strong>
                    <span className={`badge ${r.is_open ? "badge-ok" : "badge-muted"}`}>{r.is_open ? "Open" : "Closed"}</span>
                  </div>
                  <div className="muted small">{[r.cuisine, r.location].filter(Boolean).join(" · ") || " "}</div>
                  <Rating avg={r.average_rating} count={r.review_count} />
                </Link>
              ))}
            </div>
            <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
    </>
  );
}

const SORTS = [
  { value: "", label: "Menu order" },
  { value: "price-asc", label: "Price: low to high" },
  { value: "price-desc", label: "Price: high to low" },
  { value: "name", label: "Name A–Z" },
];
const sorters = {
  "price-asc": (a, b) => Number(a.price) - Number(b.price),
  "price-desc": (a, b) => Number(b.price) - Number(a.price),
  name: (a, b) => a.name.localeCompare(b.name),
};

export function RestaurantDetailPage() {
  const { id } = useParams();
  const restaurant = useAsync(() => restaurantApi.get(id), [id]);
  const [filters, setFilters] = useState({ q: "", category: "", min_price: "", max_price: "" });
  const [sort, setSort] = useState("");
  const [offset, setOffset] = useState(0);
  const df = useDebounced(filters);
  const menu = useAsync(() => restaurantApi.menu(id, { ...df, limit: 100, offset }), [id, df, offset]);
  const [rOffset, setROffset] = useState(0);
  const reviews = useAsync(() => restaurantApi.reviews(id, { limit: 5, offset: rOffset }), [id, rOffset]);
  const { add, ui } = useAddToCart();
  const setF = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setOffset(0); };

  if (restaurant.error)
    return statusOf(restaurant.error) === 404
      ? <EmptyState title="Restaurant not found">It may have been closed. <Link to="/">Browse restaurants</Link></EmptyState>
      : <ErrorState error={restaurant.error} onRetry={restaurant.reload} />;
  const r = restaurant.data;
  const items = menu.data ? [...menu.data.items].sort(sorters[sort] || (() => 0)) : [];

  return (
    <>
      {ui}
      {!r ? <Skeleton h={90} /> : (
        <PageHeader
          title={r.name}
          subtitle={<>{[r.cuisine, r.description].filter(Boolean).join(" · ")}{r.location && <><br /><MapPin size={14} /> {r.location}</>}</>}
          actions={<>
            <Rating avg={r.average_rating} count={r.review_count} />
            <span className={`badge ${r.is_open ? "badge-ok" : "badge-muted"}`}>{r.is_open ? "Open now" : "Closed – ordering paused"}</span>
          </>}
        />
      )}
      <div className="filters">
        <Input name="q" placeholder="Search this menu" value={filters.q} onChange={setF("q")} aria-label="Search menu" />
        <Input name="category" placeholder="Category" value={filters.category} onChange={setF("category")} aria-label="Category" />
        <Input name="min_price" type="number" min="0" step="0.01" placeholder="Min price" value={filters.min_price} onChange={setF("min_price")} aria-label="Minimum price" />
        <Input name="max_price" type="number" min="0" step="0.01" placeholder="Max price" value={filters.max_price} onChange={setF("max_price")} aria-label="Maximum price" />
        <Select name="sort" value={sort} onChange={(e) => setSort(e.target.value)} options={SORTS} aria-label="Sort" />
      </div>
      <p className="muted small">Only dishes the restaurant currently has available are listed.</p>
      {menu.error ? <ErrorState error={menu.error} onRetry={menu.reload} />
        : !menu.data ? <CardSkeletons n={4} />
        : items.length === 0 ? <EmptyState title="No dishes match">Clear the filters to see the full menu.</EmptyState>
        : (
          <>
            <div className={`dish-list ${menu.loading ? "dim" : ""}`}>
              {items.map((it) => <DishCard key={it.id} item={it} onAdd={(item) => add(r, item)} />)}
            </div>
            <Pagination total={menu.data.total} limit={100} offset={offset} onChange={setOffset} />
          </>
        )}

      <h2 className="section-title">Reviews</h2>
      {reviews.error ? <ErrorState error={reviews.error} onRetry={reviews.reload} />
        : !reviews.data ? <Skeleton h={60} />
        : reviews.data.items.length === 0 ? <p className="muted">No reviews yet.</p>
        : (
          <>
            {reviews.data.items.map((rv) => (
              <div className="card review" key={rv.id}>
                <span className="rating">{"★".repeat(rv.rating)}<span className="muted">{"★".repeat(5 - rv.rating)}</span></span>
                {rv.comment && <p>{rv.comment}</p>}
                <small className="muted">{dateTime(rv.created_at)}</small>
              </div>
            ))}
            <Pagination total={reviews.data.total} limit={5} offset={rOffset} onChange={setROffset} />
          </>
        )}
    </>
  );
}

export function DishSearchPage() {
  const [filters, setFilters] = useState({ q: "", min_price: "", max_price: "", open_only: false });
  const [offset, setOffset] = useState(0);
  const df = useDebounced(filters);
  const { data, loading, error, reload } = useAsync(
    () => restaurantApi.searchItems({ ...df, q: df.q.trim(), limit: LIMIT, offset }), [df, offset]);
  const { add, ui } = useAddToCart();
  const setF = (k) => (e) => {
    setFilters({ ...filters, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
    setOffset(0);
  };

  return (
    <>
      {ui}
      <PageHeader title="Find a dish" subtitle="Search available dishes across every open restaurant." />
      <div className="filters">
        <Input name="q" placeholder="Biryani, burger, coffee…" value={filters.q} onChange={setF("q")} aria-label="Dish name" />
        <Input name="min_price" type="number" min="0" step="0.01" placeholder="Min price" value={filters.min_price} onChange={setF("min_price")} aria-label="Minimum price" />
        <Input name="max_price" type="number" min="0" step="0.01" placeholder="Max price" value={filters.max_price} onChange={setF("max_price")} aria-label="Maximum price" />
        <label className="check"><input type="checkbox" checked={filters.open_only} onChange={setF("open_only")} /> Restaurant open now</label>
      </div>
      {error ? <ErrorState error={error} onRetry={reload} />
        : !data ? <CardSkeletons n={4} />
        : data.items.length === 0 ? <EmptyState title="No dishes found" icon={Search}>Try another name or widen the price range.</EmptyState>
        : (
          <>
            <div className={`dish-list ${loading ? "dim" : ""}`}>
              {data.items.map((it) => (
                <DishCard key={it.id} item={it}
                  subtitle={<Link to={`/restaurants/${it.restaurant_id}`}>{it.restaurant_name}{!it.restaurant_is_open && " (closed)"}</Link>}
                  onAdd={(item) => add({ id: item.restaurant_id, name: item.restaurant_name }, item)} />
              ))}
            </div>
            <Pagination total={data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
    </>
  );
}
