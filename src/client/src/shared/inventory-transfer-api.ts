export type InventoryTransferDecision = 'accept' | 'reject';

export interface InventoryTransferDTO {
  transferId: string;
  itemId: string;
  itemName: string;
  isSecret: boolean;
  fromCharacterId: string;
  toCharacterId: string;
  fromPlayerName: string;
  toPlayerName: string;
  quantity: number;
  status: 'pending' | 'completed' | 'rejected' | 'unavailable';
  createdAt: string;
  resolvedAt: string | null;
}

export async function requestInventoryTransfer(
  itemId: string,
  toCharacterId: string,
  quantity: number,
  headers: Record<string, string>,
  fetcher: typeof fetch = fetch,
): Promise<InventoryTransferDTO> {
  const response = await fetcher(`/api/player/inventory/${encodeURIComponent(itemId)}/transfers`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ toCharacterId, quantity }),
  });
  if (!response.ok) throw new Error('inventory_transfer_request_failed');
  return response.json() as Promise<InventoryTransferDTO>;
}

export async function resolveInventoryTransfer(
  transferId: string,
  decision: InventoryTransferDecision,
  headers: Record<string, string>,
  fetcher: typeof fetch = fetch,
): Promise<InventoryTransferDTO> {
  const response = await fetcher(
    `/api/player/inventory-transfers/${encodeURIComponent(transferId)}/${decision}`,
    { method: 'POST', headers },
  );
  if (!response.ok) throw new Error('inventory_transfer_resolution_failed');
  return response.json() as Promise<InventoryTransferDTO>;
}
