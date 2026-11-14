import { expect, test } from "@playwright/test";
import { COURIER, OWNER, uiLogin, uniqueEmail } from "./helpers";

/*
 * Full role workflows through the browser UI against the real backend + PostgreSQL.
 * Requires: docker compose up, alembic upgrade head, python -m app.seed.
 */
test.describe.configure({ mode: "serial" });

let customerEmail;
let orderId;

async function registerCustomer(page) {
  customerEmail = uniqueEmail("e2e");
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Customer");
  await page.getByLabel("E-mail").fill(customerEmail);
  await page.getByLabel("Password", { exact: true }).fill("Campus123");
  await page.getByLabel("Confirm password").fill("Campus123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/");
}

async function addBurgersAndCheckout(page) {
  await page.goto("/");
  await page.getByRole("link", { name: /Campus Grill/ }).click();
  await page.getByRole("button", { name: "Add Classic Burger to cart" }).click();
  await page.getByRole("button", { name: "Add Classic Burger to cart" }).click();
  await page.getByRole("link", { name: /Cart, 2 items/ }).click();
  await expect(page.getByText("Total")).toBeVisible();
  await page.getByLabel("Delivery address").fill("Hostel 3, Room 204");
  await page.getByRole("button", { name: /and place order/ }).click();
  await page.waitForURL(/\/orders\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Order placed and paid.")).toBeVisible();
  return page.url().split("/").pop();
}

test("validation errors and wrong password are shown", async ({ page }) => {
  await page.goto("/register");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Enter your name")).toBeVisible();
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(OWNER);
  await page.getByLabel("Password").fill("wrongpass1");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("status")).toContainText(/Incorrect|invalid/i);
});

