import { useSimulatorStore } from '../store/useSimulatorStore';
import { useEditorStore } from '../store/useEditorStore';
import { useCompileLogsStore } from '../store/useCompileLogsStore';
import { buildVlxPayload } from '../utils/vlxFile';
import type { VlxPayload } from '../utils/vlxFile';
import type { BoardInstance } from '../types/board';
import { agentValueEqual, projectRevision } from './agentService';
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
import { AgentMergeConflict, mergeAgentDocuments } from './agentMerge';

const completed = new Map<string, Record<string, unknown>>();
const pending = new Map<string, Promise<Record<string, unknown>>>();
let editorEpoch = 0;
export function invalidateAgentEditorSession(): void {
  editorEpoch++;
}
export function agentEditorEpoch(): number {
  return editorEpoch;
}

export async function applyAgentSnapshot(
  document: VlxPayload,
  expectedRevision: string,
  baseDocument?: VlxPayload,
  preferLocal = false,
  expectedEpoch = editorEpoch,
): Promise<VlxPayload> {
  if (expectedEpoch !== editorEpoch)
    throw new AgentCircuitError(
      'project_changed',
      'The editor switched projects. The previous request was stopped.',
    );
  if ((await projectRevision()) !== expectedRevision && baseDocument)
    document = mergeAgentDocuments(baseDocument, document, buildVlxPayload(), preferLocal).document;
  else if ((await projectRevision()) !== expectedRevision)
    throw new Error(
      'Your project changed while the agent was working. Your manual edits have been preserved. Stop the agent, then send another message to synchronize them.',
    );
  // Unlike importVlxFile this keeps the identity used by cloud save/autosave.
  const current = structuredClone(buildVlxPayload());
  expectedRevision = await projectRevision(current);
  const boardConfig = (payload: VlxPayload) =>
    payload.boards.map(({ serialBaudRate: _baud, ...board }) => board);
  const boardsChanged = !agentValueEqual(boardConfig(current), boardConfig(document));
  const candidate = await prepareAgentCircuit(document);
  if (expectedEpoch !== editorEpoch)
    throw new AgentCircuitError(
      'project_changed',
      'The editor switched projects. The previous request was stopped.',
    );
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
    return structuredClone(buildVlxPayload());
  }
  const circuitChanged =
    !agentValueEqual(current.components, candidate.components) ||
    !agentValueEqual(normalizeAgentDocument(current).wires, candidate.wires);
  for (const board of sim.boards) {
    if (
      !agentValueEqual(
        current.fileGroups[board.activeFileGroupId],
        candidate.fileGroups[board.activeFileGroupId],
      )
    ) {
      if (board.running) sim.stopBoard(board.id);
      sim.updateBoard(board.id, { compiledProgram: null, compiledUf2: null });
    }
    if (circuitChanged && board.running) sim.stopBoard(board.id);
  }
  if (
    !agentValueEqual(current.fileGroups, candidate.fileGroups) ||
    !agentValueEqual(current.folderGroups, candidate.folderGroups)
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
  return structuredClone(buildVlxPayload());
}

