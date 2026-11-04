import { describe, expect, it } from 'vitest';
import { reduceAgentEvent } from '../services/agentEvents';
import { formatAgentToolText, splitAgentThinking } from '../services/agentText';
import type { AgentEvent, AgentTurn } from '../services/agentService';

describe('agent stream rendering', () => {
  it('shortens persisted read-file paths including a path to the workspace itself', () => {
    const root = `app/data/agent/${'a'.repeat(64)}/sessions/${'b'.repeat(32)}/work`;
    expect(formatAgentToolText(`<path>${root}</path>`)).toBe('File: .');
    expect(formatAgentToolText(`<path>/${root}/group-1/sketch.ino</path>`)).toBe(
      'File: group-1/sketch.ino',
    );
    expect(formatAgentToolText(`Read ${root}/group-2/user_hook.h`)).toBe(
      'Read group-2/user_hook.h',
    );
    expect(formatAgentToolText('group-1/sketch.ino')).toBe('group-1/sketch.ino');
    expect(formatAgentToolText(`${root}space`)).toBe(`${root}space`);
    expect(formatAgentToolText('XML source:\n<path>literal</path>')).toBe(
      'XML source:\n<path>literal</path>',
    );
  });
  it('keeps thinking separate through every possible split of think tags', () => {
    const text = '<think>Inspect pins first.</think>Connected.';
    for (let split = 0; split <= text.length; split++) {
      const partial = splitAgentThinking(text.slice(0, split));
      expect(partial.answer).not.toContain('Inspect pins');
      expect(partial.answer).not.toContain('<thi');
      expect(splitAgentThinking(text.slice(0, split) + text.slice(split))).toEqual({
        thinking: 'Inspect pins first.',
        answer: 'Connected.',
      });
    }
  });

  it('preserves literal tags in code examples', () => {
    const input = 'Example:\n```xml\n<think>literal</think>\n```\nDone.';
    expect(splitAgentThinking(input)).toEqual({ answer: input, thinking: '' });
  });

  it('tracks repeated tools independently and retains completed and failed steps', () => {
    const events: AgentEvent[] = [
      {
        event_id: 1,
        turn_id: 'turn',
        type: 'turn.started',
        timestamp: 100,
        payload: { message_index: 2 },
      },
      {
        event_id: 2,
        turn_id: 'turn',
        type: 'reasoning.delta',
        timestamp: 110,
        payload: { part_id: 'reasoning', text: 'Check endpoints.' },
      },
      {
        event_id: 3,
        turn_id: 'turn',
        type: 'tool.state',
        timestamp: 200,
        payload: { call_id: 'one', name: 'connect_pins', status: 'running' },
      },
      {
        event_id: 4,
        turn_id: 'turn',
        type: 'tool.state',
        timestamp: 300,
        payload: { call_id: 'one', name: 'connect_pins', status: 'error', summary: 'Unknown pin' },
      },
      {
        event_id: 5,
        turn_id: 'turn',
        type: 'tool.state',
        timestamp: 400,
        payload: { call_id: 'two', name: 'connect_pins', status: 'running' },
      },
      {
        event_id: 6,
        turn_id: 'turn',
        type: 'tool.state',
        timestamp: 600,
        payload: { call_id: 'two', name: 'connect_pins', status: 'completed' },
      },
      { event_id: 7, turn_id: 'turn', type: 'turn.completed', timestamp: 700, payload: {} },
    ];
    const turns = events.reduce(reduceAgentEvent, [] as AgentTurn[]);
    expect(turns[0].message_index).toBe(2);
    expect(turns[0].reasoning.reasoning).toBe('Check endpoints.');
    expect(turns[0].steps.map((step) => [step.id, step.status, step.duration_ms])).toEqual([
      ['one', 'error', 100],
      ['two', 'completed', 200],
    ]);
    expect(turns[0].status).toBe('completed');
    expect(JSON.parse(JSON.stringify(turns))[0].steps).toHaveLength(2);
  });
});
