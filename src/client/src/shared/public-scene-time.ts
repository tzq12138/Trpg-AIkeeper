export interface PublicSceneTimeUpdate {
  sceneTime: string;
  version: number;
}

export async function updatePublicSceneTime(
  roomId: string,
  ownerToken: string,
  sceneTime: string,
  fetcher: typeof fetch = fetch,
): Promise<PublicSceneTimeUpdate> {
  const response = await fetcher(`/api/host/${roomId}/public-scene-time`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-Owner-Token': ownerToken,
    },
    body: JSON.stringify({ sceneTime }),
  });
  if (!response.ok) {
    throw new Error('public_scene_time_update_failed');
  }
  return response.json() as Promise<PublicSceneTimeUpdate>;
}
