/** Runtime acknowledgements, separate from the UI's optimistic running flag. */
export type BoardExecutionPhase =
  | 'compiling'
  | 'starting'
  | 'booting'
  | 'running'
  | 'completed'
  | 'stopped'
  | 'error';
export interface BoardExecutionState {
  run: number;
  state: BoardExecutionPhase;
  startedAt: number;
  code?: string;
  message?: string;
  evidence?: string;
}

let sequence = 0;
const states = new Map<string, BoardExecutionState>();
export function beginBoardExecution(id: string, state: BoardExecutionPhase = 'starting'): number {
  const run = ++sequence;
  states.set(id, { run, state, startedAt: Date.now() });
  return run;
}
export function boardExecutionState(id: string): BoardExecutionState | undefined {
  return states.get(id);
}
export function forgetBoardExecution(id: string): void {
  states.delete(id);
}
export function updateBoardExecution(
  id: string,
  state: BoardExecutionPhase,
  detail: Partial<Pick<BoardExecutionState, 'code' | 'message' | 'evidence'>> = {},
  run = states.get(id)?.run,
): void {
  const current = states.get(id);
  if (!current || current.run !== run || ['error', 'stopped', 'completed'].includes(current.state))
    return;
  states.set(id, { ...current, ...detail, state });
}

/** This is a backend/engine acknowledgement, never a WebSocket-open event. */
export function acknowledgeBoardEvent(
  id: string,
  event: string,
  data: Record<string, unknown>,
  run: number,
): void {
  if (event === 'booting' || event === 'reboot') updateBoardExecution(id, 'booting', {}, run);
  if (event === 'booted' || event === 'started' || event === 'running')
    updateBoardExecution(id, 'running', { evidence: 'engine_acknowledgement' }, run);
  if (event === 'crash')
    updateBoardExecution(
      id,
      'error',
      {
        code: 'engine_crashed',
        message: String(data.reason ?? data.message ?? 'The simulation engine crashed.'),
      },
      run,
    );
  if (event === 'exited' || event === 'stopped')
    updateBoardExecution(id, 'stopped', { message: 'The simulation engine stopped.' }, run);
}
