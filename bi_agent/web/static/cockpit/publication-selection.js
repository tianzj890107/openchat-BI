export function selectSlotAnalysis({
  slotId, independent = false, published = null, current = null,
  validPayload = () => true,
}) {
  const projected = published?.status === 'ready' && published.payload
    && validPayload(published.payload) ? published.payload : null;
  if (independent) {
    if (projected) return projected;
    return current?.context?.slotId === slotId ? current : null;
  }
  if (!projected) return current;
  if (!current) return projected;
  return Number(projected.updatedAt || 0) >= Number(current.updatedAt || 0)
    ? projected : current;
}
