import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, test } from 'vitest';


function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key: string) { return store.get(key) ?? null; },
    key(index: number) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key: string) { store.delete(key); },
    setItem(key: string, value: string) { store.set(key, value); },
  };
}

Object.defineProperty(globalThis, 'localStorage', {
  value: createStorageMock(),
  configurable: true,
});


describe('CampaignHomePanel', () => {
  test('renders the player campaign return and collaboration sections', async () => {
    const { default: CampaignHomePanel } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(<CampaignHomePanel roomId="room-1" />);

    expect(html).toContain('战役回流');
    expect(html).toContain('本场状态');
    expect(html).toContain('引用依据');
    expect(html).toContain('新增个人目标');
    expect(html).toContain('Session Zero');
    expect(html).toContain('私人笔记');
    expect(html).toContain('队伍证据板');
  });

  test('shows the current Session Zero risk contract version and does not accept a stale confirmation', async () => {
    const { SessionZeroPanel } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <SessionZeroPanel
        sessionZero={{
          steps: [
            { step: 'character_rules', confirmed: true, confirmed_at: '2026-08-02T10:00:00Z' },
            { step: 'safety', confirmed: false, confirmed_at: null },
            { step: 'ai_host', confirmed: false, confirmed_at: null },
          ],
          complete: false,
          risk_contract: {
            schema_version: 'risk_contract.v1',
            contract_hash: 'hash-current',
            categories: [{ category: 'body_horror', max_level: 'medium' }],
            excluded_tags: ['sexual_violence'],
            default_harm: { npc: 'medium', scene: 'low' },
            irreversible_controls: ['character_death'],
            hidden_checks_allowed: false,
            safe_alternative_tags: ['sexual_violence'],
            safe_abort_available: true,
          },
        }}
        error="安全边界版本已更新，请重新确认。"
        onConfirm={() => {}}
      />,
    );

    expect(html).toContain('risk_contract.v1');
    expect(html).toContain('body_horror：中');
    expect(html).toContain('sexual_violence');
    expect(html).toContain('安全边界版本已更新，请重新确认');
    expect(html).toContain('安全边界');
    expect(html).not.toContain('Session Zero 已完成');
  });

  test('renders the persisted campaign archive ending card after completion', async () => {
    const { CampaignEndingCard } = await import('../src/pages/PlayerLobby');
    const html = renderToStaticMarkup(
      <CampaignEndingCard
        ending={{
          ending_type: 'mixed',
          summary: '调查员阻止了仪式，但真相仍留下代价。',
          highlights: ['找到了失踪档案', '四名调查员全部存活'],
        }}
      />,
    );

    expect(html).toContain('混合结局');
    expect(html).toContain('调查员阻止了仪式');
    expect(html).toContain('四名调查员全部存活');
  });

  test('renders the current solo entry with a continue action', async () => {
    const { CampaignCurrentSceneCard } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <CampaignCurrentSceneCard
        scene={{
          node_id: '1',
          title: '条目 1',
          text_preview: '太阳高悬，你正在汽车站等车。',
          citation: {
            label: '开场场景',
            page: 4,
            scene: '奥斯本药店',
            verified: true,
          },
          choice_count: 1,
          image_asset_id: 'opening-image',
        }}
        onContinue={() => {}}
      />,
    );

    expect(html).toContain('当前场景');
    expect(html).not.toContain('条目 1');
    expect(html).toContain('太阳高悬');
    expect(html).toContain('继续当前场景');
    expect(html).toContain('1 个可选方向');
    expect(html).toContain('依据已校验');
    expect(html).toContain('开场场景');
    expect(html).toContain('第 4 页');
    expect(html).toContain('奥斯本药店');
    expect(html).not.toContain('source_ref');
    expect(html).not.toContain('向火独行.pdf');
    expect(html).toContain('/api/player/assets/opening-image');
    expect(html).toContain('当前场景插图');
  });

  test('renders owned clues and shared summaries without exposing unavailable text', async () => {
    const { CampaignRecentClues } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <CampaignRecentClues
        clues={[
          {
            clue_id: 'own-clue',
            text: '我在窗边看到了血迹。',
            discovered_at: '2026-07-19T10:00:00Z',
            is_owner: true,
            is_shared: false,
          },
          {
            clue_id: 'shared-clue',
            text: '队伍摘要：办公室有异常脚印。',
            discovered_at: '2026-07-19T10:01:00Z',
            is_owner: false,
            is_shared: true,
          },
        ]}
      />,
    );

    expect(html).toContain('最近线索');
    expect(html).toContain('我的发现');
    expect(html).toContain('队伍分享摘要');
    expect(html).toContain('我在窗边看到了血迹。');
    expect(html).toContain('队伍摘要：办公室有异常脚印。');
    expect(html).not.toContain('凶手真实身份');
  });

  test('shows at most three party unresolved questions on the campaign home', async () => {
    const { CampaignUnresolvedQuestions } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <CampaignUnresolvedQuestions
        questions={Array.from({ length: 4 }, (_, index) => ({
          evidence_card_id: `question-${index + 1}`,
          title: `待调查问题 ${index + 1}`,
          fact_status: 'hypothesis',
        }))}
      />,
    );

    expect(html).toContain('待调查问题 1');
    expect(html).toContain('待调查问题 3');
    expect(html).not.toContain('待调查问题 4');
  });

  test('renders explicit question lifecycle actions without changing its fact status', async () => {
    const { PartyQuestionCard } = await import('../src/components/CampaignHomePanel');
    const card = {
      evidence_card_id: 'question-1',
      title: '谁拿走了钥匙？',
      body: '仍需要继续调查。',
      card_type: 'question' as const,
      fact_status: 'hypothesis' as const,
      visibility: 'party' as const,
      source: 'player' as const,
      confirmed_by: null,
      created_by_character_id: 'character-1',
      version: 1,
      created_at: '2026-07-19T10:00:00Z',
      updated_at: '2026-07-19T10:00:00Z',
      question_status: 'investigating' as const,
    };
    const investigating = renderToStaticMarkup(
      <PartyQuestionCard card={card} undoAvailable={false} onMarkExplained={() => {}} onPreviewClose={() => {}} onReopen={() => {}} />,
    );
    const closed = renderToStaticMarkup(
      <PartyQuestionCard card={{ ...card, question_status: 'closed' }} undoAvailable onMarkExplained={() => {}} onPreviewClose={() => {}} onReopen={() => {}} />,
    );

    expect(investigating).toContain('猜测');
    expect(investigating).toContain('待调查');
    expect(investigating).toContain('标记已有解释');
    expect(investigating).toContain('关闭问题');
    expect(investigating).not.toContain('重新打开');
    expect(closed).toContain('已关闭');
    expect(closed).toContain('撤销关闭');
    expect(closed).not.toContain('标记已有解释');
  });

  test('renders an editable party-copy form for a private evidence card', async () => {
    const { EvidenceShareEditor } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <EvidenceShareEditor
        card={{
          evidence_card_id: 'private-card-1',
          title: '我的私人推测',
          body: '不要直接公开这段原文。',
          card_type: 'person',
          fact_status: 'hypothesis',
          visibility: 'private',
          source: 'player',
          confirmed_by: null,
          created_by_character_id: 'character-1',
          version: 1,
          created_at: '2026-07-19T10:00:00Z',
          updated_at: '2026-07-19T10:00:00Z',
        }}
        title="给队伍的推测"
        body="请留意馆长的反应。"
        onTitleChange={() => {}}
        onBodyChange={() => {}}
        onSubmit={() => {}}
        onCancel={() => {}}
      />,
    );

    expect(html).toContain('分享为队伍副本');
    expect(html).toContain('给队伍的推测');
    expect(html).toContain('保存队伍副本');
    expect(html).toContain('原私人卡不会被修改');
  });

  test('renders collaboration controls without a vote action for shared hypotheses', async () => {
    const { SharedHypothesisCollaboration } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <SharedHypothesisCollaboration
        comments={[{ evidence_card_id: 'party-copy-1', body: '护士证词支持这个推测。', author_name: '第二位调查员' }]}
        draft="补充相关资料"
        onDraftChange={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(html).toContain('支持资料');
    expect(html).toContain('矛盾资料');
    expect(html).toContain('相关资料');
    expect(html).toContain('第二位调查员');
    expect(html).toContain('添加评论');
    expect(html).not.toContain('投票');
  });

  test('renders explicit shared-hypothesis status controls and a short undo window', async () => {
    const { SharedHypothesisStatusControls } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <SharedHypothesisStatusControls
        status="disproved"
        undoAvailable
        onStatusChange={() => {}}
        onApply={() => {}}
        onRevert={() => {}}
      />,
    );

    expect(html).toContain('讨论中');
    expect(html).toContain('已证伪');
    expect(html).toContain('已搁置');
    expect(html).toContain('更新状态');
    expect(html).toContain('撤销状态更改');
    expect(html).toContain('AI 只能提出建议');
  });

  test('offers only party-visible material as optional hypothesis context', async () => {
    const { RelatedEvidenceSelector } = await import('../src/components/CampaignHomePanel');
    const baseCard = {
      body: '',
      card_type: 'clue' as const,
      fact_status: 'hypothesis' as const,
      source: 'player' as const,
      confirmed_by: null,
      created_by_character_id: 'character-1',
      version: 1,
      created_at: '2026-07-19T10:00:00Z',
      updated_at: '2026-07-19T10:00:00Z',
    };
    const html = renderToStaticMarkup(
      <RelatedEvidenceSelector
        cards={[
          { ...baseCard, evidence_card_id: 'party-card', title: '公开线索', visibility: 'party' as const },
          { ...baseCard, evidence_card_id: 'private-card', title: '私人原稿', visibility: 'private' as const },
        ]}
        selectedCardIds={['party-card']}
        onToggle={() => {}}
      />,
    );

    expect(html).toContain('可选关联资料');
    expect(html).toContain('公开线索');
    expect(html).not.toContain('私人原稿');
    expect(html).toContain('不会提示“正确证据”');
  });

  test('renders a read-only AI disproof suggestion that requires player confirmation', async () => {
    const { HypothesisDisproofSuggestionCard } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <HypothesisDisproofSuggestionCard
        suggestion={{
          suggestedStatus: 'possible_disproved',
          reason: '这条已确认资料与假说矛盾。',
          factIds: ['fact-1'],
          confidence: 'medium',
          requiresPlayerConfirmation: true,
        }}
        factTitles={['已确认的公开资料']}
        onCheck={() => {}}
        onFillDisproved={() => {}}
      />,
    );

    expect(html).toContain('检查已确认事实');
    expect(html).toContain('可能已证伪');
    expect(html).toContain('仅建议，未更改状态');
    expect(html).toContain('填入“已证伪”');
    expect(html).toContain('已确认的公开资料');
  });

  test('renders the four-section investigation detail with only player-safe material', async () => {
    const { InvestigationDetailCard } = await import('../src/components/CampaignHomePanel');
    const html = renderToStaticMarkup(
      <InvestigationDetailCard
        detail={{
          summary: {
            evidence_card_id: 'clue-1',
            title: '走廊血迹',
            body: '血迹通往地下室。',
            card_type: 'clue',
            fact_status: 'confirmed',
            visibility: 'private',
            source: 'system',
            confirmed_by: 'system',
            created_by_character_id: null,
            version: 1,
            created_at: '2026-07-19T10:00:00Z',
            updated_at: '2026-07-19T10:00:00Z',
          },
          current_known: [{
            evidence_card_id: 'clue-1',
            title: '走廊血迹',
            body: '血迹通往地下室。',
            cognitive_tag: '已确认',
          }],
          related_materials: [{
            evidence_card_id: 'clue-2',
            title: '地下室传闻',
            body: '有人听见脚步声。',
            cognitive_tag: 'NPC 证词',
          }],
          player_notes: [{
            note_id: 'note-1',
            title: '我的判断',
            body: '先检查地下室入口。',
          }],
        }}
        onAddNote={() => {}}
        onShare={() => {}}
      />,
    );

    expect(html).toContain('资料详情：走廊血迹');
    expect(html).toContain('<details open=""');
    expect(html).toContain('摘要');
    expect(html).toContain('当前已知 · 1 条');
    expect(html).toContain('相关资料 · 1 项');
    expect(html).toContain('玩家笔记 · 1 条');
    expect(html).toContain('已确认');
    expect(html).toContain('NPC 证词');
    expect(html).toContain('加入笔记');
    expect(html).toContain('分享给队伍');
    expect(html).toContain('更多');
    expect(html).not.toContain('关键程度');
    expect(html).not.toContain('隐藏线索');
  });
});
