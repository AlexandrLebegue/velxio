import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import type { VlxPayload } from '../utils/vlxFile';
import { mergeAgentDocuments } from '../services/agentMerge';

const fixture = vi.hoisted(() => ({ local: null as unknown as VlxPayload, epoch: 0 }));
vi.mock('../services/agentService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/agentService')>()),
  agentRequest: vi.fn(),
}));
vi.mock('../services/agentBrowserBridge', () => ({
  snapshotForAgent: () => structuredClone(fixture.local),
  agentEditorEpoch: () => fixture.epoch,
  applyAgentSnapshot: vi.fn(
    async (
      document: VlxPayload,
      _revision: string,
      base: VlxPayload,
      _prefer: boolean,
      epoch: number,
    ) => {
      if (epoch !== fixture.epoch) throw Error('project_changed');
      fixture.local = mergeAgentDocuments(base, document, fixture.local, true).document;
      return structuredClone(fixture.local);
    },
  ),
}));
import { agentRequest, projectRevision } from '../services/agentService';
import { applyAgentSnapshot } from '../services/agentBrowserBridge';
import { synchronizeAgentSession } from '../services/agentSync';

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  vi.clearAllMocks();
  fixture.epoch = 0;
  fixture.local = {
    format: 'velxio-project',
    version: 1,
    boards: [{ id: 'b', boardKind: 'arduino-uno', x: 0, y: 0, activeFileGroupId: 'g' }],
    components: [],
    wires: [],
    fileGroups: {
      g: [
        { name: 'sketch.ino', content: 'original' },
        { name: 'user.h', content: 'original header' },
      ],
    },
    activeBoardId: 'b',
  } as unknown as VlxPayload;
});

describe('automatic chat synchronization', () => {
  it('downloads server edits, preserves a manual move and acknowledges the resulting revision', async () => {
    const base = structuredClone(fixture.local),
      baseRevision = await projectRevision(base);
    fixture.local.boards[0].x = 90;
    const server = structuredClone(base);
    server.fileGroups.g[0].content = 'agent source';
    const serverRevision = await projectRevision(server);
    const merged = mergeAgentDocuments(base, server, fixture.local).document;
    const mergedRevision = await projectRevision(merged);
    vi.mocked(agentRequest).mockResolvedValue({
      id: 'session',
      revision: mergedRevision,
      document: merged,
    });
    const result = await synchronizeAgentSession('session', serverRevision, baseRevision);
    expect(fixture.local.boards[0].x).toBe(90);
    expect(fixture.local.fileGroups.g[0].content).toBe('agent source');
    expect(result.editorRevision).toBe(mergedRevision);
    expect(agentRequest).toHaveBeenCalledTimes(2);
    expect(vi.mocked(agentRequest).mock.calls[1][2]).toMatchObject({
      base_revision: mergedRevision,
      expected_revision: mergedRevision,
    });
  });

  it('keeps a manual header edit arriving while the server request is in flight', async () => {
    const baseRevision = await projectRevision(fixture.local);
    let first = true;
    vi.mocked(agentRequest).mockImplementation(async (_path, _method, body) => {
      const sent = structuredClone((body as { document: VlxPayload }).document);
      if (first) {
        first = false;
        fixture.local.fileGroups.g[1].content = 'latest manual header';
        sent.fileGroups.g[0].content = 'agent source';
      }
      return { id: 'session', revision: await projectRevision(sent), document: sent };
    });
    const result = await synchronizeAgentSession('session', baseRevision, baseRevision);
    expect(result.document.fileGroups.g.map((f) => f.content)).toEqual([
      'agent source',
      'latest manual header',
    ]);
    expect(agentRequest).toHaveBeenCalledTimes(2);
  });

  it('avoids reapplying an unchanged document', async () => {
    const revision = await projectRevision(fixture.local);
    vi.mocked(agentRequest).mockResolvedValue({
      id: 'session',
      revision,
      document: structuredClone(fixture.local),
    });
    await synchronizeAgentSession('session', revision, revision);
    expect(agentRequest).toHaveBeenCalledTimes(1);
    expect(applyAgentSnapshot).not.toHaveBeenCalled();
  });

  it('does not apply a delayed response to a different editor project', async () => {
    const revision = await projectRevision(fixture.local);
    vi.mocked(agentRequest).mockImplementation(async () => {
      const old = structuredClone(fixture.local);
      old.fileGroups.g[0].content = 'old project response';
      fixture.epoch++;
      fixture.local.fileGroups.g[0].content = 'new project';
      return { id: 'session', revision: await projectRevision(old), document: old };
    });
    await expect(synchronizeAgentSession('session', revision, revision)).rejects.toThrow(
      'project_changed',
    );
    expect(fixture.local.fileGroups.g[0].content).toBe('new project');
  });
});
