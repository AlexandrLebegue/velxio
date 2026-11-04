// Export real pinInfo with jsdom and the editor's alias resolver. No browser.
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const require = createRequire(process.cwd() + '/frontend/package.json');
const { JSDOM } = require('jsdom');
const window = new JSDOM('<html><body></body></html>', { pretendToBeVisual: true }).window;
for (const key of ['window', 'document', 'customElements', 'HTMLElement', 'Element', 'Node', 'Document', 'DocumentFragment', 'ShadowRoot', 'CSSStyleSheet', 'CustomEvent', 'MutationObserver', 'navigator']) {
  Object.defineProperty(globalThis, key, { value: key === 'window' ? window : window[key], configurable: true });
}
require('@wokwi/elements');
const inventory = {};
for (const key of ['arduino-uno', 'arduino-nano', 'servo', 'resistor', 'led']) {
  const element = document.createElement('wokwi-' + key);
  document.body.append(element);
  await element.updateComplete;
  inventory[key] = { pins: element.pinInfo, source: '@wokwi/elements pinInfo via jsdom' };
}
const snapshot = JSON.parse(readFileSync('backend/app/mcp/compact/catalog.snapshot.json'));
for (const id of ['board:esp32', 'component:epaper-1in54-bw']) {
  const entry = snapshot.entries.find((entry) => entry.id === id);
  inventory[entry.key] = { pins: entry.pins, source: entry.sources };
}
const { build } = require('esbuild');
const output = process.argv[2];
const bundled = await build({ entryPoints: ['frontend/src/utils/pinPositionCalculator.ts'], bundle: true, format: 'esm', platform: 'node', write: false, define: { 'import.meta.env.MODE': '"test"' } });
const resolver = output + '.resolver.mjs';
writeFileSync(resolver, bundled.outputFiles[0].text);
const { resolvePinDescriptor } = await import(pathToFileURL(resolver));
for (const entry of Object.values(inventory)) {
  const candidates = new Set(['GND', 'GND2', '3.3V', '3V3', '5V', ...entry.pins.flatMap((pin) => [pin.name, pin.name.split('.')[0]])]);
  for (let index = 0; index <= 64; index++) for (const prefix of ['', 'D', 'GP']) candidates.add(prefix + index);
  entry.aliases = Object.fromEntries([...candidates].map((name) => [name, resolvePinDescriptor(entry.pins, name)?.name]).filter(([, target]) => target));
}
writeFileSync(output, JSON.stringify(inventory, null, 2));
window.close();
