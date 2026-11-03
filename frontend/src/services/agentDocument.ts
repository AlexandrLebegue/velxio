import type { VlxPayload } from '../utils/vlxFile';

export const DEFAULT_AGENT_WIRE_COLOR = '#00c853';

/** The same defaults are used before hashing on the server and in the editor. */
export function normalizeAgentDocument(payload: VlxPayload): VlxPayload {
  const value = structuredClone(payload);
  value.wires = value.wires.map((wire) => ({
    ...wire,
    color: wire.color ?? DEFAULT_AGENT_WIRE_COLOR,
    waypoints: wire.waypoints ?? [],
  }));
  return value;
}
