/** Platform adapter — abstracts away platform-specific APIs.
 *
 *  Web uses localStorage + window.location.
 *  React Native would use AsyncStorage + navigation.
 *  Add new implementations by implementing this interface and setting `currentPlatform`.
 */

export interface PlatformAdapter {
  storage: {
    get(key: string): string | null;
    set(key: string, value: string): void;
    remove(key: string): void;
  };
  navigate: (path: string) => void;
}

/** Current platform implementation — defaults to web. */
export let platform: PlatformAdapter = {
  storage: {
    get: (k) => localStorage.getItem(k),
    set: (k, v) => localStorage.setItem(k, v),
    remove: (k) => localStorage.removeItem(k),
  },
  navigate: (path) => {
    window.location.href = path;
  },
};

/** Override platform implementation (e.g. for React Native). */
export function setPlatform(p: PlatformAdapter) {
  platform = p;
}
