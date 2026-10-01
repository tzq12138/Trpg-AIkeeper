import { useEffect, useState } from 'react';
import type { CampaignHomeDTO } from '../shared/types';
import { getSlotValue } from '../shared/identity';

/// <summary>缺少授权场景图时使用的无剧情含义装饰插画。</summary>
const atmosphereUrl = new URL('../assets/player-journal/journal-atmosphere.png', import.meta.url).href;

/// <summary>玩家已经获准看到的场景标题和插画。</summary>
interface PlayerSceneHeaderProps {
  /// <summary>玩家战役接口投影出的当前场景；空值表示尚未加载。</summary>
  scene: CampaignHomeDTO['current_scene'];
}

/// <summary>呈现当前场景的视觉页头。</summary>
/// <param name="props">玩家可见的场景。</param>
/// <returns>场景页头。</returns>
export default function PlayerSceneHeader({ scene }: PlayerSceneHeaderProps) {
  const assetId = scene?.image_asset_id || '';
  const token = getSlotValue('player_token') || '';
  const [image, setImage] = useState<{ assetId: string; token: string; url: string } | null>(null);

  useEffect(() => {
    if (!assetId || !token) return;
    const controller = new AbortController();
    let objectUrl = '';
    // 1. 使用玩家凭证取图；后台决定该角色是否有权访问素材。
    void fetch(`/api/player/assets/${encodeURIComponent(assetId)}`, {
      headers: { 'X-Room-Token': token }, signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error('Scene image unavailable');
      const blob = await response.blob();
      if (controller.signal.aborted || !blob.type.startsWith('image/')) return;
      objectUrl = URL.createObjectURL(blob);
      setImage({ assetId, token, url: objectUrl });
    }).catch(() => {
      if (!controller.signal.aborted) setImage(null);
    });
    // 2. 切换场景或身份时撤销旧图并中止请求，避免旧响应覆盖新场景。
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [assetId, token]);

  const visibleImage = image?.assetId === assetId && image.token === token ? image.url : '';
  return (
    <figure className="bh-journal-scene">
      <img
        src={visibleImage || atmosphereUrl}
        alt={visibleImage ? `当前场景插图：${scene?.title || '已知场景'}` : ''}
        onError={() => setImage(null)}
      />
      <figcaption>{scene?.title || '调查手记'}</figcaption>
    </figure>
  );
}
