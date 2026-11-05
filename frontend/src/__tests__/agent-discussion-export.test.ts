import { describe, expect, it } from 'vitest';
import {
  agentDiscussionFilename,
  buildAgentDiscussionExport,
} from '../services/agentDiscussionExport';
import type { AgentSession } from '../services/agentService';

function session(): AgentSession {
  return {
    id: 'session-1',
    revision: 'rev-1',
    editor_revision: 'editor-1',
    sequence: 7,
    busy: false,
    messages: [
      { role: 'user', content: 'Add a servo and compile.' },
      {
        role: 'assistant',
        content: '<think>Use pin 9 and angle 120.</think>Done: servo at 120°.',
      },
    ],
    turns: [
      {
        id: 'turn-1',
        message_index: 0,
        status: 'completed',
        phase: 'working',
        started_at: 1000,
        reasoning: { reasoning: 'Private chain of thought that must not be exported.' },
        steps: [
          {
            id: 'call-1',
            name: 'connect',
            title: 'Connect wires',
            status: 'completed',
            summary: '{"connections":3,"validated":true}',
            result_state: 'compiled',
            confirmed: true,
            duration_ms: 1250,
            started_at: 1100,
          },
        ],
      },
    ],
  };
}

describe('agent discussion export', () => {
  it('keeps messages, actions and results while removing thinking', () => {
    const payload = buildAgentDiscussionExport(
      session(),
      'qwen3.8-27b',
      new Date('2026-11-05T12:00:00.000Z'),
      '<think>Draft reasoning.</think>Compiling now.',
    );
    expect(payload.messages[1].content).toBe('Done: servo at 120°.');
    expect(payload.draft).toBe('Compiling now.');
    expect(payload.turns[0].steps[0]).toMatchObject({
      name: 'connect',
      status: 'completed',
      summary: '{"connections":3,"validated":true}',
      result_state: 'compiled',
      confirmed: true,
      duration_ms: 1250,
    });
    expect(payload.turns[0]).not.toHaveProperty('reasoning');
    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain('Private chain of thought');
    expect(serialized).not.toContain('Draft reasoning');
    expect(serialized).not.toContain('<think>');
  });

  it('produces a filesystem-safe deterministic filename', () => {
    expect(agentDiscussionFilename('qwen3.8-27b', new Date('2026-11-05T12:00:00.000Z'))).toBe(
      'velxio-agent-discussion-qwen3.8-27b-2026-11-05T12-00-00-000Z.json',
    );
    expect(agentDiscussionFilename('../model name')).toMatch(
      /^velxio-agent-discussion-model-name-\d{4}-\d{2}-\d{2}T/,
    );
  });
});
