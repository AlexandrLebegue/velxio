import { beforeEach, describe, expect, it, vi } from 'vitest';
const fixture = vi.hoisted(() => ({
  board: {
    id: 'uno',
    boardKind: 'arduino-uno',
    name: 'Arduino',
    activeFileGroupId: 'g',
    libraries: ['Servo'],
  },
  files: [{ name: 'sketch.ino', content: 'void setup() {}\nvoid loop() {}\n' }],
  record: vi.fn(),
  compile: vi.fn(),
}));
vi.mock('../store/useSimulatorStore', () => ({
  useSimulatorStore: {
    getState: () => ({
      boards: [fixture.board],
      activeBoardId: 'uno',
      compileBoardProgram: fixture.record,
    }),
  },
}));
vi.mock('../store/useCompileLogsStore', () => ({
  useCompileLogsStore: { getState: () => ({ appendLogs: vi.fn() }) },
}));
vi.mock('../utils/boardCompile', () => ({
  compileBoardForFlash: fixture.compile,
  collectSketchFilesForBoard: () => fixture.files,
}));
vi.mock('../lib/proBoardGate', () => ({ boardGateVerdict: () => ({ decision: 'allow' }) }));
import { cancelAgentCompile, executeAgentCompile } from '../services/agentCompile';

beforeEach(() => {
  cancelAgentCompile();
  vi.clearAllMocks();
  fixture.files[0].content = 'void setup() {}\nvoid loop() {}\n';
});
describe('application-native chat compile', () => {
  it('uses the toolbar compiler without recording until the inputs are verified', async () => {
    fixture.compile.mockResolvedValue({ ok: true, program: 'hex', uf2: null, elapsedMs: 10 });
    expect(await executeAgentCompile()).toMatchObject({
      ok: true,
      state: 'compiled',
      compiled: true,
      confirmed: false,
      behavior_verified: false,
    });
    expect(fixture.compile).toHaveBeenCalledWith(fixture.board, expect.any(Function), {
      record: false,
    });
    expect(fixture.record).toHaveBeenCalledWith('uno', 'hex', { uf2: null });
    await executeAgentCompile();
    expect(fixture.compile).toHaveBeenCalledTimes(1);
  });
  it('resumes one pending build and returns its final result without restarting it', async () => {
    let finish!: (value: unknown) => void;
    fixture.compile.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    expect(await executeAgentCompile(0)).toMatchObject({ state: 'compiling', confirmed: false });
    finish({ ok: true, program: 'hex', uf2: null, elapsedMs: 5 });
    expect(await executeAgentCompile()).toMatchObject({ state: 'compiled' });
    expect(fixture.compile).toHaveBeenCalledTimes(1);
  });
  it('never records an old build after a native source edit', async () => {
    fixture.compile.mockImplementation(async () => {
      fixture.files[0].content += '// manual edit\n';
      return { ok: true, program: 'old', uf2: null };
    });
    expect(await executeAgentCompile()).toMatchObject({
      ok: false,
      state: 'stale',
      compiled: false,
    });
    expect(fixture.record).not.toHaveBeenCalled();
  });
  it('keeps compilation errors distinct from successful firmware and simulation', async () => {
    fixture.compile.mockResolvedValue({ ok: false, error: 'sketch.ino:3: broken', elapsedMs: 4 });
    expect(await executeAgentCompile()).toMatchObject({
      ok: false,
      state: 'error',
      compiled: false,
      confirmed: false,
      compilation: { success: false },
      error: { code: 'compilation_failed', message: 'sketch.ino:3: broken' },
    });
    expect(fixture.record).not.toHaveBeenCalled();
  });
  it('does not publish a compile result after changing projects or stopping', async () => {
    let finish!: (value: unknown) => void;
    fixture.compile.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    expect(await executeAgentCompile(0)).toMatchObject({ state: 'compiling' });
    cancelAgentCompile();
    finish({ ok: true, program: 'old', uf2: null });
    await Promise.resolve();
    await Promise.resolve();
    expect(fixture.record).not.toHaveBeenCalled();
  });
});
