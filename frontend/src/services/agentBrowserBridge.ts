import { useSimulatorStore } from '../store/useSimulatorStore';
import { useEditorStore } from '../store/useEditorStore';
import { useCompileLogsStore } from '../store/useCompileLogsStore';
import { buildVlxPayload } from '../utils/vlxFile';
import type { VlxPayload } from '../utils/vlxFile';
import type { BoardInstance } from '../types/board';
import { projectRevision } from './agentService';
import {
  executeAgentProjectRun,
  projectExecutionStatus,
  cancelAgentProjectRun,
} from './projectExecution';
import {
  AgentCircuitError,
  prepareAgentCircuit,
  settleAgentCircuit,
  inspectAgentProject,
  describeAgentPart,
} from './agentCircuit';
import { normalizeAgentDocument } from './agentDocument';
import { flushElectricalResolve } from '../simulation/spice/electricalResolveHook';

const completed = new Map<string, Record<string, unknown>>();
const pending = new Map<string, Promise<Record<string, unknown>>>();

export async function applyAgentSnapshot(
  document: VlxPayload,
  expectedRevision: string,
): Promise<void> {
  if ((await projectRevision()) !== expectedRevision)
    throw new Error(
      'Your project changed while the agent was working. Your manual edits have been preserved. Stop the agent, then send another message to synchronize them.',
    );
  // Unlike importVlxFile this keeps the identity used by cloud save/autosave.
  const current = buildVlxPayload();
  const boardConfig = (payload: VlxPayload) =>
    payload.boards.map(({ serialBaudRate: _baud, ...board }) => board);
  const boardsChanged =
    JSON.stringify(boardConfig(current)) !== JSON.stringify(boardConfig(document));
  const candidate = await prepareAgentCircuit(document);
  if ((await projectRevision()) !== expectedRevision)
    throw new AgentCircuitError(
      'revision_conflict',
      'The project changed while validating connections. Your edits were preserved.',
    );
  const sim = useSimulatorStore.getState();
  if (boardsChanged) {
    // Recreate the engines too: changing only boardKind would leave the old
    // MCU/bridge attached to the new picture. loadProjectState keeps project identity.
    sim.loadProjectState({ ...candidate, boards: candidate.boards as BoardInstance[] });
    try {
      await settleAgentCircuit(candidate);
      sim.recalculateAllWirePositions();
      await flushElectricalResolve();
    } catch (error) {
      if ((await projectRevision()) === (await projectRevision(candidate))) {
        sim.loadProjectState({ ...current, boards: current.boards as BoardInstance[] });
      }
      throw error;
    }
    return;
  }
  const circuitChanged =
    JSON.stringify(current.components) !== JSON.stringify(candidate.components) ||
    JSON.stringify(normalizeAgentDocument(current).wires) !== JSON.stringify(candidate.wires);
  for (const board of sim.boards) {
    if (
      JSON.stringify(current.fileGroups[board.activeFileGroupId]) !==
      JSON.stringify(candidate.fileGroups[board.activeFileGroupId])
    ) {
      if (board.running) sim.stopBoard(board.id);
      sim.updateBoard(board.id, { compiledProgram: null, compiledUf2: null });
    }
    if (circuitChanged && board.running) sim.stopBoard(board.id);
  }
  if (
    JSON.stringify(current.fileGroups) !== JSON.stringify(candidate.fileGroups) ||
    JSON.stringify(current.folderGroups) !== JSON.stringify(candidate.folderGroups)
  )
    useEditorStore.getState().replaceFileGroups(candidate.fileGroups, candidate.folderGroups);
  if (circuitChanged) {
    sim.applyCircuitState(candidate.components, candidate.wires);
    try {
      await settleAgentCircuit(candidate);
      sim.recalculateAllWirePositions();
      await flushElectricalResolve();
    } catch (error) {
      if ((await projectRevision()) === (await projectRevision(candidate))) {
        sim.applyCircuitState(current.components, normalizeAgentDocument(current).wires);
        useEditorStore.getState().replaceFileGroups(current.fileGroups, current.folderGroups);
      }
      throw error;
    }
  }
  await new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
}

