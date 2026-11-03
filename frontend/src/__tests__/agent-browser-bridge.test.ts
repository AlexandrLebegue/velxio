import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';

const fixture = vi.hoisted(() => {
  const board = {
    id: 'uno',
    boardKind: 'arduino-uno',
    x: 0,
    y: 0,
    activeFileGroupId: 'sketch',
    running: false,
    compiledProgram: null as string | null,
  };
  return {
    board,
    boards: [board],
    files: { sketch: [{ name: 'sketch.ino', content: 'void setup() {}\nvoid loop() {}' }] },
    engineRunning: false,
    projectId: 'saved-project',
  };
});

const stopBoard = vi.fn(() => {
  fixture.board.running = false;
  fixture.engineRunning = false;
});
vi.mock('../store/useSimulatorStore', () => ({
  getBoardSimulator: () => ({ isRunning: () => fixture.engineRunning }),
  keepWireShapes: vi.fn(),
  useSimulatorStore: {
    getState: () => ({
      boards: fixture.boards,
      activeBoardId: 'uno',
      components: [],
      wires: [],
      serialOutput: '42\n',
      stopBoard,
      updateBoard: (_id: string, value: object) => Object.assign(fixture.board, value),
      setComponents: vi.fn(),
      setWires: vi.fn(),
    }),
  },
}));
vi.mock('../store/useEditorStore', () => ({
  useEditorStore: {
    getState: () => ({
      replaceFileGroups: (files: typeof fixture.files) => {
        fixture.files = files;
      },
    }),
  },
}));
vi.mock('../store/useCompileLogsStore', () => ({
  useCompileLogsStore: { getState: () => ({ logs: [] }) },
}));
vi.mock('../utils/vlxFile', () => ({
  buildVlxPayload: () => ({
    format: 'velxio-project',
    version: 1,
    boards: fixture.boards.map((board) => ({
      id: board.id,
      boardKind: board.boardKind,
      x: board.x,
      y: board.y,
      activeFileGroupId: board.activeFileGroupId,
    })),
    fileGroups: fixture.files,
    components: [],
    wires: [],
    activeBoardId: 'uno',
  }),
}));

import { projectRevision } from '../services/agentService';
import { handleAgentBrowserCommand, snapshotForAgent } from '../services/agentBrowserBridge';
import {
  cancelAgentProjectRun,
  executeAgentProjectRun,
  registerProjectExecutor,
} from '../services/projectExecution';

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  vi.stubGlobal('requestAnimationFrame', (callback: () => void) => {
    callback();
    return 1;
  });
  fixture.board.running = false;
  fixture.board.compiledProgram = null;
  fixture.board.boardKind = 'arduino-uno';
  fixture.engineRunning = false;
  fixture.files = { sketch: [{ name: 'sketch.ino', content: 'void setup() {}\nvoid loop() {}' }] };
  vi.clearAllMocks();
});

describe('project-scoped agent bridge', () => {
  it('uses the same canonical revision as Python', async () => {
    expect(await projectRevision()).toBe(
      'a5233c4ff1d8e8cedaa4231db43de1d27886dde0e83bb68be1a7a36d7ade9170',
    );
  });

  it('preserves manual edits and never executes a stale agent snapshot', async () => {
    const revision = await projectRevision();
    const document = structuredClone(snapshotForAgent());
    document.fileGroups.sketch[0].content = 'agent edit';
    fixture.files.sketch[0].content = 'manual edit';
    const executor = vi.fn();
    const dispose = registerProjectExecutor(executor);
    const result = await handleAgentBrowserCommand({
      command_id: 'conflict',
      action: 'run',
      expected_revision: revision,
      document,
      revision: await projectRevision(document),
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatchObject({ code: 'revision_conflict' });
    expect(fixture.files.sketch[0].content).toBe('manual edit');
    expect(executor).not.toHaveBeenCalled();
    dispose();
  });

  it('applies code, confirms engine startup, and deduplicates repeated commands', async () => {
    const expected = await projectRevision();
    const document = structuredClone(snapshotForAgent());
    document.fileGroups.sketch[0].content = 'void setup() {}\nvoid loop() { delay(50); }';
    const next = await projectRevision(document);
    const executor = vi.fn(async () => {
      fixture.board.compiledProgram = 'firmware';
      fixture.board.running = true;
      fixture.engineRunning = true;
    });
    const dispose = registerProjectExecutor(executor);
    const command = {
      command_id: 'one-run',
      action: 'run',
      expected_revision: expected,
      document,
      revision: next,
    };
    const [first, second] = await Promise.all([
      handleAgentBrowserCommand(command),
      handleAgentBrowserCommand(command),
    ]);
    expect(first).toEqual(second);
    expect(first).toMatchObject({ ok: true, state: 'running', applied_revision: next });
    expect(executor).toHaveBeenCalledTimes(1);
    const observed = await handleAgentBrowserCommand({
      command_id: 'observe',
      action: 'observe',
      expected_revision: next,
      duration_ms: 0,
    });
    expect(observed).toMatchObject({ serial: '42\n', state: 'running' });
    dispose();
  });

  it('does not mistake a board flag or a compiled firmware for actual execution', async () => {
    const dispose = registerProjectExecutor(async () => {
      fixture.board.running = true;
      fixture.board.compiledProgram = 'firmware';
    });
    expect(await executeAgentProjectRun()).toMatchObject({
      ok: false,
      compiled: true,
      state: 'blocked',
    });
    dispose();
  });

  it('stops a pending execution and prevents a late compile from leaving the board running', async () => {
    let finish!: () => void;
    const dispose = registerProjectExecutor(
      () =>
        new Promise<void>((resolve) => {
          finish = () => {
            fixture.board.running = true;
            fixture.engineRunning = true;
            resolve();
          };
        }),
    );
    const running = executeAgentProjectRun();
    cancelAgentProjectRun();
    finish();
    expect(await running).toMatchObject({ ok: false, state: 'stopped' });
    expect(fixture.board.running).toBe(false);
    dispose();
  });
});
