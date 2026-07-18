export function canAccessAcceptance(role: string | undefined): boolean {
  return role === 'admin';
}
