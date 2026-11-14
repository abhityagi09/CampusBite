import { useEffect } from "react";
import { AlertTriangle, ChevronLeft, ChevronRight, Inbox, Loader2, RotateCw, X } from "lucide-react";
import { errorMessage } from "../api/client";

export function Button({ variant = "primary", size, loading, children, className = "", ...props }) {
  return (
    <button
      className={`btn btn-${variant} ${size ? `btn-${size}` : ""} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="spin" size={16} />}
      {children}
    </button>
  );
}

function Field({ label, error, hint, children, id }) {
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      {label && <label htmlFor={id}>{label}</label>}
      {children}
      {error ? <small className="field-error">{error}</small> : hint && <small className="hint">{hint}</small>}
    </div>
  );
}

export const Input = ({ label, error, hint, id, ...props }) => (
  <Field label={label} error={error} hint={hint} id={id || props.name}>
    <input id={id || props.name} aria-invalid={Boolean(error)} {...props} />
  </Field>
);

export const Textarea = ({ label, error, hint, id, ...props }) => (
  <Field label={label} error={error} hint={hint} id={id || props.name}>
    <textarea id={id || props.name} rows={3} aria-invalid={Boolean(error)} {...props} />
  </Field>
);

export const Select = ({ label, error, hint, id, options, ...props }) => (
  <Field label={label} error={error} hint={hint} id={id || props.name}>
    <select id={id || props.name} {...props}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  </Field>
);

export function Modal({ open, title, onClose, children, footer }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

/** status: a key from one of the maps in utils/format.js, passed as `map`. */
export function StatusBadge({ status, map }) {
  const s = map?.[status] || { label: status, tone: "muted" };
  return <span className={`badge badge-${s.tone}`}>{s.label}</span>;
}

export const Skeleton = ({ h = 16, w = "100%", style }) => (
  <span className="skeleton" style={{ height: h, width: w, ...style }} />
);

export const CardSkeletons = ({ n = 6 }) => (
  <div className="grid">
    {Array.from({ length: n }, (_, i) => (
      <div className="card" key={i}>
        <Skeleton h={120} />
        <Skeleton h={18} w="60%" style={{ marginTop: 12 }} />
        <Skeleton h={14} w="40%" style={{ marginTop: 8 }} />
      </div>
    ))}
  </div>
);

export const EmptyState = ({ title, children, icon: Icon = Inbox }) => (
  <div className="state">
    <Icon size={36} />
    <h3>{title}</h3>
    {children && <div className="muted">{children}</div>}
  </div>
);

export const ErrorState = ({ error, onRetry }) => (
  <div className="state state-error" role="alert">
    <AlertTriangle size={36} />
    <h3>Something went wrong</h3>
    <p className="muted">{errorMessage(error)}</p>
    {onRetry && (
      <Button variant="ghost" onClick={onRetry}><RotateCw size={16} /> Try again</Button>
    )}
  </div>
);

export const Alert = ({ tone = "bad", children }) =>
  children ? <div className={`alert alert-${tone}`} role="status">{children}</div> : null;

/** For Page responses: { total, limit, offset }. For plain lists pass hasMore instead of total. */
export function Pagination({ total, limit, offset, hasMore, onChange }) {
  const pages = total != null ? Math.max(1, Math.ceil(total / limit)) : null;
  const page = Math.floor(offset / limit) + 1;
  const next = total != null ? offset + limit < total : hasMore;
  if (offset === 0 && !next) return null;
  return (
    <nav className="pagination" aria-label="Pagination">
      <Button variant="ghost" size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        <ChevronLeft size={16} /> Prev
      </Button>
      <span className="muted">Page {page}{pages ? ` of ${pages}` : ""}</span>
      <Button variant="ghost" size="sm" disabled={!next} onClick={() => onChange(offset + limit)}>
        Next <ChevronRight size={16} />
      </Button>
    </nav>
  );
}

export const PageHeader = ({ title, subtitle, actions }) => (
  <div className="page-header">
    <div>
      <h1>{title}</h1>
      {subtitle && <p className="muted">{subtitle}</p>}
    </div>
    {actions && <div className="row">{actions}</div>}
  </div>
);

export const Stat = ({ label, value, icon: Icon }) => (
  <div className="card stat">
    {Icon && <Icon size={20} className="accent" />}
    <span className="muted">{label}</span>
    <strong>{value}</strong>
  </div>
);
