import { expect, test } from "@playwright/test";
import { COURIER, OWNER, apiLogin } from "./helpers";

/* Every page at 375/430/768/1024/1440 px: no horizontal page overflow, no element wider
 * than the viewport (tables scroll inside their own wrapper), nav visible. Screenshots go
 * to e2e/screenshots for manual review. */
const WIDTHS = [375, 430, 768, 1024, 1440];
const ROLES = {
  guest: { pages: ["/", "/search", "/login", "/register", "/cart"] },
  customer: { email: "asha@example.com", pages: ["/orders", "/refunds", "/insights"] },
  owner: { email: OWNER, pages: ["/owner", "/owner/orders", "/owner/restaurants", "/insights"] },
  courier: { email: COURIER, pages: ["/delivery", "/insights"] },
};

async function overflow(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const offenders = [];
    for (const el of document.querySelectorAll("body *")) {
      if (el.closest(".table-wrap, .tabs")) continue; // these scroll horizontally by design
      const r = el.getBoundingClientRect();
      if (r.width && (r.right > vw + 1 || r.left < -1)) offenders.push(`${el.tagName}.${el.className}`.slice(0, 80));
    }
    return { page: document.documentElement.scrollWidth - vw, offenders: offenders.slice(0, 5) };
  });
}

for (const [role, cfg] of Object.entries(ROLES)) {
  test(`layout: ${role}`, async ({ page, request }) => {
    if (cfg.email) await apiLogin(page, request, cfg.email);
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of cfg.pages) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 15_000 });
        const o = await overflow(page);
        expect(o, `${role} ${path} @${width}px`).toEqual({ page: 0, offenders: [] });
        const nav = width >= 820 ? page.locator(".header-nav") : page.locator(".mobile-nav");
        await expect(nav).toBeVisible();
        await page.screenshot({ path: `e2e/screenshots/${role}${path.replaceAll("/", "_") || "_home"}-${width}.png`, fullPage: true });
      }
    }
  });
}

test("restaurant detail and modal fit on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/");
  await page.getByRole("link", { name: /Campus Grill/ }).click();
  await expect(page.getByRole("button", { name: /Add Classic Burger/ })).toBeVisible();
  expect(await overflow(page)).toEqual({ page: 0, offenders: [] });
  // touch targets: primary buttons at least 32px tall
  const h = await page.getByRole("button", { name: /Add Classic Burger/ }).evaluate((b) => b.getBoundingClientRect().height);
  expect(h).toBeGreaterThanOrEqual(32);
});
