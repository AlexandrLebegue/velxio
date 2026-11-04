import type { VlxPayload } from '../utils/vlxFile';

export class AgentMergeConflict extends Error {
  readonly code = 'edit_conflict';
  readonly paths: string[];
  constructor(paths: string[]) {
    super(
      `The same fields changed in the editor and agent: ${paths.slice(0, 4).join(', ')}. Manual edits were preserved.`,
    );
    this.paths = paths;
  }
}

/** Three-way merge; overlapping edits are never silently overwritten. */
export function mergeAgentDocuments(
  base: VlxPayload,
  proposed: VlxPayload,
  local: VlxPayload,
  preferLocal = false,
): { document: VlxPayload; conflicts: string[] } {
  const missing = Symbol('missing');
  const conflicts: string[] = [];
  const same = (a: unknown, b: unknown): boolean => {
    if (a === missing || b === missing) return a === b;
    if (Array.isArray(a) && Array.isArray(b))
      return a.length === b.length && a.every((v, i) => same(v, b[i]));
    if (a && b && typeof a === 'object' && typeof b === 'object') {
      const left = a as Record<string, unknown>,
        right = b as Record<string, unknown>;
      return (
        Object.keys(left).length === Object.keys(right).length &&
        Object.keys(left).every((k) => k in right && same(left[k], right[k]))
      );
    }
    return a === b;
  };
  const clone = (v: unknown) => (v === missing ? missing : structuredClone(v));
  const object = (v: unknown): v is Record<string, unknown> =>
    Boolean(v) && typeof v === 'object' && !Array.isArray(v);
  function merge(old: unknown, wanted: unknown, current: unknown, path: string[]): unknown {
    if (
      old === missing &&
      path.at(-1) === 'libraries' &&
      Array.isArray(wanted) &&
      Array.isArray(current)
    )
      old = [];
    if (same(wanted, old)) return clone(current);
    if (same(current, old) || same(wanted, current)) return clone(wanted);
    const volatile =
      (path.length === 1 && ['name', 'exportedAt'].includes(path[0])) ||
      (path.length === 3 && path[0] === 'boards' && path[2] === 'serialBaudRate') ||
      (path[0] === 'wires' &&
        (path.at(-1) === 'signalType' ||
          (path.length === 4 &&
            ['start', 'end'].includes(path[2]) &&
            ['x', 'y'].includes(path[3]))));
    if (volatile) return clone(current);
    if (object(old) && object(wanted) && object(current)) {
      const out: Record<string, unknown> = {};
      for (const key of [
        ...new Set([...Object.keys(old), ...Object.keys(wanted), ...Object.keys(current)]),
      ].sort()) {
        const v = merge(
          key in old ? old[key] : missing,
          key in wanted ? wanted[key] : missing,
          key in current ? current[key] : missing,
          [...path, key],
        );
        if (v !== missing) out[key] = v;
      }
      return out;
    }
    if (Array.isArray(old) && Array.isArray(wanted) && Array.isArray(current)) {
      const entries: unknown[] = [...old, ...wanted, ...current];
      const field = ['id', 'name'].find(
        (key) => entries.length && entries.every((v) => object(v) && typeof v[key] === 'string'),
      );
      if (field) {
        const maps = [old, wanted, current].map(
          (values) => new Map(values.map((v) => [v[field], v])),
        );
        if (maps.every((map, i) => map.size === [old, wanted, current][i].length)) {
          const out: unknown[] = [];
          for (const key of new Set(
            [...current, ...wanted, ...old].map((v) => v[field] as string),
          )) {
            const v = merge(
              ...(maps.map((map) => (map.has(key) ? map.get(key) : missing)) as [
                unknown,
                unknown,
                unknown,
              ]),
              [...path, key],
            );
            if (v !== missing) out.push(v);
          }
          return out;
        }
      }
      if (path.at(-1) === 'libraries' && entries.every((v) => typeof v === 'string')) {
        const removed = new Set(old.filter((v) => !wanted.includes(v) || !current.includes(v)));
        return [...new Set([...current, ...wanted].filter((v) => !removed.has(v)))];
      }
    }
    conflicts.push('/' + path.map((v) => v.replaceAll('~', '~0').replaceAll('/', '~1')).join('/'));
    return clone(current);
  }
  // The wire protocol omits undefined properties. Native editor snapshots
  // contain them, so normalize all three sides to the actual JSON contract.
  const json = (value: VlxPayload): VlxPayload => JSON.parse(JSON.stringify(value));
  const document = merge(json(base), json(proposed), json(local), []) as VlxPayload;
  if (conflicts.length && !preferLocal) throw new AgentMergeConflict(conflicts);
  return { document, conflicts };
}
