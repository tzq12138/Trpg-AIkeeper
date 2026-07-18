export const SCENARIO_WORKFLOW_STEPS = [
  { key: 'import', label: '1. 导入授权' },
  { key: 'review', label: '2. AI 编译与审核' },
  { key: 'assets', label: '3. 素材绑定' },
  { key: 'publish', label: '4. 发布开团' },
] as const;

export type ScenarioWorkflowStep = (typeof SCENARIO_WORKFLOW_STEPS)[number]['key'];
