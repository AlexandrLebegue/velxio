// @vitest-environment jsdom
import { webcrypto } from 'node:crypto';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { ComponentRegistry } from '../services/ComponentRegistry';
import { useSimulatorStore } from '../store/useSimulatorStore';
import { useEditorStore } from '../store/useEditorStore';
import { useWireDiagnosticsStore } from '../store/useWireDiagnosticsStore';
import { buildVlxPayload } from '../utils/vlxFile';
import {
  prepareAgentCircuit,
  inspectAgentProject,
  describeAgentPart,
} from '../services/agentCircuit';
import { applyAgentSnapshot } from '../services/agentBrowserBridge';
import { projectRevision } from '../services/agentService';
import type { VlxPayload } from '../utils/vlxFile';
import type { ComponentMetadata } from '../types/component-metadata';
import { WireRenderer } from '../components/simulator/WireRenderer';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

class TestLed extends HTMLElement {
  mode = 'normal';
  get pinInfo() {
    return [
      { name: this.mode === 'flipped' ? 'B' : 'A', x: 0, y: 10 },
      { name: 'C', x: 20, y: 10 },
    ];
  }
}

beforeAll(() => {
  customElements.define(
    'agent-test-board',
    class extends HTMLElement {
      get pinInfo() {
        return [
          { name: '13', x: 10, y: 0 },
          { name: '12', x: 20, y: 0 },
          { name: 'GND.1', x: 30, y: 0 },
        ];
      }
    },
  );
  customElements.define('agent-test-led', TestLed);
});

