export function buildHostHeaders(
  ownerToken: string,
  accountToken: string,
  json = false,
): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Owner-Token': ownerToken,
  };
  if (accountToken) {
    headers.Authorization = `Bearer ${accountToken}`;
  }
  if (json) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}