test("customer: register, search, checkout, history, cancel while placed", async ({ page }) => {
  await registerCustomer(page);
  await page.goto("/search");
  await page.getByLabel("Dish name").fill("burger");
  await page.getByLabel("Maximum price").fill("5.25");
  await expect(page.getByText("Veggie Burger")).toBeVisible();
  await expect(page.getByText("Classic Burger")).toHaveCount(0); // 5.50 > 5.25

  const cancelId = await addBurgersAndCheckout(page);
  await page.getByRole("button", { name: "Cancel order" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel order" }).click();
  await expect(page.getByText("Order cancelled")).toBeVisible();
  await expect(page.getByText("Refunded").first()).toBeVisible();

  orderId = await addBurgersAndCheckout(page);
  await page.goto("/orders");
  await expect(page.locator(".order-row")).toHaveCount(2);
  await page.getByLabel("Status").selectOption("cancelled");
  await expect(page.locator(".order-row")).toHaveCount(1);
  await expect(page.locator(".order-row")).toContainText(cancelId.slice(-8));
});

test("owner: accept, prepare, ready, assign courier", async ({ page }) => {
  const short = orderId.slice(-8);
  await uiLogin(page, OWNER);
  await expect(page).toHaveURL("/owner");
  await page.goto("/owner/orders");
  const card = () => page.locator(".card", { hasText: `#${short}` });

  await card().getByRole("button", { name: "Accept" }).click();
  await page.getByRole("tab", { name: "Accepted" }).click();
  await card().getByRole("button", { name: "Start preparing" }).click();
  await page.getByRole("tab", { name: "Preparing" }).click();
  await card().getByRole("button", { name: "Mark ready" }).click();
  await page.getByRole("tab", { name: "Ready" }).click();
  await card().getByLabel("Assign courier").selectOption({ label: "Dev Courier" });
  await expect(page.getByText("Courier assigned.")).toBeVisible();
});

test("courier: picked up, delivered (confirmed); invalid moves blocked", async ({ page }) => {
  const short = orderId.slice(-8);
  await uiLogin(page, COURIER);
  await expect(page).toHaveURL("/delivery");
  const card = page.locator(".card", { hasText: `#${short}` });
  await card.getByRole("button", { name: /Picked up/ }).click();
  await expect(page.getByText(`Picked up – out for delivery: #${short}`)).toBeVisible();
  await card.getByRole("button", { name: "Mark delivered" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delivered" }).click();
  await page.getByRole("tab", { name: /Delivered/ }).click();
  await expect(page.locator(".card", { hasText: `#${short}` })).toContainText("Delivered");
  await expect(card.getByRole("button")).toHaveCount(0); // no further actions offered
});

test("customer: review once, refund request; owner approves", async ({ browser }) => {
  const customer = await browser.newPage();
  await uiLogin(customer, customerEmail);
  await customer.goto(`/orders/${orderId}`);
  await customer.getByRole("button", { name: "Write a review" }).click();
  await customer.getByRole("radio", { name: "4 stars" }).click();
  await customer.getByRole("button", { name: "Submit review" }).click();
  await expect(customer.getByText("Thanks for your review!")).toBeVisible();
  await expect(customer.getByRole("button", { name: "Write a review" })).toHaveCount(0); // no duplicates

  await customer.getByRole("button", { name: "Request refund" }).click();
  await customer.getByLabel(/What went wrong/).fill("Burger was cold");
  await customer.getByRole("button", { name: "Send request" }).click();
  await expect(customer.getByText("Refund pending")).toBeVisible();
  await expect(customer.getByRole("button", { name: "Request refund" })).toHaveCount(0);

  const owner = await browser.newPage();
  await uiLogin(owner, OWNER);
  await owner.goto("/owner/orders");
  const req = owner.locator(".order-row", { hasText: "Burger was cold" }).first();
  await req.getByRole("button", { name: "Approve" }).click();
  await owner.getByRole("dialog").getByRole("button", { name: "Approve refund" }).click();
  await expect(owner.getByText("Refund approved and processed.")).toBeVisible();

  await customer.reload();
  await expect(customer.getByText("Refund approved · refunded")).toBeVisible();
  await expect(customer.getByText("Refunded", { exact: true }).first()).toBeVisible(); // payment badge
});

test("AI insights shows the real backend answer or its real error", async ({ page }) => {
  await uiLogin(page, customerEmail);
  await page.goto("/insights");
  await page.getByRole("button", { name: "How much did I spend this week?" }).click();
  // With OPENAI_API_KEY set: an AI bubble with "Based on N order(s)". Without: the 503 message.
  await expect(page.locator(".bubble.ai, .bubble.err").last()).toBeVisible({ timeout: 45_000 });
  await expect(page.locator(".bubble.ai:not(.muted), .bubble.err").last()).toContainText(/AI-generated|not configured|AI/);
  await page.getByRole("button", { name: "Summarize my order history" }).click();
  await expect(page.locator(".bubble")).toHaveCount(4, { timeout: 45_000 }); // 2 questions + 2 real responses

  // A brand-new customer has no orders: factual reply, no OpenAI call involved.
  await page.evaluate(() => localStorage.clear());
  await page.goto("/register");
  await page.getByLabel("Full name").fill("No Orders Yet");
  await page.getByLabel("E-mail").fill(`noorders.${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("Campus123");
  await page.getByLabel("Confirm password").fill("Campus123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/"); // registered and logged in
  await page.goto("/insights");
  await page.getByRole("button", { name: "Summarize my order history" }).click();
  await expect(page.getByText("You haven't placed any orders yet")).toBeVisible();
});

test("role guards, unknown routes and invalid tokens", async ({ page }) => {
  await uiLogin(page, customerEmail);
  await page.goto("/owner");
  await expect(page.getByText("Not allowed")).toBeVisible();
  await page.goto("/delivery");
  await expect(page.getByText("Not allowed")).toBeVisible();
  await page.goto("/no-such-page");
  await expect(page.getByText("Page not found")).toBeVisible();

  await page.evaluate(() => localStorage.setItem("campusbite.token", "expired.or.forged"));
  await page.goto("/orders");
  await expect(page).toHaveURL(/\/login/);
  expect(await page.evaluate(() => localStorage.getItem("campusbite.token"))).toBeNull();
});
