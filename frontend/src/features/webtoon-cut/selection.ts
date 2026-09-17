export function toggleSelection(current: ReadonlySet<string>, targetIds: Iterable<string>): Set<string> {
  const targets = [...new Set(targetIds)];
  if (!targets.length) return new Set(current);
  const next = new Set(current);
  if (targets.every((id) => next.has(id))) {
    targets.forEach((id) => next.delete(id));
  } else {
    targets.forEach((id) => next.add(id));
  }
  return next;
}
