#!/usr/bin/env node
'use strict';
// Local AST extraction, never imports/evaluates a browser module.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;
const babel = require('@babel/core');
const tsPlugin = require('@babel/plugin-transform-typescript');
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const files = new Map();
const modules = new Map();
const origins = new Map();
const libraryOrigins = new Map();
const rawInputs = new Map();
const globals = new Set(['Object', 'Array', 'String', 'Number', 'Boolean', 'Math', 'JSON', 'Set', 'Map', 'undefined']);
function read(file, raw = false) {
  const full = path.resolve(root, file);
  if (!full.startsWith(root + path.sep)) throw Error(`Outside repository: ${file}`);
  const bytes = fs.readFileSync(full);
  const data = bytes.toString('utf8');
  files.set(file, sha(bytes));
  if (!Buffer.from(data).equals(bytes)) {
    if (!raw) throw Error(`${file}: invalid UTF-8 in structured source`);
    // Match Vite ?raw text decoding, but retain original bytes, never discard.
    rawInputs.set(file, {path: file, sha256: sha(bytes), decoded_sha256: sha(data), content_b64: bytes.toString('base64')});
  }
  return data;
}
function source(file, node) { return {path: file, line: node.loc.start.line, sha256: files.get(file)}; }
function moduleOf(file) {
  if (modules.has(file)) return modules.get(file);
  const ast = parser.parse(read(file), {sourceType: 'module', plugins: ['typescript']});
  const mod = {ast, bindings: new Map(), cache: new Map(), active: new Set()};
  modules.set(file, mod);
  for (let node of ast.program.body) {
    if (node.type === 'ImportDeclaration' && node.importKind !== 'type') {
      for (const spec of node.specifiers) mod.bindings.set(spec.local.name, {import: node.source.value, name: spec.imported?.name || 'default'});
    }
    if (node.type === 'ExportNamedDeclaration') node = node.declaration;
    if (!node) continue;
    if (node.type === 'VariableDeclaration') for (const d of node.declarations) {
      if (d.id.type !== 'Identifier') throw Error(`${file}:${d.loc.start.line}: destructured declaration unsupported`);
      mod.bindings.set(d.id.name, {expr: d.init, node: d});
    }
    if (node.type === 'FunctionDeclaration') mod.bindings.set(node.id.name, {fn: node, node});
  }
  traverse(ast, {ObjectExpression(p) {
    const id = p.node.properties.find(x => x.key?.name === 'id' && x.value?.type === 'StringLiteral');
    if (id && p.node.properties.some(x => x.key?.name === 'title')) {
      origins.set(id.value.value, source(file, p.node));
      const libs = p.node.properties.find(x => x.key?.name === 'libraries');
      if (libs) libraryOrigins.set(id.value.value, [source(file, libs), ...(libs.value.type === 'Identifier' && mod.bindings.get(libs.value.name)?.node ? [source(file, mod.bindings.get(libs.value.name).node)] : [])]);
    }
  }});
  return mod;
}
function evaluate(file, node, fnName) {
  // Generate only the reachable expression/helper; no module-level side effects.
  const wrapper = fnName
    ? {type: 'File', program: {type: 'Program', sourceType: 'script', body: [node]}}
    : {type: 'File', program: {type: 'Program', sourceType: 'script', body: [{type: 'VariableDeclaration', kind: 'const', declarations: [{type: 'VariableDeclarator', id: {type: 'Identifier', name: '__value'}, init: node}]}]}};
  const code = babel.transformFromAstSync(wrapper, undefined, {filename: file, configFile: false, babelrc: false, plugins: [tsPlugin], comments: false}).code;
  const deps = new Set();
  traverse(parser.parse(code), {ReferencedIdentifier(p) {
    if (!p.scope.hasBinding(p.node.name) && !globals.has(p.node.name)) deps.add(p.node.name);
  }});
  const context = Object.create(null);
  for (const name of deps) context[name] = resolve(file, name);
  return vm.runInNewContext(`${code}\n;${fnName || '__value'}`, context, {timeout: 2000, contextCodeGeneration: {strings: false, wasm: false}});
}
function resolve(file, name) {
  const mod = moduleOf(file);
  if (mod.cache.has(name)) return mod.cache.get(name);
  if (mod.active.has(name)) throw Error(`${file}: cyclic data dependency ${name}`);
  const b = mod.bindings.get(name);
  if (!b) throw Error(`${file}: unsupported/unresolved data dependency ${name}`);
  mod.active.add(name);
  let value;
  if (b.import) {
    let target;
    if (b.import === '@pro/data/proExamples') target = 'frontend/src/__pro_stub__/data/proExamples.ts';
    else if (b.import.startsWith('.')) target = path.posix.normalize(path.posix.join(path.posix.dirname(file), b.import));
    else throw Error(`${file}: nonlocal import ${b.import}`);
    if (target.endsWith('?raw')) value = read(target.slice(0, -4), true);
    else {
      if (!target.startsWith('frontend/src/data/') && target !== 'frontend/src/__pro_stub__/data/proExamples.ts') throw Error(`${file}: non-data import ${target}`);
      value = resolve(target + (target.endsWith('.ts') ? '' : '.ts'), b.name);
    }
  } else value = evaluate(file, b.fn || b.expr, b.fn && name);
  mod.active.delete(name);
  mod.cache.set(name, value);
  return value;
}
function location(file, name) { return source(file, moduleOf(file).bindings.get(name).node); }
function plain(value) {
  return JSON.parse(JSON.stringify(value, (key, item) => {
    if (['undefined', 'function', 'symbol', 'bigint'].includes(typeof item) ||
        (typeof item === 'number' && !Number.isFinite(item))) {
      throw Error(`Non-JSON data at ${key || '(root)'}; refusing lossy extraction`);
    }
    return item;
  }));
}
function main() {
  const metadataFile = 'frontend/public/components-metadata.json';
  const metadataText = read(metadataFile);
  const metadata = JSON.parse(metadataText);
  const metadataItems = metadata.components.map(data => {
    const offset = metadataText.indexOf('"id": ' + JSON.stringify(data.id));
    if (offset < 0) throw Error(`Cannot locate metadata provenance for ${data.id}`);
    return {data, source: {path: metadataFile, line: metadataText.slice(0, offset).split('\n').length, sha256: files.get(metadataFile)}};
  });
  const registryFile = 'frontend/src/services/ComponentRegistry.ts';
  const registry = moduleOf(registryFile);
  const additions = [];
  traverse(registry.ast, {CallExpression(p) {
    const c = p.node.callee;
    if (c.type === 'MemberExpression' && c.property.name === 'push' && c.object.type === 'MemberExpression' && c.object.object.name === 'data' && c.object.property.name === 'components') {
      if (p.node.arguments.length !== 1 || p.node.arguments[0].type !== 'ObjectExpression') throw Error('Registry injection shape changed');
      additions.push({data: plain(evaluate(registryFile, p.node.arguments[0])), source: source(registryFile, p.node)});
    }
  }});
  const boardFile = 'frontend/src/types/board.ts';
  const labels = plain(resolve(boardFile, 'BOARD_KIND_LABELS'));
  const keywordsFile = 'frontend/src/data/componentSearchKeywords.ts';
  const keywords = plain(resolve(keywordsFile, 'KEYWORDS'));
  const boardKeywords = plain(resolve(keywordsFile, 'BOARD_KEYWORDS'));
  const fqbns = plain(resolve(boardFile, 'BOARD_KIND_FQBN'));
  const idf = Array.from(resolve(boardFile, 'BOARD_SUPPORTS_ESPIDF'));
  const micro = Array.from(resolve(boardFile, 'BOARD_SUPPORTS_MICROPYTHON'));
  const espFile = 'frontend/src/components/velxio-components/Esp32Element.ts';
  const esp = plain(resolve(espFile, 'BOARD_CONFIGS'));
  const panelFile = 'frontend/src/simulation/displays/EPaperPanels.ts';
  const panels = plain(resolve(panelFile, 'PANEL_CONFIGS'));
  const pinFile = 'frontend/src/components/velxio-components/EPaperElement.ts';
  const panelPins = plain(resolve(pinFile, 'STANDARD_PIN_NAMES'));
  const protocolFile = 'frontend/src/simulation/parts/EPaperPart.ts';
  const protocolText = read(protocolFile);
  const protocolLine = protocolText.split('\n').findIndex(line => line.includes('const handle = attachSpiDevice(')) + 1;
  if (!protocolLine) throw Error('E-paper SPI provenance changed; review extractor');
  const nativeFile = 'frontend/src/utils/wokwiZip.ts';
  const nativeBoards = plain(resolve(nativeFile, 'WOKWI_NATIVE_BOARDS'));
  const exampleFile = 'frontend/src/data/examples.ts';
  const examples = plain(resolve(exampleFile, 'exampleProjects'));
  const entries = [];
  const unknown = 'unknown';
  for (const item of [...metadataItems, ...additions]) {
    const c = item.data;
    const panel = panels[c.id];
    const espKind = Object.keys(esp).find(key => path.posix.basename(esp[key].svgUrl, '.svg') === c.id);
    const pinSources = panel ? [location(pinFile, 'STANDARD_PIN_NAMES'), location(panelFile, 'PANEL_CONFIGS')]
      : espKind ? [location(espFile, 'BOARD_CONFIGS')] : [];
    entries.push({id: `component:${c.id}`, kind: 'component', key: c.id, name: c.name, summary: c.description || c.name,
      aliases: [...new Set([c.tagName, `wokwi-${c.id}`, `velxio-${c.id}`])],
      tags: c.tags || [], keywords: [keywords[c.id] || '', ...(c.keywords || [])], attrs: c.properties || [], defaults: c.defaultValues || {},
      pins: panel ? panelPins.map(name => ({name})) : espKind ? esp[espKind].pins : unknown,
      protocol: panel ? {name: 'SPI', sources: [{path: protocolFile, line: protocolLine, sha256: files.get(protocolFile)}]} : unknown,
      panel: panel || null, sources: [item.source, ...pinSources], limitations: panel ? ['Accelerated refresh; no hardware timing guarantee.', 'Standalone minimal initialization not extracted; consult an explicit example code section.'] : ['Unextracted pin names/protocol remain unknown; pinCount is not a pin list.'],
      pin_count: c.pinCount, category: c.category});
  }
  for (const [key, name] of Object.entries(labels)) entries.push({id: `board:${key}`, kind: 'board', key, name, summary: name,
    aliases: [`board-velxio-${key}`, ...(nativeBoards[key] ? [nativeBoards[key].type] : [])], keywords: [boardKeywords[key] || ''], fqbn: fqbns[key], languages: [...(fqbns[key] ? ['arduino'] : []), ...(idf.includes(key) ? ['espidf'] : []), ...(micro.includes(key) ? ['micropython'] : [])],
    pins: esp[key] ? esp[key].pins : unknown, attrs: [], protocol: unknown, sources: [location(boardFile, 'BOARD_KIND_LABELS'), location(boardFile, 'BOARD_KIND_FQBN'), ...(esp[key] ? [location(espFile, 'BOARD_CONFIGS')] : [])],
    limitations: ['Catalog presence does not establish installed compiler or simulation support.', ...(!esp[key] ? ['Physical pin list not extracted for this board.'] : [])]});
  for (const e of examples) {
    if (!e.id || !e.title || !Array.isArray(e.components) || !Array.isArray(e.wires)) throw Error(`Invalid example ${e.id}`);
    entries.push({id: `example:${e.id}`, kind: 'example', key: e.id, name: e.title, summary: e.description,
      tags: e.tags || [], aliases: [], sources: [origins.get(e.id) || location(exampleFile, 'exampleProjects')], library_sources: libraryOrigins.get(e.id) || [],
      pins: unknown, attrs: [], protocol: unknown, limitations: ['Example sources are provided as authored; build and execution have not been verified.'], project: e});
  }
  // Hash the extractor as well as all consumed inputs; no time or absolute paths.
  read('scripts/generate-mcp-compact-catalog.cjs');
  for (const entry of entries) for (const s of entry.sources) s.sha256 = files.get(s.path);
  const ids = entries.map(e => e.id);
  if (new Set(ids).size !== ids.length) throw Error('Duplicate catalog IDs; refusing to lose/overwrite entries');
  entries.sort((a,b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  const inputs = [...files].sort(([a],[b]) => a < b ? -1 : 1).map(([path, sha256]) => ({path, sha256}));
  const payload = {schema_version: 1, extractor: {parser:'@babel/parser', version:require('@babel/parser/package.json').version, babel:require('@babel/core/package.json').version, typescript_transform:require('@babel/plugin-transform-typescript/package.json').version}, inputs, raw_inputs: [...rawInputs.values()], limitations: ['OSS data only; private/dynamic overlay additions excluded.', 'Only reachable data declarations and helpers evaluated in a timed VM; browser modules never imported.', ...(rawInputs.size ? ['Some ?raw inputs contain invalid UTF-8; original bytes retained as base64 in explicit code sections.'] : [])], entries};
  const bytes = JSON.stringify(payload);
  process.stdout.write(JSON.stringify({revision: sha(bytes), ...payload}) + '\n');
}
try { main(); } catch (error) { process.stderr.write(`Catalog extraction failed: ${error.message}\n`); process.exitCode = 1; }