beforeEach(() => {
  useWireDiagnosticsStore.getState().clear();
  vi.stubGlobal('crypto', webcrypto);
  vi.stubGlobal('requestAnimationFrame', (callback: () => void) => {
    callback();
    return 1;
  });
  document.body.innerHTML =
    '<agent-test-board id="uno" data-board-kind="arduino-uno"></agent-test-board><agent-test-led id="led"></agent-test-led>';
  vi.spyOn(ComponentRegistry.getInstance(), 'load').mockResolvedValue();
  vi.spyOn(ComponentRegistry.getInstance(), 'getById').mockImplementation((id) =>
    id === 'led'
      ? ({
          id,
          tagName: 'agent-test-led',
          defaultValues: { mode: 'normal' },
          properties: [{ name: 'mode', type: 'string', defaultValue: 'normal' }],
        } as unknown as ComponentMetadata)
      : undefined,
  );
  useSimulatorStore.setState({
    boards: [
      {
        id: 'uno',
        boardKind: 'arduino-uno',
        x: 100,
        y: 100,
        activeFileGroupId: 'sketch',
        running: false,
      },
    ],
    components: [{ id: 'led', metadataId: 'led', x: 200, y: 100, properties: {} }],
    wires: [],
    activeBoardId: 'uno',
  } as never);
  useEditorStore.getState().replaceFileGroups({
    sketch: [{ name: 'sketch.ino', content: 'void setup(){} void loop(){}' }],
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

function withWire(pin = '13'): VlxPayload {
  const value = buildVlxPayload();
  // A valid native logical wire: the agent does not supply pixel coordinates.
  value.wires = [
    {
      id: 'wire',
      start: { componentId: 'uno', pinName: pin },
      end: { componentId: 'led', pinName: 'A' },
    },
  ] as VlxPayload['wires'];
  return value;
}

describe('agent circuit application with the real store', () => {
  it('returns mounted pins and a complete new-part reference in one read', async () => {
    expect(inspectAgentProject().pinouts.uno.pins).toEqual(['13', '12', 'GND.1']);
    expect(await describeAgentPart('component', 'led')).toMatchObject({
      pins: [{ name: 'A' }, { name: 'C' }],
      defaults: { mode: 'normal' },
      attrs: [{ name: 'mode', defaultValue: 'normal' }],
    });
  });

  it('validates the new board and waits for its replacement DOM while preserving source groups', async () => {
    const candidate = withWire('23');
    candidate.boards[0].boardKind = 'esp32';
    candidate.boards[0].languageMode = 'arduino';
    const source = candidate.fileGroups.sketch;
    let mounted = false;
    const off = useSimulatorStore.subscribe((state) => {
      if (state.boards[0]?.boardKind !== 'esp32') return;
      off();
      setTimeout(() => {
        document.getElementById('uno')?.remove();
        const element = document.createElement('velxio-esp32');
        element.id = 'uno';
        element.setAttribute('board-kind', 'esp32');
        element.dataset.boardKind = 'esp32';
        document.body.appendChild(element);
        mounted = true;
      }, 25);
    });
    try {
      await applyAgentSnapshot(candidate, await projectRevision());
      expect(mounted).toBe(true);
      expect(useSimulatorStore.getState().boards[0]).toMatchObject({
        id: 'uno',
        boardKind: 'esp32',
        activeFileGroupId: 'sketch',
      });
      expect(useEditorStore.getState().fileGroups.sketch).toMatchObject(source);
      expect(await projectRevision()).toBe(await projectRevision(candidate));
    } finally {
      off();
      useSimulatorStore.getState().removeBoard('uno');
    }
  });

  it('derives finite geometry and stable revisions for minimal logical wires', async () => {
    const before = await projectRevision();
    const candidate = withWire();
    const expected = await projectRevision(candidate);
    await applyAgentSnapshot(candidate, before);
    const actual = useSimulatorStore.getState().wires[0];
    expect(actual.start).toMatchObject({ x: 110, y: 100 });
    expect(actual.end).toMatchObject({ x: 206, y: 116 });
    expect(actual.waypoints).toEqual([]);
    expect(actual.color).toBe('#00c853');
    expect(await projectRevision()).toBe(expected);
  });

  it('rejects unknown pins even if their coordinates appear connected, without mutating the circuit', async () => {
    const before = buildVlxPayload();
    const candidate = withWire('__missing_pin__');
    candidate.wires[0].start.x = 110;
    candidate.wires[0].start.y = 100;
    await expect(applyAgentSnapshot(candidate, await projectRevision())).rejects.toMatchObject({
      code: 'pin_invalid',
      details: { pin: '__missing_pin__', valid_pins: ['13', '12', 'GND.1'] },
    });
    expect(buildVlxPayload().wires).toEqual(before.wires);
    expect(buildVlxPayload().components).toEqual(before.components);
    expect(useWireDiagnosticsStore.getState().errors).toEqual({});
  });

  it('marks an invalid wire already present in a legacy project and clears it after repair', async () => {
    const candidate = withWire('__missing_pin__');
    useSimulatorStore.getState().applyCircuitState(candidate.components, candidate.wires);
    await expect(prepareAgentCircuit(candidate)).rejects.toMatchObject({ code: 'pin_invalid' });
    expect(useWireDiagnosticsStore.getState().errors.wire).toMatchObject({
      endpoint: 'start',
      pin: '__missing_pin__',
    });
    await prepareAgentCircuit(withWire());
    expect(useWireDiagnosticsStore.getState().errors).toEqual({});
  });

  it('renders a legacy unknown pin as unresolved even without an agent turn', () => {
    const wire = withWire('__missing_pin__').wires[0];
    Object.assign(wire, { color: '#00c853', waypoints: [] });
    Object.assign(wire.start, { x: 110, y: 100 });
    Object.assign(wire.end, { x: 206, y: 116 });
    const html = renderToStaticMarkup(
      createElement(WireRenderer, {
        wire,
        isSelected: false,
        isHovered: false,
      }),
    );
    expect(html).toContain('data-wire-invalid="true"');
    expect(html).toContain('stroke-dasharray="5,4"');
    expect(html).toContain('uno:__missing_pin__');
  });

  it('uses the candidate component properties to validate a changed pinout', async () => {
    const candidate = withWire();
    candidate.components[0].properties.mode = 'flipped';
    await expect(prepareAgentCircuit(candidate)).rejects.toMatchObject({
      code: 'pin_invalid',
      details: { pin: 'A', valid_pins: ['B', 'C'] },
    });
  });

  it('waits for a newly added component to mount before acknowledging application', async () => {
    const candidate = withWire();
    candidate.components.push({ id: 'added', metadataId: 'led', x: 300, y: 100, properties: {} });
    candidate.wires[0].end.componentId = 'added';
    let mounted = false;
    const off = useSimulatorStore.subscribe((state) => {
      if (!state.components.some((item) => item.id === 'added')) return;
      off();
      setTimeout(() => {
        const element = document.createElement('agent-test-led');
        element.id = 'added';
        document.body.appendChild(element);
        mounted = true;
      }, 25);
    });
    await applyAgentSnapshot(candidate, await projectRevision());
    expect(mounted).toBe(true);
    expect(useSimulatorStore.getState().wires[0].end).toMatchObject({
      componentId: 'added',
      x: 306,
      y: 116,
    });
  });

  it('resolves aliases to actual pad names and emits topology atomically', async () => {
    const candidate = withWire('D13');
    expect((await prepareAgentCircuit(candidate)).wires[0].start).toMatchObject({
      pinName: '13',
      x: 110,
      y: 100,
    });
    const changes: Array<[number, number]> = [];
    const off = useSimulatorStore.subscribe((state) =>
      changes.push([state.components.length, state.wires.length]),
    );
    useSimulatorStore
      .getState()
      .applyCircuitState(candidate.components, (await prepareAgentCircuit(candidate)).wires);
    off();
    expect(changes).toEqual([[1, 1]]);
  });

  it('canonicalizes component aliases so the electrical model sees the same pad', async () => {
    const candidate = withWire();
    candidate.wires[0].end.pinName = 'A.1';
    const resolved = await prepareAgentCircuit(candidate);
    expect(resolved.wires[0].end.pinName).toBe('A');
    expect(await projectRevision(resolved)).toBe(await projectRevision(withWire()));
  });
});
