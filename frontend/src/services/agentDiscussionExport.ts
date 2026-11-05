import type { AgentSession, AgentStep, AgentTurn } from './agentService';
import { splitAgentThinking } from './agentText';

export interface AgentDiscussionExport {
  format: 'velxio-agent-discussion';
  version: 1;
  exportedAt: string;
  model: string;
  session: {
    id: string;
    revision: string;
    editor_revision?: string;
    sequence: number;
    busy: boolean;
  };
  messages: Array<{ role: 'user' | 'assistant'; content: string }>;
  turns: Array<{
    id: string;
    message_index: number;
    status: string;
    phase: string;
    started_at?: number;
    steps: Array<{
      id: string;
      name: string;
      title: string;
      status: AgentStep['status'];
      result_state?: string;
      confirmed?: boolean;
      duration_ms?: number;
      started_at?: number;
      summary?: string;
    }>;
  }>;
  draft?: string;
}

function answerOnly(text: string): string {
  return splitAgentThinking(text).answer;
}

function stepExport(step: AgentStep) {
  return {
    id: step.id,
    name: step.name,
    title: step.title,
    status: step.status,
    ...(step.result_state !== undefined ? { result_state: step.result_state } : {}),
    ...(step.confirmed !== undefined ? { confirmed: step.confirmed } : {}),
    ...(step.duration_ms !== undefined ? { duration_ms: step.duration_ms } : {}),
    ...(step.started_at !== undefined ? { started_at: step.started_at } : {}),
    ...(step.summary !== undefined ? { summary: step.summary } : {}),
  };
}

function turnExport(turn: AgentTurn) {
  // `reasoning` is intentionally omitted: it dominates the payload and is not
  // needed to reproduce or review the agent's actual actions and results.
  return {
    id: turn.id,
    message_index: turn.message_index,
    status: turn.status,
    phase: turn.phase,
    ...(turn.started_at !== undefined ? { started_at: turn.started_at } : {}),
    steps: (turn.steps ?? []).map(stepExport),
  };
}

export function buildAgentDiscussionExport(
  session: AgentSession,
  model: string,
  now = new Date(),
  draft = '',
): AgentDiscussionExport {
  const payload: AgentDiscussionExport = {
    format: 'velxio-agent-discussion',
    version: 1,
    exportedAt: now.toISOString(),
    model,
    session: {
      id: session.id,
      revision: session.revision,
      ...(session.editor_revision !== undefined
        ? { editor_revision: session.editor_revision }
        : {}),
      sequence: session.sequence,
      busy: session.busy,
    },
    messages: session.messages.map((message) => ({
      role: message.role,
      content: message.role === 'assistant' ? answerOnly(message.content) : message.content,
    })),
    turns: (session.turns ?? []).map(turnExport),
  };
  const answer = draft.trim() ? answerOnly(draft) : '';
  if (answer) payload.draft = answer;
  return payload;
}

export function agentDiscussionFilename(model: string, now = new Date()): string {
  const stamp = now.toISOString().replace(/[:.]/g, '-');
  const safe = (model || 'agent')
    .replace(/[^a-z0-9._-]+/gi, '-')
    .replace(/^[.-]+|[.-]+$/g, '')
    .slice(0, 60);
  return `velxio-agent-discussion-${safe || 'agent'}-${stamp}.json`;
}
