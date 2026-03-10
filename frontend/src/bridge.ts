export interface ModelInfo {
  id: string;
  name: string;
  description?: string;
}

export interface BridgeState {
  activePage: string;
  currentModel: string;
  cwdPath: string;
  theme: string;
  models: ModelInfo[];
  permissionMode: string;
}

export interface ClawWebBridge {
  state: BridgeState;
  setState(partial: Partial<BridgeState>): void;
  subscribe(listener: () => void): () => void;
  getSnapshot(): BridgeState;
  actions: {
    switchPage: (page: string) => void;
    changeModel: (model: string) => void;
    openCwdPanel: () => void;
    toggleLogPanel: () => void;
    toggleSettings: () => void;
    toggleRightHistory: () => void;
  };
}

declare global {
  interface Window {
    ClawWeb: ClawWebBridge;
    // Existing vanilla JS functions
    switchPage?: (page: string) => void;
    changeModel?: () => void;
    openCwdPanel?: () => void;
    toggleLogPanel?: () => void;
    toggleSettings?: () => void;
    toggleRightHistory?: () => void;
  }
}

const defaultState: BridgeState = {
  activePage: 'chat',
  currentModel: '',
  cwdPath: '加载中...',
  theme: '',
  models: [],
  permissionMode: 'auto',
};

export function createBridge(): ClawWebBridge {
  let state: BridgeState = { ...defaultState };
  const listeners = new Set<() => void>();

  const bridge: ClawWebBridge = {
    get state() {
      return state;
    },

    setState(partial: Partial<BridgeState>) {
      state = { ...state, ...partial };
      listeners.forEach((l) => l());
    },

    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    getSnapshot() {
      return state;
    },

    actions: {
      switchPage(page: string) {
        // Call the vanilla JS function
        window.switchPage?.(page);
      },
      changeModel(model: string) {
        // Update bridge state — React re-renders the select, vanilla JS reads from bridge
        bridge.setState({ currentModel: model });
        window.changeModel?.();
      },
      openCwdPanel() {
        window.openCwdPanel?.();
      },
      toggleLogPanel() {
        window.toggleLogPanel?.();
      },
      toggleSettings() {
        window.toggleSettings?.();
      },
      toggleRightHistory() {
        window.toggleRightHistory?.();
      },
    },
  };

  return bridge;
}
