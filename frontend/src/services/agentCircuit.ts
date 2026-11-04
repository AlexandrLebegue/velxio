import { ComponentRegistry } from './ComponentRegistry';
import type { ComponentMetadata } from '../types/component-metadata';
import { normalizeAgentDocument } from './agentDocument';
import type { VlxPayload } from '../utils/vlxFile';
import { readPinInfo } from '../utils/readPinInfo';
import {
  calculatePinPosition,
  resolvePinDescriptor,
  type PinDescriptor,
} from '../utils/pinPositionCalculator';
import { boardSize } from '../utils/boardGeometry';
import type { BoardKind } from '../types/board';
import { useSimulatorStore } from '../store/useSimulatorStore';
import { useWireDiagnosticsStore } from '../store/useWireDiagnosticsStore';
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import {
  BOARD_KIND_LABELS,
  BOARD_SUPPORTS_MICROPYTHON,
  BOARD_SUPPORTS_ESPIDF,
  isPiBoardKind,
  type BoardInstance,
} from '../types/board';

export class AgentCircuitError extends Error {
  readonly code: string;
  readonly details: Record<string, unknown>;
  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

async function readyPins(element: Element, instance: string): Promise<PinDescriptor[]> {
  const deadline = Date.now() + 2500;
  do {
    const pins = readPinInfo<PinDescriptor>(element);
    if (pins?.length && pins.every((pin) => Number.isFinite(pin.x) && Number.isFinite(pin.y)))
      return pins;
    await new Promise((resolve) => setTimeout(resolve, 25));
  } while (Date.now() < deadline);
  throw new AgentCircuitError(
    'pins_unavailable',
    `Pin definitions are not ready for ${instance}.`,
    { instance_id: instance },
  );
}

async function mountedElement(id: string, boardKind?: string): Promise<HTMLElement> {
  const deadline = Date.now() + 2500;
  do {
    const element = document.getElementById(id);
    if (
      element &&
      (!boardKind ||
        element.closest('[data-board-kind]')?.getAttribute('data-board-kind') === boardKind)
    )
      return element;
    await new Promise((resolve) => setTimeout(resolve, 25));
  } while (Date.now() < deadline);
  throw new AgentCircuitError('pins_unavailable', `Component ${id} did not mount.`);
}

/** Render the exact canvas board off-canvas, without changing the active board. */
async function previewBoard(board: VlxPayload['boards'][number], host: HTMLElement, roots: Root[]) {
  if (!(board.boardKind in BOARD_KIND_LABELS))
    throw new AgentCircuitError('unsupported_board', `Unknown board ${board.boardKind}.`);
  const { BoardElement } = await import('../components/simulator/BoardElement');
  const container = document.createElement('div');
  container.dataset.boardKind = board.boardKind;
  host.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  const id = `agent-board-${crypto.getRandomValues(new Uint32Array(1))[0]}`;
  root.render(
    createElement(BoardElement, { board: { ...board, id, x: 0, y: 0 } as BoardInstance }),
  );
  return mountedElement(id);
}

async function previewComponent(
  metadata: ComponentMetadata,
  properties: Record<string, unknown>,
  host: HTMLElement,
) {
  if (!customElements.get(metadata.tagName)) {
    await Promise.race([
      customElements.whenDefined(metadata.tagName),
      new Promise((_, reject) =>
        setTimeout(
          () =>
            reject(
              new AgentCircuitError(
                'pins_unavailable',
                `Component definition ${metadata.tagName} is not loaded.`,
              ),
            ),
          2500,
        ),
      ),
    ]);
  }
  const wrapper = document.createElement('div');
  wrapper.className = 'dynamic-component-wrapper';
  wrapper.style.cssText =
    'position:relative;display:inline-block;padding:4px;border:2px solid transparent;transform:none;';
  const element = document.createElement(metadata.tagName);
  element.id = `agent-pad-${crypto.getRandomValues(new Uint32Array(1))[0]}`;
  for (const [key, raw] of Object.entries({
    ...metadata.defaultValues,
    ...properties,
  })) {
    const defaultValue = metadata.defaultValues[key];
    const value =
      typeof defaultValue === 'number'
        ? Number(raw)
        : typeof defaultValue === 'boolean' && typeof raw === 'string'
          ? raw !== 'false'
          : raw;
    (element as unknown as Record<string, unknown>)[key] = value;
  }
  wrapper.appendChild(element);
  host.appendChild(wrapper);
  return element;
}

/** Validate a candidate off-canvas before changing the active circuit. */
export async function prepareAgentCircuit(payload: VlxPayload): Promise<VlxPayload> {
  const candidate = normalizeAgentDocument(payload);
  if (
    !candidate.wires.length &&
    candidate.boards.every((board) =>
      useSimulatorStore
        .getState()
        .boards.some((current) => current.id === board.id && current.boardKind === board.boardKind),
    )
  )
    return candidate;
  const registry = ComponentRegistry.getInstance();
  await registry.load();
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = 'position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;';
  document.body.appendChild(host);
  const roots: Root[] = [];
  const elements = new Map<
    string,
    {
      element: HTMLElement;
      pins: PinDescriptor[];
      x: number;
      y: number;
      rotation: number;
      board?: BoardKind;
    }
  >();
  try {
    const referenced = new Set([
      ...candidate.boards.map((board) => board.id),
      ...candidate.wires.flatMap((wire) => [wire.start.componentId, wire.end.componentId]),
    ]);
    for (const id of referenced) {
      const board = candidate.boards.find((item) => item.id === id);
      if (board) {
        const existing = useSimulatorStore.getState().boards.find((item) => item.id === id);
        const element =
          existing?.boardKind === board.boardKind
            ? await mountedElement(id)
            : await previewBoard(board, host, roots);
        elements.set(id, {
          element,
          pins: await readyPins(element, id),
          x: board.x,
          y: board.y,
          rotation: Number((board as { rotation?: number }).rotation) || 0,
          board: board.boardKind as BoardKind,
        });
        continue;
      }
      const component = candidate.components.find((item) => item.id === id);
      const metadata = component && registry.getById(component.metadataId);
      if (!component || !metadata)
        throw new AgentCircuitError('component_unknown', `Unknown component ${id}.`, {
          instance_id: id,
        });
      const element = await previewComponent(metadata, component.properties, host);
      elements.set(id, {
        element,
        pins: await readyPins(element, id),
        x: component.x + 6,
        y: component.y + 6,
        rotation: Number(component.properties.rotation) || 0,
      });
    }
    for (const wire of candidate.wires) {
      for (const side of ['start', 'end'] as const) {
        const endpoint = wire[side];
        const entry = elements.get(endpoint.componentId)!;
        const pin = resolvePinDescriptor(entry.pins, endpoint.pinName);
        if (!pin)
          throw new AgentCircuitError(
            'pin_invalid',
            `Wire ${wire.id}: ${endpoint.componentId}:${endpoint.pinName} does not exist.`,
            {
              wire_id: wire.id,
              endpoint: side,
              instance_id: endpoint.componentId,
              pin: endpoint.pinName,
              valid_pins: entry.pins.map((item) => item.name),
            },
          );
        const position = calculatePinPosition(
          entry.element.id,
          endpoint.pinName,
          entry.x,
          entry.y,
          entry.rotation,
          entry.board ? boardSize(entry.board) : undefined,
        );
        if (!position)
          throw new AgentCircuitError('pins_unavailable', `Cannot resolve wire ${wire.id}.`);
        // Persist the actual pad name too: the electrical engines use logical
        // pin names, not the coordinates that happen to draw on that pad.
        wire[side] = { ...endpoint, pinName: pin.name, ...position };
      }
    }
    useWireDiagnosticsStore.getState().clear();
    return candidate;
  } catch (error) {
    if (error instanceof AgentCircuitError && error.code === 'pin_invalid') {
      const { wire_id, endpoint, pin } = error.details;
      const active = useSimulatorStore.getState().wires.find((wire) => wire.id === wire_id);
      if ((endpoint === 'start' || endpoint === 'end') && active?.[endpoint].pinName === pin)
        useWireDiagnosticsStore
          .getState()
          .set(String(wire_id), { endpoint, pin: String(pin), message: error.message });
    }
    throw error;
  } finally {
    roots.forEach((root) => root.unmount());
    host.remove();
  }
}

/** Wait for the actual mounted parts, then reconcile their measured geometry. */
export async function settleAgentCircuit(payload: VlxPayload): Promise<void> {
  for (const id of new Set([
    ...payload.boards.map((board) => board.id),
    ...payload.wires.flatMap((wire) => [wire.start.componentId, wire.end.componentId]),
  ])) {
    const element = await mountedElement(
      id,
      payload.boards.find((board) => board.id === id)?.boardKind,
    );
    await readyPins(element, id);
  }
}

/** Pin names come from mounted parts, including property-dependent pinouts. */
export function inspectAgentProject() {
  const sim = useSimulatorStore.getState();
  const registry = ComponentRegistry.getInstance();
  const parts = [
    ...sim.boards.map((board) => ({ id: board.id, type: board.boardKind })),
    ...sim.components.map((component) => ({ id: component.id, type: component.metadataId })),
  ];
  return {
    ok: true,
    available_boards: Object.entries(BOARD_KIND_LABELS).map(([boardKind, name]) => ({
      boardKind,
      name,
      languages: isPiBoardKind(boardKind)
        ? []
        : [
            'arduino',
            ...(BOARD_SUPPORTS_MICROPYTHON.has(boardKind as BoardKind) ? ['micropython'] : []),
            ...(BOARD_SUPPORTS_ESPIDF.has(boardKind as BoardKind) ? ['espidf'] : []),
          ],
    })),
    pinouts: Object.fromEntries(
      parts.map((part) => [
        part.id,
        {
          type: part.type,
          pins: readPinInfo(document.getElementById(part.id))?.map((pin) => pin.name) ?? [],
          defaults: registry.getById(part.type)?.defaultValues ?? {},
        },
      ]),
    ),
  };
}

/** One reference read supplies both metadata and actual pins for a new part. */
export async function describeAgentPart(kind: string, id: string) {
  const registry = ComponentRegistry.getInstance();
  await registry.load();
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-100000px;visibility:hidden;pointer-events:none';
  host.setAttribute('aria-hidden', 'true');
  document.body.appendChild(host);
  const roots: Root[] = [];
  try {
    if (kind === 'board') {
      const element = await previewBoard(
        { id: 'preview', boardKind: id, x: 0, y: 0, activeFileGroupId: 'preview' },
        host,
        roots,
      );
      return { ok: true, pins: (await readyPins(element, id)).map(({ name }) => ({ name })) };
    }
    const metadata = registry.getById(id);
    if (!metadata) throw new AgentCircuitError('component_unknown', `Unknown component ${id}.`);
    const element = await previewComponent(metadata, {}, host);
    const pins = await readyPins(element, id);
    return {
      ok: true,
      pins: pins.map(({ name }) => ({ name })),
      defaults: metadata.defaultValues,
      attrs: metadata.properties,
    };
  } finally {
    roots.forEach((root) => root.unmount());
    host.remove();
  }
}
