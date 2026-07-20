export function canExecuteGlobalReset({
  backupId,
  downloaded,
  verified,
  acknowledged,
}: {
  backupId: string;
  downloaded: boolean;
  verified: boolean;
  acknowledged: boolean;
}): boolean {
  return Boolean(backupId) && downloaded && verified && acknowledged;
}
