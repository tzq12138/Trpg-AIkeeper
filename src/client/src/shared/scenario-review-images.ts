export type ImageVisibility = 'host_only' | 'party';
export type ImageTargetType = 'scene' | 'npc' | 'item' | 'clue';

export type ImageSuggestion = {
  target_type: ImageTargetType;
  target_key: string;
  image_summary: string;
  prompt: string;
  style: string;
  visibility: ImageVisibility;
  confidence: number;
  citation: Record<string, unknown>;
  preview?: {
    data_url: string;
    preview_token: string;
    generated_prompt: string;
    mime_type: string;
  };
};

export function normalizeImageSuggestion(value: Record<string, unknown>): ImageSuggestion {
  return {
    target_type: ['scene', 'npc', 'item', 'clue'].includes(String(value.target_type))
      ? String(value.target_type) as ImageTargetType
      : 'scene',
    target_key: String(value.target_key || value.scene_id || ''),
    image_summary: String(value.image_summary || ''),
    prompt: String(value.prompt || ''),
    style: String(value.style || '调查恐怖插画，避免任何文字'),
    visibility: value.visibility === 'party' ? 'party' : 'host_only',
    confidence: Number(value.confidence || 0),
    citation: value.citation && typeof value.citation === 'object'
      ? value.citation as Record<string, unknown>
      : {},
  };
}

export function imageTargetLabel(targetType: ImageTargetType): string {
  return {
    scene: '场景',
    npc: 'NPC',
    item: '物品',
    clue: '线索',
  }[targetType];
}

export function partyVisibleImageNotice(visibility: ImageVisibility): string {
  return visibility === 'party'
    ? '队伍可见时会忽略此处的自由提示词，仅依据场景公开描述重新生成，避免泄露线索或真相。'
    : '';
}
