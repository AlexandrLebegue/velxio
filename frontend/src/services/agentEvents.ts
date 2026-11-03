import type { AgentEvent, AgentTurn } from './agentService';

export function reduceAgentEvent(previous: AgentTurn[], event: AgentEvent): AgentTurn[] {
  const id = event.turn_id ?? String(event.payload.turn_id ?? '');
  if (!id) return previous;
  const turns = structuredClone(previous);
  let turn = turns.find((item) => item.id === id);
  if (!turn && event.type === 'turn.started') {
    turn = {
      id,
      message_index: Number(event.payload.message_index ?? 0),
      status: 'running',
      phase: 'starting',
      reasoning: {},
      steps: [],
      started_at: event.timestamp,
    };
    turns.push(turn);
  }
  if (!turn) return previous;
  const value = event.payload;
  if (event.type === 'turn.phase') turn.phase = String(value.phase);
  if (
    event.type === 'reasoning.delta' ||
    (event.type === 'part.updated' && value.kind === 'reasoning')
  ) {
    const part = String(value.part_id);
    turn.reasoning[part] = (
      event.type === 'reasoning.delta'
        ? (turn.reasoning[part] ?? '') + String(value.text ?? '')
        : String(value.text ?? '')
    ).slice(-16000);
  }
  if (event.type === 'tool.state') {
    const call = String(value.call_id);
    let step = turn.steps.find((item) => item.id === call);
    if (!step) {
      step = {
        id: call,
        name: String(value.name),
        title: String(value.title ?? value.name),
        status: 'pending',
        started_at: event.timestamp,
      };
      turn.steps.push(step);
      turn.steps = turn.steps.slice(-100);
    }
    Object.assign(step, value);
    if (['completed', 'error', 'cancelled'].includes(step.status))
      step.duration_ms = Math.max(
        0,
        (event.timestamp ?? 0) - (step.started_at ?? event.timestamp ?? 0),
      );
  }
  if (['turn.completed', 'turn.interrupted', 'error'].includes(event.type)) {
    turn.status =
      event.type === 'turn.completed'
        ? 'completed'
        : event.type === 'error'
          ? 'error'
          : 'cancelled';
    for (const step of turn.steps)
      if (['pending', 'running'].includes(step.status))
        step.status = turn.status === 'error' ? 'error' : 'cancelled';
  }
  return turns.slice(-30);
}
