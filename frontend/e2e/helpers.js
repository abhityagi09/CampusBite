// Shared helpers. Everything goes through the real UI or the real API; nothing is mocked.
export const API = process.env.E2E_API || "http://localhost:8000/api/v1";
export const PASSWORD = "Campus123"; // seed accounts (backend: python -m app.seed)
export const OWNER = "grill.owner@example.com";
export const COURIER = "dev.courier@example.com";

export async function uiLogin(page, email, password = PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
}

/** Fast login for layout checks: real token from the API, stored where the app keeps it. */
export async function apiLogin(page, request, email, password = PASSWORD) {
  const res = await request.post(`${API}/auth/login/json`, { data: { email, password } });
  if (!res.ok()) throw new Error(`login failed for ${email}: ${res.status()}`);
  const { access_token } = await res.json();
  await page.goto("/login");
  await page.evaluate((t) => localStorage.setItem("campusbite.token", t), access_token);
}

export const uniqueEmail = (tag) => `${tag}.${Date.now()}${Math.floor(Math.random() * 1e4)}@example.com`;
