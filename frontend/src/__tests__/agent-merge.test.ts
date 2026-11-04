import { describe, expect, it } from 'vitest';
import cases from '../../../test/fixtures/agent-merge-cases.json';
import { AgentMergeConflict, mergeAgentDocuments } from '../services/agentMerge';
import type { VlxPayload } from '../utils/vlxFile';

describe('automatic editor/agent reconciliation', () => {
  for (const fixture of cases)
    it(fixture.name, () => {
      const args = [fixture.base, fixture.proposed, fixture.local] as unknown as [
        VlxPayload,
        VlxPayload,
        VlxPayload,
      ];
      const before = structuredClone(args);
      expect(mergeAgentDocuments(...args, true)).toEqual({
        document: fixture.expected,
        conflicts: fixture.conflicts,
      });
      expect(args).toEqual(before);
      if (fixture.conflicts.length)
        expect(() => mergeAgentDocuments(...args)).toThrow(AgentMergeConflict);
      else expect(mergeAgentDocuments(...args).document).toEqual(fixture.expected);
    });
});
