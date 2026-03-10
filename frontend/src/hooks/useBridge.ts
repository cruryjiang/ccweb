import { useSyncExternalStore } from 'react';
import type { BridgeState } from '../bridge';

export function useBridge(): BridgeState {
  const bridge = window.ClawWeb;
  return useSyncExternalStore(
    bridge.subscribe,
    bridge.getSnapshot,
  );
}
