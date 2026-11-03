import { ComponentRegistry } from './ComponentRegistry';
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

/** Validate a candidate off-canvas before changing the active circuit. */
export async function prepareAgentCircuit(payload: VlxPayload): Promise<VlxPayload> {
  const candidate = normalizeAgentDocument(payload);
  if (!candidate.wires.length) return candidate;
  const registry = ComponentRegistry.getInstance();
  await registry.load();
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  host.style.cssText = 'position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;';
  document.body.appendChild(host);
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
    const referenced = new Set(
      candidate.wires.flatMap((wire) => [wire.start.componentId, wire.end.componentId]),
    );
    for (const id of referenced) {
      const board = candidate.boards.find((item) => item.id === id);
      if (board) {
        const element = document.getElementById(id);
        if (!element)
          throw new AgentCircuitError('pins_unavailable', `Board ${id} is not mounted.`, {
            instance_id: id,
          });
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
        ...component.properties,
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
    host.remove();
  }
}

/** Wait for the actual mounted parts, then reconcile their measured geometry. */
export async function settleAgentCircuit(payload: VlxPayload): Promise<void> {
  for (const id of new Set(
    payload.wires.flatMap((wire) => [wire.start.componentId, wire.end.componentId]),
  )) {
    const deadline = Date.now() + 2500;
    let element = document.getElementById(id);
    while (!element && Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 25));
      element = document.getElementById(id);
    }
    if (!element) throw new AgentCircuitError('pins_unavailable', `Component ${id} did not mount.`);
    await readyPins(element, id);
  }
}