async function perform(command: Record<string, unknown>): Promise<Record<string, unknown>> {
  const expected = command.expected_revision as string;
  if ((await projectRevision()) !== expected)
    return {
      ok: false,
      error: {
        code: 'revision_conflict',
        message: 'Manual project edits were preserved. Stop and synchronize before continuing.',
      },
    };
  if (command.action === 'inspect_project') return inspectAgentProject();
  if (command.action === 'describe_part')
    return describeAgentPart(String(command.kind), String(command.part_id));
  if (command.action === 'validate_circuit') {
    const candidate = await prepareAgentCircuit(command.document as VlxPayload);
    return {
      ok: true,
      validated: true,
      revision: await projectRevision(candidate),
      connections: candidate.wires.length,
      document: candidate,
    };
  }
  if (command.action === 'apply') {
    await applyAgentSnapshot(command.document as VlxPayload, expected);
    const revision = await projectRevision();
    return {
      ok: revision === command.revision,
      applied_revision: revision,
      revision,
      validated: true,
      connections: (command.document as VlxPayload).wires.length,
      boards: (command.document as VlxPayload).boards.map(({ id, boardKind }) => ({
        id,
        boardKind,
      })),
      pinouts: inspectAgentProject().pinouts,
    };
  }
  if (command.action === 'create') {
    const document = command.document as VlxPayload;
    const sim = useSimulatorStore.getState();
    if (sim.boards.length || sim.components.length)
      return {
        ok: false,
        error: { code: 'project_not_empty', message: 'The current project is no longer empty.' },
      };
    await applyAgentSnapshot(document, expected);
    const revision = await projectRevision();
    return {
      ok: revision === command.revision,
      applied_revision: revision,
      state: 'ready',
      revision,
    };
  }
  if (command.action === 'run') {
    await applyAgentSnapshot(command.document as VlxPayload, expected);
    const revision = await projectRevision();
    if (revision !== command.revision)
      return {
        ok: false,
        error: {
          code: 'revision_conflict',
          message: 'The loaded project does not match the requested revision.',
        },
      };
    return { ...(await executeAgentProjectRun()), applied_revision: revision, revision };
  }
  if (command.action === 'stop') {
    cancelAgentProjectRun();
    const sim = useSimulatorStore.getState();
    sim.boards.filter((board) => board.running).forEach((board) => sim.stopBoard(board.id));
    return { ok: true, state: 'stopped' };
  }
  if (command.action === 'observe') {
    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(Number(command.duration_ms) || 0, 15000)),
    );
    if ((await projectRevision()) !== expected)
      return {
        ok: false,
        error: { code: 'revision_conflict', message: 'The project changed during observation.' },
      };
    const sim = useSimulatorStore.getState();
    const board = sim.boards.find((item) => item.id === sim.activeBoardId);
    return {
      ...projectExecutionStatus(),
      revision: expected,
      serial: (board?.serialOutput ?? sim.serialOutput).slice(-8000),
      logs: useCompileLogsStore
        .getState()
        .logs.slice(-15)
        .map((entry) => entry.message)
        .join('\n')
        .slice(-6000),
      capabilities: { serial: true, images: false },
    };
  }
  return { ok: false, error: { code: 'unknown_command', message: 'Unknown editor command.' } };
}

export function handleAgentBrowserCommand(
  command: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const id = command.command_id as string;
  const saved = completed.get(id);
  if (saved) return Promise.resolve(saved);
  const existing = pending.get(id);
  if (existing) return existing;
  const operation = perform(command)
    .catch((error: unknown) => ({
      ok: false,
      error: {
        code: error instanceof AgentCircuitError ? error.code : 'editor_error',
        message: error instanceof Error ? error.message : 'Editor action failed.',
        ...(error instanceof AgentCircuitError ? { details: error.details } : {}),
      },
    }))
    .then((result) => {
      completed.set(id, result);
      pending.delete(id);
      if (completed.size > 100) completed.delete(completed.keys().next().value!);
      return result;
    });
  pending.set(id, operation);
  return operation;
}

export function snapshotForAgent(): VlxPayload {
  return buildVlxPayload();
}
