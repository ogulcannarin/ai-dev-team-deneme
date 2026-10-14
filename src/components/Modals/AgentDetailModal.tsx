import React from 'react';
import {
  X,
  Bot,
  Activity,
  Code2,
  CheckCircle2,
  Shield,
  BookOpen,
  Zap,
  Clock,
  Sparkles,
  Info
} from 'lucide-react';
import type { Agent } from '../../types';

interface AgentDetailModalProps {
  agent: Agent | null;
  onClose: () => void;
  onPingAgent?: (agent: Agent) => void;
}

export const AgentDetailModal: React.FC<AgentDetailModalProps> = ({
  agent,
  onClose,
  onPingAgent
}) => {
  if (!agent) return null;

  const getAgentIcon = (id: string) => {
    switch (id) {
      case 'agent-architect':
        return <Activity size={24} />;
      case 'agent-coder':
        return <Code2 size={24} />;
      case 'agent-test':
        return <CheckCircle2 size={24} />;
      case 'agent-security':
        return <Shield size={24} />;
      case 'agent-docs':
        return <BookOpen size={24} />;
      default:
        return <Bot size={24} />;
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card modal-medium"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-modal-title"
      >
        {/* Modal Header */}
        <div className="modal-header">
          <div className="agent-modal-header-profile">
            <div
              className={`agent-avatar-large color-${agent.accentColor}`}
              style={{ borderColor: agent.avatarColor }}
            >
              {getAgentIcon(agent.id)}
            </div>
            <div>
              <div className="agent-modal-name-row">
                <h3 id="agent-modal-title" className="agent-modal-title">
                  {agent.name}
                </h3>
                <span className={`status-pill ${agent.status}`}>
                  {agent.status.toUpperCase()}
                </span>
              </div>
              <p className="agent-modal-role">{agent.role}</p>
            </div>
          </div>

          <button
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Kapat"
          >
            <X size={18} />
          </button>
        </div>

        {/* Demo Tag */}
        <div className="modal-demo-banner">
          <Info size={15} className="demo-banner-icon" />
          <div className="demo-banner-text">
            <strong>Agent Telemetrisi (Demo):</strong> Gösterilen metrikler, model
            parametreleri ve prompt şablonları simülasyon amaçlıdır.
          </div>
        </div>

        <div className="agent-modal-body">
          {/* Metrics Grid */}
          <div className="agent-metrics-grid">
            <div className="metric-box">
              <span className="metric-title">Model</span>
              <span className="metric-value">{agent.model}</span>
            </div>
            <div className="metric-box">
              <span className="metric-title">İşlenen Token</span>
              <span className="metric-value">{agent.totalTokens}</span>
            </div>
            <div className="metric-box">
              <span className="metric-title">Yanıt Gecikmesi</span>
              <span className="metric-value">{agent.latencyMs} ms</span>
            </div>
            <div className="metric-box">
              <span className="metric-title">Başarı Oranı</span>
              <span className="metric-value success-text">{agent.successRate}</span>
            </div>
          </div>

          {/* Description */}
          <div className="modal-section">
            <h4 className="section-title">Görev Tanımı</h4>
            <p className="section-text">{agent.description}</p>
          </div>

          {/* Capabilities */}
          <div className="modal-section">
            <h4 className="section-title">Temel Yetkinlikler (Skills)</h4>
            <div className="capabilities-tags">
              {agent.capabilities.map((cap, i) => (
                <span key={i} className="skill-chip">
                  <Sparkles size={12} />
                  <span>{cap}</span>
                </span>
              ))}
            </div>
          </div>

          {/* System Prompt Summary */}
          <div className="modal-section">
            <h4 className="section-title">Sistem Prompt Şablonu (Özet)</h4>
            <div className="system-prompt-box">
              <code>{agent.systemPromptSummary}</code>
            </div>
          </div>

          {/* Last Activity */}
          <div className="modal-section">
            <h4 className="section-title">Son Etkinlik Günlüğü</h4>
            <div className="activity-journal-item">
              <Clock size={14} className="journal-icon" />
              <div>
                <span className="journal-time">{agent.lastActivityTime}</span>
                <p className="journal-msg">{agent.lastActivity}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="modal-footer">
          <button type="button" className="btn-modal-cancel" onClick={onClose}>
            Kapat
          </button>
          {onPingAgent && (
            <button
              type="button"
              className="btn-modal-submit"
              onClick={() => {
                onPingAgent(agent);
                onClose();
              }}
            >
              <Zap size={15} />
              <span>Simulate Agent Ping</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
