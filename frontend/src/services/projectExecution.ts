/** The agent and toolbar share the same verification, build and Run entry point. */
import { getBoardSimulator, useSimulatorStore } from '../store/useSimulatorStore';
import { useCompileLogsStore } from '../store/useCompileLogsStore';
import { isPiBoardKind, isStm32BoardKind } from '../types/board';
import { isEsp32Family } from '../types/boardOptions';
import { boardGateVerdict } from '../lib/proBoardGate';
import {
  beginBoardExecution,
  boardExecutionState,
  updateBoardExecution,
} from '../simulation/boardExecutionState';

let executor: (() => Promise<void>) | undefined;
let inFlight = false;
let cancel: (() => void) | undefined;
let generation = 0;
const clocks = new WeakMap<object, { run: number | undefined; value: number }>();

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

/** Pollable by observe_project after a long backend boot, including failures. */
export function projectExecutionStatus(
  boardId = useSimulatorStore.getState().activeBoardId,
): Record<string, unknown> {
  const board = useSimulatorStore.getState().boards.find((item) => item.id === boardId);
  if (!board)
    return {
      ok: false,
      state: 'stopped',
      confirmed: false,
      error: { code: 'board_unknown', message: 'No active board is available to run.' },
    };
  const execution = boardExecutionState(board.id);
  const result = {
    board_id: board.id,
    board: board.boardKind,
    compiled:
      board.languageMode !== 'micropython' &&
      !isPiBoardKind(board.boardKind) &&
      !!board.compiledProgram,
    firmware_loaded: !!board.compiledProgram,
    language_mode: board.languageMode ?? 'arduino',
    elapsed_ms: execution ? Date.now() - execution.startedAt : 0,
  };
  if (execution?.state === 'error')
    return {
      ...result,
      ok: false,
      state: 'error',
      confirmed: false,
      error: {
        code: execution.code ?? 'engine_error',
        message: execution.message ?? 'The simulation failed.',
      },
    };
  if (execution?.state === 'completed')
    return {
      ...result,
      ok: true,
      state: 'completed',
      confirmed: true,
      evidence: execution.evidence,
    };
  if (execution?.state === 'stopped')
    return { ...result, ok: true, state: 'stopped', confirmed: false };
  const engine = getBoardSimulator(board.id) as
    | { isRunning?: () => boolean; getGuestMicros?: () => number }
    | undefined;
  // Remote shims' isRunning means socket connected. Only their engine event
  // (or an in-browser engine's advancing clock) confirms actual execution.
  const remote =
    isPiBoardKind(board.boardKind) ||
    isStm32BoardKind(board.boardKind) ||
    isEsp32Family(board.boardKind);
  const nativeRunning = !remote && engine?.isRunning?.() === true;
  const acknowledged = execution?.state === 'running';
  const clock = engine?.getGuestMicros?.() ?? -1;
  const previousClock = engine && clocks.get(engine);
  const clockRunning =
    remote &&
    clock >= 0 &&
    !!previousClock &&
    previousClock.value >= 0 &&
    previousClock.run === execution?.run &&
    clock > previousClock.value;
  if (engine) clocks.set(engine, { run: execution?.run, value: clock });
  if (clockRunning) updateBoardExecution(board.id, 'running', { evidence: 'guest_clock_advanced' });
  if (board.running && (nativeRunning || acknowledged || clockRunning))
    return {
      ...result,
      ok: true,
      state: 'running',
      confirmed: true,
      evidence: acknowledged
        ? execution.evidence
        : nativeRunning
          ? 'engine_running'
          : 'guest_clock_advanced',
    };
  const pending = execution && ['compiling', 'starting', 'booting'].includes(execution.state);
  if (pending && (board.running || execution.state === 'compiling')) {
    if (execution.state !== 'compiling' && result.elapsed_ms > 120000)
      return {
        ...result,
        ok: false,
        state: 'error',
        confirmed: false,
        error: {
          code: 'startup_timeout',
          message:
            'The engine did not confirm startup within two minutes. Inspect diagnostics before retrying.',
        },
      };
    return {
      ...result,
      ok: true,
      state: execution.state,
      confirmed: false,
      next_action:
        'Call observe_project with duration_ms=15000 to check startup. Do not restart the build.',
    };
  }
  return { ...result, ok: true, state: board.running ? 'starting' : 'stopped', confirmed: false };
}

export async function executeAgentProjectRun(): Promise<Record<string, unknown>> {
  if (!executor) throw new Error('The editor is not ready to run a project.');
  if (inFlight) throw new Error('A simulation command is already running.');
  const sim = useSimulatorStore.getState();
  const board = sim.boards.find((item) => item.id === sim.activeBoardId);
  if (!board) return projectExecutionStatus();
  const verdict = boardGateVerdict(board.boardKind, 'run');
  if (verdict.decision === 'block')
    return {
      ok: false,
      state: 'blocked',
      confirmed: false,
      error: {
        code: 'board_access_denied',
        message: verdict.description ?? 'This installation does not allow running this board.',
      },
    };
  inFlight = true;
  const started = generation;
  const since = Date.now();
  try {
    if (board.running) sim.stopBoard(board.id);
    sim.clearBoardSerialOutput?.(board.id);
    beginBoardExecution(board.id, 'compiling');
    await executor();
    const deadline = Date.now() + 8000;
    for (;;) {
      if (started !== generation) {
        useSimulatorStore.getState().stopBoard(board.id);
        return {
          ok: false,
          state: 'stopped',
          confirmed: false,
          error: { code: 'interrupted', message: 'Agent execution was stopped.' },
        };
      }
      const current = useSimulatorStore.getState().boards.find((item) => item.id === board.id);
      if (!current || current.boardKind !== board.boardKind)
        return {
          ok: false,
          state: 'blocked',
          confirmed: false,
          error: { code: 'revision_conflict', message: 'The board changed during execution.' },
        };
      const status = projectExecutionStatus(board.id);
      const logs = useCompileLogsStore
        .getState()
        .logs.filter(
          (entry) =>
            (!entry.target || entry.target.id === board.id) && entry.timestamp.getTime() >= since,
        )
        .slice(-25);
      const output = logs
        .map((entry) => `${entry.type}: ${entry.message}`)
        .join('\n')
        .slice(-8000);
      if (status.state === 'error' || status.confirmed) return { ...status, logs: output };
      if (!current.running || status.state === 'compiling') {
        const failure = logs.find((entry) => entry.type === 'error');
        const error = {
          code: failure ? 'compilation_failed' : 'simulation_not_started',
          message:
            failure?.message ??
            'The editor did not start the simulation. Check the circuit verification dialog or installation requirements.',
        };
        updateBoardExecution(board.id, 'error', error);
        return { ...status, ok: false, state: 'blocked', confirmed: false, error, logs: output };
      }
      // Native engines answer immediately. Backend/overlay engines may need
      // time; returning booting is an honest, pollable result, not a failure.
      if (Date.now() >= deadline || status.state === 'stopped') return { ...status, logs: output };
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  } catch (error) {
    if (started !== generation) {
      useSimulatorStore.getState().stopBoard(board.id);
      return {
        ok: false,
        state: 'stopped',
        confirmed: false,
        error: { code: 'interrupted', message: 'Agent execution was stopped.' },
      };
    }
    const message = error instanceof Error ? error.message : String(error);
    updateBoardExecution(board.id, 'error', { code: 'execution_failed', message });
    return {
      ok: false,
      state: 'error',
      confirmed: false,
      error: { code: 'execution_failed', message },
    };
  } finally {
    inFlight = false;
  }
}
