export function toggleSelectedResource(selectedIds: string[], resourceId: string, selected: boolean) {
  if (selected) return selectedIds.includes(resourceId) ? selectedIds : [...selectedIds, resourceId];
  return selectedIds.filter((item) => item !== resourceId);
}
