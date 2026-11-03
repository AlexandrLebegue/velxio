/** Async entry point shared with the existing toolbar; never simulates a click. */
import { getBoardSimulator, useSimulatorStore } from '../store/useSimulatorStore';
import { useCompileLogsStore } from '../store/useCompileLogsStore';

let executor: (() => Promise<void>) | undefined;
let inFlight = false;
let cancel: (() => void) | undefined;
let generation = 0;

export function registerProjectExecutor(
  handler: () => Promise<void>,
  onCancel?: () => void,
): () => void {
  executor = handler;
  cancel = onCancel;
  return () => {
    if (executor === handler) {
      executor = undefined;
      cancel = undefined;
    }
  };
}

export function cancelAgentProjectRun(): void {
  generation++;
  cancel?.();
}

export async function executeAgentProjectRun(): Promise<Record<string, unknown>> {
  if (!executor) throw new Error('The editor is not ready to run a project.');
  if (inFlight) throw new Error('A simulation command is already running.');
  const sim = useSimulatorStore.getState();
  const board = sim.boards.find((item) => item.id === sim.activeBoardId);
  if (
    !board ||
    !['arduino-uno', 'arduino-nano', 'arduino-mega', 'attiny85'].includes(board.boardKind)
  ) {
    return {
      ok: false,
      state: 'blocked',
      error: {
        code: 'unsupported_board',
        message:
          'Agent-controlled execution currently supports AVR boards. Other boards can still be edited and run manually.',
      },
    };
  }
  inFlight = true;
  const started = generation;
  try {
    if (board.running) sim.stopBoard(board.id);
    await executor();
    if (started !== generation) {
      useSimulatorStore.getState().stopBoard(board.id);
      return {
        ok: false,
        state: 'stopped',
        error: { code: 'interrupted', message: 'Agent execution was stopped.' },
      };
    }
    const current = useSimulatorStore.getState().boards.find((item) => item.id === board.id);
    const engine = getBoardSimulator(board.id) as { isRunning?: () => boolean } | undefined;
    const running = !!current?.running && engine?.isRunning?.() === true;
    const logs = useCompileLogsStore
      .getState()
      .logs.slice(-25)
      .map((entry) => `${entry.type}: ${entry.message}`)
      .join('\n')
      .slice(-8000);
    return {
      ok: running,
      state: running ? 'running' : 'blocked',
      compiled: !!current?.compiledProgram,
      logs,
      ...(!running
        ? {
            error: {
              code: 'simulation_not_started',
              message:
                'The editor did not start the simulation. Check compiler diagnostics or the circuit verification dialog.',
            },
          }
        : {}),
    };
  } finally {
    inFlight = false;
  }
}
