import { getApiBase } from '../lib/apiBase';
import { buildVlxPayload } from '../utils/vlxFile';
import type { VlxPayload } from '../utils/vlxFile';
import { generateUUID } from '../utils/uuid';
import { normalizeAgentDocument } from './agentDocument';

export interface AgentSettings {
  base_url: string;
  model: string;
  api_key?: string;
  clear_api_key?: boolean;
  has_api_key?: boolean;
  available?: boolean;
  max_steps: number;
  max_output_tokens?: number;
  context_window?: number;
  timeout_seconds: number;
}

export interface AgentSession {
  id: string;
  revision: string;
  sequence: number;
  busy: boolean;
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  turns?: AgentTurn[];
}

export interface AgentStep {
  id: string;
  name: string;
  title: string;
  status: 'pending' | 'running' | 'completed' | 'error' | 'cancelled';
  summary?: string;
  result_state?: string;
  confirmed?: boolean;
  duration_ms?: number;
  started_at?: number;
}
export interface AgentTurn {
  id: string;
  message_index: number;
  status: string;
  phase: string;
  started_at?: number;
  reasoning: Record<string, string>;
  steps: AgentStep[];
}

export interface AgentEvent {
  event_id: number;
  type: string;
  payload: Record<string, unknown>;
  turn_id?: string;
  timestamp?: number;
}

let browserId: string | undefined;
export function agentBrowserId(): string {
  return (browserId ??= generateUUID());
}

export class AgentApiError extends Error {
  code: string;
  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

export async function agentRequest<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  const response = await fetch(`${getApiBase()}/agent${path}`, {
    method,
    credentials: 'include',
    ...(data === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  });
  const body = await response.json();
  if (!response.ok)
    throw new AgentApiError(
      body.error?.message ?? body.detail?.[0]?.msg ?? `HTTP ${response.status}`,
      body.error?.code ?? 'request_failed',
    );
  return body as T;
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonical((value as Record<string, unknown>)[key])]),
    );
  }
  return value;
}

/** Same semantic snapshot hash as the backend, independent of export date. */
export async function projectRevision(payload: VlxPayload = buildVlxPayload()): Promise<string> {
  // WebCrypto is unavailable when a self-hosted instance is opened over LAN HTTP.
  if (!globalThis.crypto?.subtle)
    return (await agentRequest<{ revision: string }>('/revision', 'POST', { document: payload }))
      .revision;
  const value = JSON.parse(JSON.stringify(normalizeAgentDocument(payload))) as Record<
    string,
    unknown
  >;
  delete value.exportedAt;
  delete value.name;
  for (const board of (value.boards ?? []) as Array<Record<string, unknown>>)
    delete board.serialBaudRate;
  for (const wire of (value.wires ?? []) as Array<Record<string, unknown>>) {
    delete wire.signalType;
    for (const endpoint of [wire.start, wire.end] as Array<Record<string, unknown>>) {
      delete endpoint.x;
      delete endpoint.y;
    }
  }
  for (const component of (value.components ?? []) as Array<{
    metadataId: string;
    properties: Record<string, unknown>;
  }>) {
    if (['led', 'rgb-led', 'buzzer', 'relay-module'].includes(component.metadataId)) {
      delete component.properties.state;
      if (typeof component.properties.value === 'boolean') delete component.properties.value;
    }
  }
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(JSON.stringify(canonical(value))),
  );
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function connectAgentEvents(
  sessionId: string,
  after: number,
  onEvent: (event: AgentEvent) => void,
  onResync: () => void,
  onConnection: (connected: boolean) => void,
): () => void {
  const source = new EventSource(
    `${getApiBase()}/agent/sessions/${sessionId}/events?after=${after}&browser_id=${agentBrowserId()}`,
    { withCredentials: true },
  );
  source.onopen = () => onConnection(true);
  source.onerror = () => onConnection(false);
  source.onmessage = (message) => onEvent(JSON.parse(message.data) as AgentEvent);
  source.addEventListener('resync', onResync);
  return () => source.close();
}
