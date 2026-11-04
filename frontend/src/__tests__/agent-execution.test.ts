import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BoardInstance } from '../types/board';

const fixture = vi.hoisted(() => ({
  board: {
    id: 'target',
    boardKind: 'raspberry-pi-pico',
    running: false,
    activeFileGroupId: 'source',
    compiledProgram: null,
  } as unknown as BoardInstance,
  engineRunning: false,
  guestClock: -1,
  logs: [] as Array<{ type: string; message: string; timestamp: Date; target?: { id: string } }>,
}));
const stopBoard = vi.fn(() => {
  fixture.board.running = false;
  fixture.engineRunning = false;
  beginBoardExecution('target', 'stopped');
});
const engine = vi.hoisted(() => ({ isRunning: vi.fn(), getGuestMicros: vi.fn() }));
vi.mock('../store/useSimulatorStore', () => ({
  getBoardSimulator: () => engine,
  useSimulatorStore: {
    getState: () => ({ boards: [fixture.board], activeBoardId: 'target', stopBoard }),
  },
}));
vi.mock('../store/useCompileLogsStore', () => ({
  useCompileLogsStore: { getState: () => ({ logs: fixture.logs }) },
}));

import {
  beginBoardExecution,
  boardExecutionState,
  updateBoardExecution,
  forgetBoardExecution,
  acknowledgeBoardEvent,
} from '../simulation/boardExecutionState';
import {
  executeAgentProjectRun,
  projectExecutionStatus,
  registerProjectExecutor,
  cancelAgentProjectRun,
} from '../services/projectExecution';
import { Esp32Bridge } from '../simulation/Esp32Bridge';
import { Stm32Bridge } from '../simulation/Stm32Bridge';
import { RaspberryPi3Bridge } from '../simulation/RaspberryPi3Bridge';
import { installBoardGateImpl } from '../lib/proBoardGate';

class Socket {
  static CLOSED = 3;
  static all: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  constructor() {
    Socket.all.push(this);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(type: string, data: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify({ type, data }) });
  }
}
let dispose = () => {};
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', Socket);
  forgetBoardExecution('target');
  fixture.board = {
    id: 'target',
    boardKind: 'raspberry-pi-pico',
    running: false,
    compiledProgram: null,
    activeFileGroupId: 'source',
  } as unknown as BoardInstance;
  fixture.engineRunning = false;
  fixture.guestClock = -1;
  engine.isRunning.mockImplementation(() => fixture.engineRunning);
  engine.getGuestMicros.mockImplementation(() => fixture.guestClock);
  fixture.logs = [];
  Socket.all = [];
  installBoardGateImpl(null);
});
afterEach(() => {
  dispose();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  installBoardGateImpl(null);
});

