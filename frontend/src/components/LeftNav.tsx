import {
  MessageSquare,
  Presentation,
  FileText,
  Code2,
  ScrollText,
  Settings,
} from 'lucide-react';
import { useBridge } from '../hooks/useBridge';

interface NavPageItem {
  page: string;
  icon: React.ReactNode;
  label: string;
}

const topItems: NavPageItem[] = [
  { page: 'chat', icon: <MessageSquare size={20} />, label: '对话' },
  { page: 'ppt', icon: <Presentation size={20} />, label: 'PPT助手' },
];

const middleItems: NavPageItem[] = [
  { page: 'yuque', icon: <FileText size={20} />, label: '语雀助手' },
  { page: 'coder', icon: <Code2 size={20} />, label: '编码助手' },
];

export function LeftNav() {
  const { activePage } = useBridge();
  const bridge = window.ClawWeb;

  return (
    <>
      {topItems.map((item) => (
        <div
          key={item.page}
          className={`nav-item${activePage === item.page ? ' active' : ''}`}
          data-page={item.page}
          onClick={() => bridge.actions.switchPage(item.page)}
          title={item.label}
        >
          {item.icon}
          <span className="nav-tooltip">{item.label}</span>
        </div>
      ))}

      <div className="nav-divider" />

      {middleItems.map((item) => (
        <div
          key={item.page}
          className={`nav-item${activePage === item.page ? ' active' : ''}`}
          data-page={item.page}
          onClick={() => bridge.actions.switchPage(item.page)}
          title={item.label}
        >
          {item.icon}
          <span className="nav-tooltip">{item.label}</span>
        </div>
      ))}

      <div className="nav-spacer" />
      <div className="nav-divider" />

      <div
        className="nav-item"
        onClick={() => bridge.actions.toggleLogPanel()}
        title="日志"
      >
        <ScrollText size={20} />
        <span className="nav-tooltip">日志</span>
      </div>
      <div
        className="nav-item"
        onClick={() => bridge.actions.toggleSettings()}
        title="设置"
      >
        <Settings size={20} />
        <span className="nav-tooltip">设置</span>
      </div>
    </>
  );
}