async function perform(command: Record<string, unknown>): Promise<Record<string, unknown>> {
  const epoch = editorEpoch;
  let expected = command.expected_revision as string;
  const observed = structuredClone(buildVlxPayload());
  const observedRevision = await projectRevision(observed);
  if (epoch !== editorEpoch)
    throw new AgentCircuitError('project_changed', 'The editor switched projects.');
  // Read-only metadata must not fail merely because the editor moved ahead.
  if (command.action === 'inspect_project')
    return { ...inspectAgentProject(), document: observed, revision: observedRevision };
  if (command.action === 'describe_part')
    return describeAgentPart(String(command.kind), String(command.part_id));
  if (command.document && command.base_document) {
    command = {
      ...command,
      document: mergeAgentDocuments(
        command.base_document as VlxPayload,
        command.document as VlxPayload,
        observed,
      ).document,
    };
    expected = observedRevision;
  }
  if (observedRevision !== expected && command.action !== 'stop')
    return {
      ok: false,
      error: {
        code: 'revision_conflict',
        message: 'Manual project edits were preserved. Stop and synchronize before continuing.',
      },
    };
  if (command.action === 'validate_circuit') {
    const candidate = await prepareAgentCircuit(command.document as VlxPayload);
    return {
      ok: true,
      validated: true,
      revision: await projectRevision(candidate),
      connections: candidate.wires.length,
      document: candidate,
      editor_document: observed,
      editor_revision: observedRevision,
    };
  }
  if (command.action === 'apply') {
    const document = await applyAgentSnapshot(
      command.document as VlxPayload,
      expected,
      observed,
      false,
      epoch,
    );
    const revision = await projectRevision();
    return {
      ok: revision === (await projectRevision(document)),
      applied_revision: revision,
      revision,
      document,
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
    const applied = await applyAgentSnapshot(document, expected, observed, false, epoch);
    const revision = await projectRevision();
    return {
      ok: revision === (await projectRevision(applied)),
      applied_revision: revision,
      state: 'ready',
      revision,
      document: applied,
    };
  }
  if (command.action === 'run') {
    const applied = await applyAgentSnapshot(
      command.document as VlxPayload,
      expected,
      observed,
      false,
      epoch,
    );
    const revision = await projectRevision();
    if (revision !== (await projectRevision(applied)))
      return {
        ok: false,
        error: {
          code: 'revision_conflict',
          message: 'The loaded project does not match the requested revision.',
        },
      };
    const result = await executeAgentProjectRun();
    const actual = structuredClone(buildVlxPayload());
    // Only library discovery may change the compile manifest without changing
    // what the user/model asked to build. Other concurrent edits stay visible.
    const compatible = structuredClone(applied);
    for (const board of compatible.boards) {
      const current = actual.boards.find((item) => item.id === board.id);
      if (current) {
        board.x = current.x;
        board.y = current.y;
      }
      if (current?.libraries === undefined) delete board.libraries;
      else board.libraries = current.libraries;
    }
    for (const component of compatible.components) {
      const current = actual.components.find((item) => item.id === component.id);
      if (current) {
        component.x = current.x;
        component.y = current.y;
      }
    }
    for (const wire of compatible.wires) {
      const current = actual.wires.find((item) => item.id === wire.id);
      if (current) {
        wire.color = current.color;
        wire.waypoints = current.waypoints;
      }
    }
    const finalRevision = await projectRevision(actual);
    if ((await projectRevision(compatible)) !== finalRevision)
      return {
        ok: false,
        state: 'stale',
        confirmed: false,
        document: actual,
        applied_revision: finalRevision,
        revision: finalRevision,
        error: {
          code: 'execution_changed',
          message:
            'The project changed during compilation. Your latest edits were preserved; run the current project again.',
        },
      };
    return {
      ...result,
      document: actual,
      applied_revision: finalRevision,
      revision: finalRevision,
    };
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
  const operation = (async () => {
    for (let attempt = 0; ; attempt++) {
      try {
        return await perform(command);
      } catch (error) {
        if (
          attempt >= 2 ||
          !command.base_document ||
          !['validate_circuit', 'apply'].includes(String(command.action)) ||
          !(error instanceof AgentCircuitError) ||
          error.code !== 'revision_conflict'
        )
          throw error;
      }
    }
  })()
    .catch((error: unknown) => ({
      ok: false,
      error: {
        code:
          error instanceof AgentCircuitError || error instanceof AgentMergeConflict
            ? error.code
            : 'editor_error',
        message: error instanceof Error ? error.message : 'Editor action failed.',
        ...(error instanceof AgentCircuitError ? { details: error.details } : {}),
        ...(error instanceof AgentMergeConflict
          ? { details: { conflicting_paths: error.paths } }
          : {}),
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
  return structuredClone(buildVlxPayload());
}
