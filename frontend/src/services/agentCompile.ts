/** Chat compilation uses the same app compiler and owner policy as the toolbar. */
import { useSimulatorStore } from '../store/useSimulatorStore';
import { useCompileLogsStore } from '../store/useCompileLogsStore';
import { compileBoardForFlash, collectSketchFilesForBoard } from '../utils/boardCompile';
import { boardGateVerdict } from '../lib/proBoardGate';
import { agentValueEqual } from './agentService';
import type { BoardInstance } from '../types/board';

interface Build {
  boardId: string;
  input: unknown;
  cancelled: boolean;
  result: Record<string, unknown>;
  done: Promise<void>;
}
let active: Build | undefined;

function inputs(board: BoardInstance): unknown {
  return structuredClone({
    board: board.boardKind,
    language: board.languageMode,
    options: board.boardOptions,
    libraries: board.libraries,
    spiffs: board.spiffsFiles,
    files: collectSketchFilesForBoard(board),
  });
}
export function cancelAgentCompile(): void {
  if (active) active.cancelled = true;
  active = undefined;
}
export async function executeAgentCompile(
  waitSeconds = 20,
  restart = false,
): Promise<Record<string, unknown>> {
  const sim = useSimulatorStore.getState();
  const board = sim.boards.find((b) => b.id === sim.activeBoardId);
  if (!board)
    return {
      ok: false,
      state: 'error',
      confirmed: false,
      error: { code: 'board_unknown', message: 'Select a board before compiling.' },
    };
  const input = inputs(board);
  if (
    !active ||
    active.cancelled ||
    active.boardId !== board.id ||
    !agentValueEqual(active.input, input) ||
    (restart && active.result.state !== 'compiling')
  ) {
    const verdict = boardGateVerdict(board.boardKind, 'run');
    if (verdict.decision === 'block')
      return {
        ok: false,
        state: 'blocked',
        confirmed: false,
        error: {
          code: 'board_access_denied',
          message: verdict.description ?? 'Compilation is unavailable for this board.',
        },
      };
    if (active) active.cancelled = true;
    const record: Build = {
      boardId: board.id,
      input,
      cancelled: false,
      result: { ok: true, state: 'compiling', compiled: false, confirmed: false },
      done: Promise.resolve(),
    };
    active = record;
    const lines: string[] = [];
    record.done = (async () => {
      const result = await compileBoardForFlash(
        board,
        (line) => {
          lines.push(line);
          useCompileLogsStore.getState().appendLogs([
            {
              timestamp: new Date(),
              type: 'info',
              message: line,
              target: { id: board.id, label: board.name ?? board.boardKind, kind: 'board' },
            },
          ]);
        },
        { record: false },
      );
      const current = useSimulatorStore.getState().boards.find((b) => b.id === board.id);
      const stale = record.cancelled || !current || !agentValueEqual(input, inputs(current));
      if (stale) {
        record.result = {
          ok: false,
          state: 'stale',
          compiled: false,
          confirmed: false,
          error: {
            code: 'execution_changed',
            message:
              'Build inputs changed or execution was cancelled. Run the current project again.',
          },
        };
        return;
      }
      if (result.ok) {
        useSimulatorStore
          .getState()
          .compileBoardProgram(board.id, result.program, { uf2: result.uf2 });
        record.result = {
          ok: true,
          state: 'compiled',
          compiled: true,
          confirmed: false,
          compilation: { success: true, source: 'application compiler' },
          elapsed_ms: result.elapsedMs,
        };
      } else {
        record.result = {
          ok: false,
          state: 'error',
          compiled: false,
          confirmed: false,
          compilation: { success: false, source: 'application compiler' },
          error: { code: 'compilation_failed', message: result.error },
          elapsed_ms: result.elapsedMs,
        };
      }
      record.result.logs = lines.join('\n').slice(-8000);
    })().catch((error: unknown) => {
      record.result = {
        ok: false,
        state: 'error',
        compiled: false,
        confirmed: false,
        error: {
          code: 'compilation_failed',
          message: error instanceof Error ? error.message : String(error),
        },
      };
    });
  }
  const record = active;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      record.done,
      new Promise<void>((resolve) => {
        timer = setTimeout(resolve, Math.max(0, Math.min(waitSeconds, 60)) * 1000);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
  return {
    ...record.result,
    board_id: board.id,
    board: board.boardKind,
    behavior_verified: false,
    ...(record.result.state === 'compiling'
      ? { next_action: 'Call run() again to read this build result. Do not restart.' }
      : {}),
  };
}
