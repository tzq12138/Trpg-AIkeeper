import { describe, expect, test } from 'vitest';
import { getRouteForPath, hostTabs, playerTabs } from '../src/navigation';

describe('navigation configuration', () => {
  test('parses existing app routes without a router dependency', () => {
    expect(getRouteForPath('/')).toEqual({ page: 'home', param: '' });
    expect(getRouteForPath('/admin')).toEqual({ page: 'admin', param: '' });
    expect(getRouteForPath('/rag-test')).toEqual({ page: 'rag-test', param: '' });
    expect(getRouteForPath('/host/create')).toEqual({ page: 'host-create', param: '' });
    expect(getRouteForPath('/host/ABCD/stage')).toEqual({ page: 'host-stage', param: 'ABCD' });
    expect(getRouteForPath('/host/ABCD')).toEqual({ page: 'host-lobby', param: 'ABCD' });
    expect(getRouteForPath('/player/join')).toEqual({ page: 'player-join', param: '' });
    expect(getRouteForPath('/player/ABCD')).toEqual({ page: 'player-action', param: 'ABCD' });
    expect(getRouteForPath('/player/ABCD/lobby')).toEqual({ page: 'player-lobby', param: 'ABCD' });
  });

  test('exposes the current host and player tabs', () => {
    expect(hostTabs.map((tab) => tab.key)).toEqual(['narrative', 'combat', 'database', 'logs', 'map']);
    expect(playerTabs.map((tab) => tab.key)).toEqual(['home', 'action', 'character', 'inventory', 'logs', 'map']);
  });
});
