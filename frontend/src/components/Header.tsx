import { FolderOpen, History } from 'lucide-react';
import { useBridge } from '../hooks/useBridge';

export function Header() {
  const { currentModel, cwdPath, models, permissionMode } = useBridge();
  const bridge = window.ClawWeb;

  const displayCwd = cwdPath
    ? cwdPath.split('/').slice(-2).join('/') || cwdPath
    : '加载中...';

  return (
    <header className="header">
      <h1>Claude Web Chat</h1>
      <div className="header-controls">
        <div
          className="cwd-display"
          id="cwdDisplay"
          onClick={() => bridge.actions.openCwdPanel()}
          title="点击切换工作目录"
        >
          <span><FolderOpen size={14} /></span>
          <span id="cwdPath">{displayCwd}</span>
        </div>
        <select
          className="model-select"
          id="modelSelect"
          value={currentModel}
          onChange={(e) => bridge.actions.changeModel(e.target.value)}
          title="选择模型"
        >
          {models.length > 0 ? (
            models.map((m) => (
              <option key={m.id} value={m.id} title={m.description || ''}>
                {m.name}
              </option>
            ))
          ) : (
            <option value="claude-sonnet-4-6">Sonnet 4.6</option>
          )}
        </select>
        <select
          className="permission-select"
          id="permissionModeSelect"
          value={permissionMode}
          onChange={(e) => {
            bridge.setState({ permissionMode: e.target.value });
          }}
          title="权限模式"
        >
          <option value="auto">自动执行</option>
          <option value="acceptEdits">自动编辑</option>
          <option value="safe">安全模式</option>
        </select>
        <button
          className="header-btn"
          onClick={() => bridge.actions.toggleRightHistory()}
          title="历史对话"
          style={{ fontSize: '16px' }}
        >
          <History size={16} />
        </button>
      </div>
    </header>
  );
}
