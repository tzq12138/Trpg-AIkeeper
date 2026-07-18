import { describe, expect, it } from 'vitest';
import { describeLoginReturnContext } from '../src/shared/login-return';

describe('describeLoginReturnContext', () => {
  it('describes a player invitation without exposing unrelated query data', () => {
    expect(describeLoginReturnContext('/player/join?room=ab12cd34&token=hidden')).toEqual({
      title: '登录后返回受邀房间',
      detail: '房间编号：ab12cd34',
    });
  });

  it('keeps generic destinations concise', () => {
    expect(describeLoginReturnContext('/host/create')).toEqual({
      title: '登录后继续创建房间',
      detail: '你的已填写内容会保留在当前页面流程中。',
    });
  });
});
