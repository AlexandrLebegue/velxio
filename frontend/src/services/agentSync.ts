/** Automatically reconcile the editor with an idle conversation, preserving manual edits. */
import type { VlxPayload } from '../utils/vlxFile';
import { agentRequest, projectRevision, type AgentSession } from './agentService';
import { agentEditorEpoch, applyAgentSnapshot, snapshotForAgent } from './agentBrowserBridge';

export async function synchronizeAgentSession(
  id: string,
  serverRevision: string,
  baseRevision: string,
) {
  const epoch = agentEditorEpoch();
  let session: (AgentSession & { document?: VlxPayload }) | null = null;
  let document = snapshotForAgent();
  let localRevision = await projectRevision(document);
  for (let attempt = 0; attempt < 3; attempt++) {
    const sent = document;
    const sentRevision = localRevision;
    session = await agentRequest<AgentSession & { document?: VlxPayload }>(
      `/sessions/${id}/workspace`,
      'PATCH',
      {
        document: sent,
        expected_revision: serverRevision,
        base_revision: baseRevision || serverRevision,
      },
    );
    if (session.document && (await projectRevision(snapshotForAgent())) !== session.revision)
      await applyAgentSnapshot(session.document, sentRevision, sent, true, epoch);
    document = snapshotForAgent();
    localRevision = await projectRevision(document);
    serverRevision = session.revision;
    baseRevision = session.revision;
    if (sentRevision === serverRevision && localRevision === serverRevision) break;
  }
  if (!session) throw new Error('Conversation synchronization did not complete.');
  return { session, document, editorRevision: localRevision, baseRevision };
}