describe('agent execution across engine families', () => {
  it('runs a Pico through the shared executor and confirms its real engine', async () => {
    dispose = registerProjectExecutor(async () => {
      fixture.board.running = true;
      fixture.engineRunning = true;
    });
    expect(await executeAgentProjectRun()).toMatchObject({
      ok: true,
      board: 'raspberry-pi-pico',
      state: 'running',
      confirmed: true,
    });
  });

  for (const [kind, Bridge] of [
    ['esp32', Esp32Bridge],
    ['stm32-bluepill', Stm32Bridge],
  ] as const) {
    it(`waits for ${kind} engine acknowledgement instead of its open socket`, async () => {
      fixture.board.boardKind = kind;
      const bridge = new Bridge('target', kind);
      dispose = registerProjectExecutor(async () => {
        fixture.board.running = true;
        bridge.connect();
        Socket.all[0].open();
        fixture.engineRunning = true;
      });
      const running = executeAgentProjectRun();
      await vi.advanceTimersByTimeAsync(100);
      expect(projectExecutionStatus()).toMatchObject({ state: 'booting', confirmed: false });
      Socket.all[0].receive('system', { event: 'booted' });
      await vi.advanceTimersByTimeAsync(50);
      expect(await running).toMatchObject({
        ok: true,
        state: 'running',
        confirmed: true,
        evidence: 'engine_acknowledgement',
      });
      Socket.all[0].receive('system', { event: 'crash', reason: 'worker_exit' });
      expect(projectExecutionStatus()).toMatchObject({
        ok: false,
        state: 'error',
        error: { code: 'engine_crashed' },
      });
    });

    it(`reports ${kind} backend refusal with the original diagnostic`, async () => {
      fixture.board.boardKind = kind;
      const bridge = new Bridge('target', kind);
      dispose = registerProjectExecutor(async () => {
        fixture.board.running = true;
        bridge.connect();
        Socket.all[0].open();
        Socket.all[0].receive('error', {
          message: 'Runtime is not installed',
          code: 'runtime_missing',
        });
      });
      expect(await executeAgentProjectRun()).toMatchObject({
        ok: false,
        state: 'error',
        error: { code: 'runtime_missing', message: 'Runtime is not installed' },
      });
    });
  }

  it('returns a pollable Linux boot without claiming the project is running', async () => {
    fixture.board.boardKind = 'raspberry-pi-3';
    const bridge = new RaspberryPi3Bridge('target', 'raspberry-pi-3');
    dispose = registerProjectExecutor(async () => {
      fixture.board.running = true;
      bridge.connect();
      Socket.all[0].open();
      Socket.all[0].receive('system', { event: 'booted' });
    });
    const running = executeAgentProjectRun();
    await vi.advanceTimersByTimeAsync(8100);
    expect(await running).toMatchObject({ ok: true, state: 'booting', confirmed: false });
    // The Linux upload path acknowledges only after the shell and upload.
    updateBoardExecution('target', 'running', { evidence: 'guest_ready_and_script_dispatched' });
    expect(projectExecutionStatus()).toMatchObject({ state: 'running', confirmed: true });
  });

  it('requires a new in-browser clock advance instead of accepting a stale positive clock', () => {
    fixture.board.boardKind = 'esp32';
    fixture.board.running = true;
    beginBoardExecution('target', 'booting');
    fixture.guestClock = 500;
    expect(projectExecutionStatus()).toMatchObject({ state: 'booting', confirmed: false });
    expect(projectExecutionStatus()).toMatchObject({ state: 'booting', confirmed: false });
    fixture.guestClock = 501;
    expect(projectExecutionStatus()).toMatchObject({
      state: 'running',
      confirmed: true,
      evidence: 'guest_clock_advanced',
    });
    beginBoardExecution('target', 'booting');
    expect(projectExecutionStatus()).toMatchObject({ state: 'booting', confirmed: false });
  });

  it('ignores queued messages and close events from a replaced simulation socket', () => {
    fixture.board.boardKind = 'esp32';
    const bridge = new Esp32Bridge('target', 'esp32');
    bridge.connect();
    const old = Socket.all[0];
    const lateMessage = old.onmessage!;
    const lateClose = old.onclose!;
    bridge.connect();
    Socket.all[1].open();
    lateMessage({ data: JSON.stringify({ type: 'system', data: { event: 'booted' } }) });
    lateClose();
    expect(boardExecutionState('target')?.state).toBe('booting');
    expect(bridge.connected).toBe(true);
    Socket.all[1].receive('system', { event: 'booted' });
    expect(boardExecutionState('target')?.state).toBe('running');
  });

  it('recognizes a short Python script completing before the running flag is sampled', async () => {
    fixture.board.boardKind = 'raspberry-pi-3';
    dispose = registerProjectExecutor(async () => {
      const run = beginBoardExecution('target');
      updateBoardExecution('target', 'completed', { evidence: 'script_completed' }, run);
    });
    expect(await executeAgentProjectRun()).toMatchObject({
      ok: true,
      state: 'completed',
      confirmed: true,
    });
  });

  it('returns a compile failure and ignores old errors from another target', async () => {
    fixture.logs.push({
      type: 'error',
      message: 'Old error',
      target: { id: 'another' },
      timestamp: new Date(),
    });
    dispose = registerProjectExecutor(async () => {
      fixture.logs.push({
        type: 'error',
        message: 'Core not installed',
        target: { id: 'target' },
        timestamp: new Date(),
      });
    });
    expect(await executeAgentProjectRun()).toMatchObject({
      ok: false,
      state: 'blocked',
      error: { code: 'compilation_failed', message: 'Core not installed' },
    });
  });

  it('preserves board access decisions before compiling', async () => {
    fixture.board.boardKind = 'stm32-bluepill';
    installBoardGateImpl(() => ({ decision: 'block', description: 'Runtime access is disabled' }));
    const executor = vi.fn();
    dispose = registerProjectExecutor(executor);
    expect(await executeAgentProjectRun()).toMatchObject({
      ok: false,
      error: { code: 'board_access_denied' },
    });
    expect(executor).not.toHaveBeenCalled();
  });

  it('stops while waiting for boot and rejects acknowledgements from that run', async () => {
    fixture.board.boardKind = 'esp32';
    let run = 0;
    dispose = registerProjectExecutor(async () => {
      fixture.board.running = true;
      run = beginBoardExecution('target', 'booting');
    });
    const running = executeAgentProjectRun();
    await vi.advanceTimersByTimeAsync(100);
    cancelAgentProjectRun();
    await vi.advanceTimersByTimeAsync(50);
    expect(await running).toMatchObject({ ok: false, state: 'stopped' });
    acknowledgeBoardEvent('target', 'booted', {}, run);
    expect(boardExecutionState('target')?.state).toBe('stopped');
  });

  it('turns an unconfirmed long boot into an explicit timeout', () => {
    fixture.board.running = true;
    fixture.board.boardKind = 'esp32';
    beginBoardExecution('target', 'booting');
    vi.advanceTimersByTime(120001);
    expect(projectExecutionStatus()).toMatchObject({
      ok: false,
      error: { code: 'startup_timeout' },
    });
  });
});
