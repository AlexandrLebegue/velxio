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
  await page.getByRole("button", { name: "Agent IA", exact: true }).click();
  await page.getByRole("button", { name: "Configurer mon modèle" }).click();
  await page
    .getByLabel("URL de base du LLM")
    .fill(process.env.AGENT_TEST_MODEL_URL);
  await page.getByLabel("Identifiant du modèle").fill("probe");
  await page.getByRole("button", { name: "Tester la connexion" }).click();
  await page
    .getByRole("status")
    .filter({ hasText: "verified" })
    .waitFor({ timeout: 35000 });
  await page.getByRole("button", { name: "Enregistrer", exact: true }).click();
  await page
    .getByLabel("Message à l’agent")
    .fill(
      "Modifie le sketch pour envoyer 42 sur le port série. Lance la simulation et observe la sortie.",
    );
  await page.getByRole("button", { name: "Envoyer", exact: true }).click();
  await page.waitForFunction(
    async () => {
      const { useSimulatorStore, getBoardSimulator } =
        await import("/src/store/useSimulatorStore.ts");
      const state = useSimulatorStore.getState();
      const board = state.boards.find(
        (item) => item.id === state.activeBoardId,
      );
      return (
        board?.running &&
        getBoardSimulator(board.id)?.isRunning?.() &&
        board.serialOutput.includes("42")
      );
    },
    undefined,
    { timeout: 120000 },
  );
  await page
    .getByRole("button", { name: "Envoyer", exact: true })
    .waitFor({ timeout: 30000 });
  const state = await page.evaluate(async () => {
    const { useSimulatorStore, getBoardSimulator } =
      await import("/src/store/useSimulatorStore.ts");
    const { useEditorStore } = await import("/src/store/useEditorStore.ts");
    const sim = useSimulatorStore.getState();
    const board = sim.boards.find((item) => item.id === sim.activeBoardId);
    return {
      running: board?.running,
      engineRunning: getBoardSimulator(board?.id)?.isRunning?.(),
      serial: board?.serialOutput?.slice(-120),
      source: useEditorStore.getState().files[0]?.content,
    };
  });
  const evidence = {
    state,
    browserResults: results,
    pageErrors,
    alerts: await page.locator(".agent-error").allTextContents(),
  };
  const artifact = process.env.AGENT_TEST_ARTIFACT || "/tmp/velxio-agent-ui";
  await page.screenshot({ path: `${artifact}-running.png`, fullPage: true });
  writeFileSync(`${artifact}-evidence.json`, JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
  if (
    !results.some((result) => result.state === "running" && result.ok) ||
    !results.some((result) => result.serial?.includes("42")) ||
    evidence.alerts.length
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
