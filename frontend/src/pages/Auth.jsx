import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { errorMessage, fieldErrors } from "../api/client";
import { authApi } from "../api/endpoints";
import { Alert, Button, Input, Select } from "../components/ui";
import { useAuth } from "../contexts/AuthContext";
import { ROLE_HOME } from "../utils/format";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function useAfterLogin() {
  const navigate = useNavigate();
  const location = useLocation();
  return (user) => {
    const from = location.state?.from;
    // Only return to the page they came from if this role may see it; else role home.
    navigate(from && user.role === "customer" ? from : ROLE_HOME[user.role] || "/", { replace: true });
  };
}

export function LoginPage() {
  const { user, login, sessionExpired, clearExpired } = useAuth();
  const goHome = useAfterLogin();
  const [form, setForm] = useState({ email: "", password: "" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={ROLE_HOME[user.role] || "/"} replace />;

  const submit = async (e) => {
    e.preventDefault();
    const errs = {};
    if (!EMAIL_RE.test(form.email)) errs.email = "Enter a valid e-mail address";
    if (!form.password) errs.password = "Enter your password";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setError("");
    try {
      clearExpired();
      goHome(await login(form.email.trim(), form.password));
    } catch (err) {
      setErrors(fieldErrors(err));
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-card card">
      <h1>Welcome back</h1>
      <p className="muted">Log in to order, track and manage.</p>
      {sessionExpired && <Alert tone="warn">Your session expired. Please log in again.</Alert>}
      <Alert>{error}</Alert>
      <form onSubmit={submit} noValidate>
        <Input label="E-mail" name="email" type="email" autoComplete="email" value={form.email}
          error={errors.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Input label="Password" name="password" type="password" autoComplete="current-password"
          value={form.password} error={errors.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <Button type="submit" loading={busy} className="block">Log in</Button>
      </form>
      <p className="muted center">New here? <Link to="/register">Create an account</Link></p>
    </div>
  );
}

const ROLES = [
  { value: "customer", label: "Customer" },
  { value: "owner", label: "Restaurant owner (staff key required)" },
  { value: "delivery_partner", label: "Delivery partner (staff key required)" },
];

export function RegisterPage() {
  const { user, login } = useAuth();
  const goHome = useAfterLogin();
  const [form, setForm] = useState({ name: "", email: "", phone: "", password: "", confirm: "", role: "customer", staffKey: "" });
  const [errors, setErrors] = useState({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={ROLE_HOME[user.role] || "/"} replace />;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const validate = () => {
    const e = {};
    if (!form.name.trim()) e.name = "Enter your name";
    if (!EMAIL_RE.test(form.email)) e.email = "Enter a valid e-mail address";
    if (form.password.length < 8) e.password = "At least 8 characters";
    else if (!/[A-Za-z]/.test(form.password) || !/\d/.test(form.password)) e.password = "Use at least one letter and one digit";
    if (form.confirm !== form.password) e.confirm = "Passwords do not match";
    if (form.phone && form.phone.length > 20) e.phone = "At most 20 characters";
    if (form.role !== "customer" && !form.staffKey) e.staffKey = "Staff accounts need the registration key";
    return e;
  };

  const submit = async (ev) => {
    ev.preventDefault();
    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setError("");
    try {
      const body = { name: form.name.trim(), email: form.email.trim(), password: form.password, role: form.role };
      if (form.phone.trim()) body.phone = form.phone.trim();
      await authApi.register(body, form.role !== "customer" ? form.staffKey : undefined);
      goHome(await login(body.email, form.password));
    } catch (err) {
      setErrors(fieldErrors(err)); // server-side validation, e.g. e-mail already registered
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-card card">
      <h1>Create your account</h1>
      <Alert>{error}</Alert>
      <form onSubmit={submit} noValidate>
        <Input label="Full name" name="name" value={form.name} error={errors.name} onChange={set("name")} autoComplete="name" />
        <Input label="E-mail" name="email" type="email" value={form.email} error={errors.email} onChange={set("email")} autoComplete="email" />
        <Input label="Phone (optional)" name="phone" value={form.phone} error={errors.phone} onChange={set("phone")} autoComplete="tel" />
        <Input label="Password" name="password" type="password" value={form.password} error={errors.password}
          onChange={set("password")} hint="8+ characters with a letter and a digit" autoComplete="new-password" />
        <Input label="Confirm password" name="confirm" type="password" value={form.confirm} error={errors.confirm} onChange={set("confirm")} autoComplete="new-password" />
        <Select label="I am a" name="role" value={form.role} onChange={set("role")} options={ROLES} error={errors.role} />
        {form.role !== "customer" && (
          <Input label="Staff registration key" name="staffKey" type="password" value={form.staffKey}
            error={errors.staffKey} onChange={set("staffKey")} hint="Provided by the CampusBite administrator" />
        )}
        <Button type="submit" loading={busy} className="block">Create account</Button>
      </form>
      <p className="muted center">Already registered? <Link to="/login">Log in</Link></p>
    </div>
  );
}
