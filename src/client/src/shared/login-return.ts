export type LoginReturnContext = {
  title: string;
  detail: string;
};

export function describeLoginReturnContext(rawPath: string | null): LoginReturnContext | null {
  if (!rawPath || !rawPath.startsWith('/') || rawPath.startsWith('//')) return null;

  const url = new URL(rawPath, 'https://aikeeper.local');
  if (url.pathname === '/player/join') {
    const room = url.searchParams.get('room')?.trim();
    return {
      title: '登录后返回受邀房间',
      detail: room ? `房间编号：${room}` : '将继续房间加入流程。',
    };
  }

  if (url.pathname === '/host/create') {
    return {
      title: '登录后继续创建房间',
      detail: '你的已填写内容会保留在当前页面流程中。',
    };
  }

  return {
    title: '登录后返回上一页',
    detail: '登录或注册成功后将自动继续原来的流程。',
  };
}
