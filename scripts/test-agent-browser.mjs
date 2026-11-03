// Requires a running Velxio backend with the AVR toolchain and the local model
// fixture from test/backend/integration/test_agent_opencode.py --serve-model.
import { writeFileSync } from "node:fs";
const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE || "playwright"
);
if (!process.env.AGENT_TEST_MODEL_URL)
  throw new Error(
    "Set AGENT_TEST_MODEL_URL to the local model fixture API base URL",
  );
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_PATH
    ? { executablePath: process.env.CHROMIUM_PATH }
    : {}),
  args: ["--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1540, height: 980 } });
const results = [];
const pageErrors = [];
page.on("request", (request) => {
  if (request.url().includes("/browser-result"))
    results.push(request.postDataJSON().result);
});
page.on("pageerror", (error) => pageErrors.push(error.message));
try {
  const origin = process.env.VELXIO_TEST_URL || "http://127.0.0.1:5181";
  await page.goto(`${origin}/editor?agent-preview=1`, {
    waitUntil: "networkidle",
    timeout: 60000,
  });
  await page.locator(".monaco-editor").first().waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "AI agent", exact: true }).click();
  await page.getByRole("button", { name: "Connect a model" }).click();
  await page
    .getByLabel("LLM API base URL")
    .fill(process.env.AGENT_TEST_MODEL_URL);
  await page.getByLabel("Model ID").fill("probe");
  await page.getByRole("button", { name: "Test connection" }).click();
  await page
    .getByRole("status")
    .filter({ hasText: "verified" })
    .waitFor({ timeout: 35000 });
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page
    .getByLabel("Message to the agent")
    .fill(
      "Wire the LED to GPIO 12, update the sketch to print 42 to serial, run the simulation, and observe the output.",
    );
  await page
    .locator(".agent-panel")
    .getByRole("button", { name: "Send", exact: true })
    .click();
  await page
    .locator('[data-testid="serial-monitor-output"]')
    .filter({ hasText: "42" })
    .waitFor({ timeout: 120000 });
  await page
    .locator(".agent-panel")
    .getByRole("button", { name: "Send", exact: true })
    .waitFor({ timeout: 30000 });
  const state = await page.evaluate(() => {
    const led = document.getElementById("led_builtin");
    return {
      serial: document
        .querySelector('[data-testid="serial-monitor-output"]')
        ?.textContent?.slice(-120),
      ledOn: led?.value,
      brightness: led?.brightness,
      connection: document
        .querySelector('[data-wire-id="wire_builtin_pin13"]')
        ?.getAttribute("data-wire-start"),
      source: document
        .querySelector(".monaco-editor")
        ?.textContent?.slice(0, 180),
    };
  });
  const steps = await page.locator(".agent-step").count();
  const failedSteps = await page.locator(".agent-step--error").count();
  const thinkingBlocks = await page.locator(".agent-thinking").count();
  const evidence = {
    state,
    steps,
    failedSteps,
    thinkingBlocks,
    browserResults: results,
    pageErrors,
    alerts: await page.locator(".agent-error").allTextContents(),
  };
  const artifact = process.env.AGENT_TEST_ARTIFACT || "/tmp/velxio-agent-ui";
  await page.screenshot({ path: `${artifact}-running.png`, fullPage: true });
  writeFileSync(`${artifact}-evidence.json`, JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "AI agent", exact: true }).click();
  await page.locator(".agent-step").first().waitFor({ timeout: 15000 });
  evidence.restoredSteps = await page.locator(".agent-step").count();
  writeFileSync(`${artifact}-evidence.json`, JSON.stringify(evidence, null, 2));
  if (evidence.restoredSteps !== steps)
    throw new Error("Action history was lost after reload");
  if (
    process.env.AGENT_TEST_CIRCUIT === "1" &&
    (!state.connection?.endsWith(":12") ||
      state.ledOn !== true ||
      failedSteps !== 1 ||
      thinkingBlocks < 1 ||
      !results.some((result) => result.error?.code === "pin_invalid"))
  )
    throw new Error(
      "Circuit repair, LED behavior, or thinking presentation did not match",
    );
  const thinking = page.locator(".agent-thinking").first();
  if (await thinking.count()) {
    if ((await thinking.getAttribute("open")) !== null)
      throw new Error("Thinking must start collapsed");
    await thinking.locator("summary").focus();
    await page.keyboard.press("Enter");
    if ((await thinking.getAttribute("open")) === null)
      throw new Error("Thinking cannot be opened with the keyboard");
  }
  await page.evaluate(() => localStorage.setItem("velxio-theme", "light"));
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "AI agent", exact: true }).click();
  await page.locator(".agent-step").first().waitFor();
  evidence.light = await page.locator(".agent-panel").evaluate((element) => ({
    color: getComputedStyle(element).color,
    background: getComputedStyle(element).backgroundColor,
    theme: document.documentElement.dataset.theme,
  }));
  if (
    evidence.light.color === evidence.light.background ||
    evidence.light.theme !== "light"
  )
    throw new Error("Light theme is not applied");
  await page.screenshot({ path: `${artifact}-light.png`, fullPage: true });
  await page.goto(`${origin}/fr/editor?agent-preview=1`, {
    waitUntil: "networkidle",
  });
  await page.getByRole("button", { name: "Agent IA", exact: true }).click();
  await page
    .getByRole("button", { name: "Connecter un modèle", exact: true })
    .click();
  await page.getByLabel("URL de base de l’API LLM").waitFor();
  evidence.french = await page.locator(".agent-settings").innerText();
  await page.screenshot({
    path: `${artifact}-fr-settings.png`,
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Fermer les paramètres", exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  const box = await page.locator(".agent-panel").boundingBox();
  if (!box || box.x < 0 || box.width > 390 || box.height > 844)
    throw new Error("Agent panel overflows mobile viewport");
  evidence.mobile = box;
  await page.screenshot({ path: `${artifact}-mobile.png`, fullPage: true });
  writeFileSync(`${artifact}-evidence.json`, JSON.stringify(evidence, null, 2));
  if (
    !results.some((result) => result.state === "running" && result.ok) ||
    !results.some((result) => result.serial?.includes("42")) ||
    evidence.alerts.length ||
    pageErrors.length
  )
    process.exitCode = 1;
} catch (error) {
  await page.screenshot({
    path: "/tmp/velxio-agent-ui-failure.png",
    fullPage: true,
  });
  console.error(error);
  console.error(
    JSON.stringify({
      results,
      pageErrors,
      alerts: await page.locator(".agent-error").allTextContents(),
    }),
  );
  process.exitCode = 1;
} finally {
  await browser.close();
}
