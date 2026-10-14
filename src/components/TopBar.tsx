import React from 'react';
import {
  Menu,
  ShieldCheck,
  Bell,
  Sliders,
  Plus,
  Radio,
  Play,
  RotateCcw,
  Sparkles,
  Bot
} from 'lucide-react';
import type { LLMProviderInfo } from '../types';

interface TopBarProps {
  onOpenMobileMenu: () => void;
  onOpenNewTaskModal: () => void;
  onAdvanceDemoStep: () => void;
  onResetDemo: () => void;
  unreadNotificationsCount?: number;
  llmInfo?: LLMProviderInfo | null;
  isBackendConnected?: boolean | null;
}

export const TopBar: React.FC<TopBarProps> = ({
  onOpenMobileMenu,
  onOpenNewTaskModal,
  onAdvanceDemoStep,
  onResetDemo,
  unreadNotificationsCount = 2,
  llmInfo,
  isBackendConnected
}) => {
  const isMock = llmInfo?.provider === 'mock' || llmInfo?.model?.toLowerCase().includes('mock');

  return (
    <header className="app-topbar">
      {/* Left side: Mobile trigger & Project Breadcrumb */}
      <div className="topbar-left">
        <button
          className="mobile-menu-btn"
          onClick={onOpenMobileMenu}
          aria-label="Menüyü Aç"
        >
          <Menu size={20} />
        </button>

        <div className="breadcrumb-wrapper">
          <div className="repo-badge">
            <span className="repo-owner">ogulcannarin</span>
            <span className="repo-slash">/</span>
            <span className="repo-title">ai-dev-team</span>
          </div>

          {isBackendConnected === true ? (
            isMock ? (
              <div className="system-live-pill" style={{ borderColor: 'rgba(234, 179, 8, 0.4)', background: 'rgba(234, 179, 8, 0.12)', color: '#facc15' }} title="Yerel deterministik Mock LLM motoru aktif. Harici API çağrısı yapılmaz.">
                <Bot size={12} className="live-icon" style={{ color: '#eab308' }} />
                <span className="live-text" style={{ color: '#facc15' }}>Mock LLM Modu</span>
                <span className="live-tag" style={{ background: '#eab308', color: '#000', fontWeight: 700 }}>MOCK</span>
              </div>
            ) : (
              <div className="system-live-pill" style={{ borderColor: 'rgba(16, 185, 129, 0.4)', background: 'rgba(16, 185, 129, 0.12)', color: '#10b981' }} title={`Canlı LLM: ${llmInfo?.model || 'OpenAI'}`}>
                <Radio size={12} className="live-icon" style={{ color: '#10b981' }} />
                <span className="live-text" style={{ color: '#10b981' }}>{llmInfo?.model || 'Live LLM'}</span>
                <span className="live-tag" style={{ background: '#10b981', color: '#fff', fontWeight: 700 }}>ONLINE</span>
              </div>
            )
          ) : (
            <div className="system-live-pill">
              <Radio size={12} className="live-icon" />
              <span className="live-text">System Nominal</span>
              <span className="live-tag">STANDBY</span>
            </div>
          )}
        </div>
      </div>

      {/* Right side: Quick Pipeline Demo Controls + New Task + Utility Icons */}
      <div className="topbar-right">
        {/* Quick Simulation Bar Controls */}
        <div className="simulation-controls-bar">
          <button
            className="sim-btn step-btn"
            onClick={onAdvanceDemoStep}
            title="Simülasyonda sonraki pipeline adımına geç"
          >
            <Play size={13} />
            <span>Simulate Step</span>
          </button>

          <button
            className="sim-btn reset-btn"
            onClick={onResetDemo}
            title="Demo durumunu sıfırla"
          >
            <RotateCcw size={13} />
            <span>Reset Demo</span>
          </button>
        </div>

        {/* Primary Action: New Task Button */}
        <button
          id="btn-new-task"
          className="btn-primary-action"
          onClick={onOpenNewTaskModal}
        >
          <Plus size={16} />
          <span>New Task</span>
          <Sparkles size={13} className="btn-sparkle" />
        </button>

        {/* Action Icons */}
        <div className="topbar-icon-group">
          <div className="icon-btn-wrapper" title="Security Agent: 0 Vulnerabilities">
            <button className="topbar-icon-btn" aria-label="Güvenlik Durumu">
              <ShieldCheck size={18} className="shield-icon" />
            </button>
            <span className="security-indicator" />
          </div>

          <div className="icon-btn-wrapper" title="2 Okunmamış Bildirim">
            <button className="topbar-icon-btn" aria-label="Bildirimler">
              <Bell size={18} />
            </button>
            {unreadNotificationsCount > 0 && (
              <span className="notification-badge">{unreadNotificationsCount}</span>
            )}
          </div>

          <div className="icon-btn-wrapper" title="Orkestrasyon Yapılandırması">
            <button className="topbar-icon-btn" aria-label="Ayarlar">
              <Sliders size={18} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
