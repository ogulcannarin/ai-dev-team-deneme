import React from 'react';
import {
  Workflow,
  Bot,
  History,
  ListTodo,
  FolderGit2,
  Settings,
  Cpu,
  GitBranch,
  X
} from 'lucide-react';
import type { NavTab } from '../types';

interface SidebarProps {
  activeTab: NavTab;
  setActiveTab: (tab: NavTab) => void;
  isOpen: boolean;
  onClose: () => void;
}

interface NavItem {
  id: NavTab;
  label: string;
  icon: React.ComponentType<{ className?: string; size?: number }>;
  badge?: string;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  isOpen,
  onClose
}) => {
  const navItems: NavItem[] = [
    { id: 'orchestration', label: 'Orchestration', icon: Workflow },
    { id: 'agents', label: 'Agents', icon: Bot, badge: '5' },
    { id: 'runs', label: 'Runs', icon: History },
    { id: 'tasks', label: 'Tasks', icon: ListTodo, badge: '4' },
    { id: 'files', label: 'Files', icon: FolderGit2 },
    { id: 'settings', label: 'Settings', icon: Settings }
  ];

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-label="Kapat"
        />
      )}

      <aside className={`app-sidebar ${isOpen ? 'open' : ''}`}>
        {/* Top Header / Branding */}
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <div className="brand-icon-wrapper">
              <Cpu size={20} className="brand-icon" />
            </div>
            <div className="brand-info">
              <span className="brand-title">AI Dev Team</span>
              <span className="brand-subtitle">Autonomous Swarm</span>
            </div>
          </div>

          <button
            className="mobile-close-btn"
            onClick={onClose}
            aria-label="Menüyü Kapat"
          >
            <X size={18} />
          </button>
        </div>

        {/* Project Selector Card */}
        <div className="project-badge-card">
          <div className="project-badge-header">
            <span className="project-label">PROJECT</span>
            <span className="project-env-tag">DEMO</span>
          </div>
          <div className="project-name-row">
            <FolderGit2 size={16} className="project-icon" />
            <span className="project-name">ai-dev-team</span>
          </div>
          <div className="project-branch-row">
            <GitBranch size={13} className="branch-icon" />
            <span className="branch-name">main</span>
            <span className="branch-dot" />
            <span className="sync-status">clean</span>
          </div>
        </div>

        {/* Navigation Section */}
        <div className="sidebar-nav-section">
          <div className="nav-section-title">NAVIGATION</div>
          <nav className="sidebar-nav">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  id={`nav-btn-${item.id}`}
                  onClick={() => {
                    setActiveTab(item.id);
                    onClose();
                  }}
                  className={`nav-item-btn ${isActive ? 'active' : ''}`}
                >
                  <div className="nav-item-left">
                    <Icon size={18} className="nav-icon" />
                    <span className="nav-label">{item.label}</span>
                  </div>
                  {item.badge && (
                    <span className={`nav-badge ${isActive ? 'active' : ''}`}>
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Pipeline Status Summary in Footer */}
        <div className="sidebar-footer">
          <div className="orchestrator-status-box">
            <div className="status-indicator-row">
              <span className="pulse-dot green" />
              <span className="status-text">Orchestrator v2.4</span>
            </div>
            <div className="status-subtext">5 Agents Ready • 1 Task Active</div>
          </div>
        </div>
      </aside>
    </>
  );
};
