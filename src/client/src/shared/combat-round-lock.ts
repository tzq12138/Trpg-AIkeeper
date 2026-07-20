export function lockCombatRoundReceipt<T extends { can_cancel: boolean } | null>(receipt: T): T {
  return receipt ? { ...receipt, can_cancel: false } : receipt;
}
