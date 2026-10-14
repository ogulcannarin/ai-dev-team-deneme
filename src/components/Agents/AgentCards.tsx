import React from 'react';
import {
  Bot,
  Activity,
  Code2,
  Shield,
  BookOpen,
  CheckCircle2,
  Loader2,
  Clock,
  Info,
  ChevronRight
} from 'lucide-react';
import type { Agent, AgentStatus } from '../../types';

interface AgentCardsProps {
  agents: Agent[];
  onSelectAgent: (agent: Agent) => void;
  selectedAgentId?: string;
}

export const AgentCards: React.FC<AgentCardsProps> = ({
  agents,
  onSelectAgent,
  selectedAgentId
}) => {
  const getAgentIcon = (id: string) => {
    switch (id) {
      case 'agent-architect':
        return <Activity size={16} />;
      case 'agent-coder':
        return <Code2 size={16} />;
      case 'agent-test':
        return <CheckCircle2 size={16} />;
      case 'agent-security':
        return <Shield size={16} />;
      case 'agent-docs':
        return <BookOpen size={16} />;
      default:
        return <Bot size={16} />;
    }
  };

  const getStatusBadge = (status: AgentStatus) => {
    switch (status) {
      case 'running':
        return (
          <span className="agent-status-badge running">
            <Loader2 size={12} className="spinning" />
            <span>Running</span>
          </span>
        );
      case 'completed':
        return (
          <span className="agent-status-badge completed">
            <CheckCircle2 size={12} />
            <span>Active</span>
          </span>
        );
      case 'idle':
        return (
          <span className="agent-status-badge idle">
            <span className="dot idle-dot" />
            <span>Idle</span>
          </span>
        );
      case 'standby':
      default:
        return (
          <span className="agent-status-badge standby">
            <Clock size={12} />
            <span>Standby</span>
          </span>
        );
    }
  };

  return (
    <div className="agent-panel-container">
      {/* Panel Header */}
      <div className="agent-panel-header">
        <div className="agent-panel-title-row">
          <div className="agent-title-icon-box">
            <Bot size={18} className="agent-header-icon" />
          </div>
          <div>
            <h3 className="agent-panel-title">Agent Activity</h3>
            <p className="agent-panel-subtitle">
              Orkestre edilen 5 otonom yapay zekâ birimi
            </p>
          </div>
        </div>

        {/* Demo Mode Notice Tag */}
        <div className="demo-notice-tag" title="Demo verisi: Gerçek agent backend bağlantısı simülasyon modundadır">
          <Info size={12} />
          <span>Demo Data</span>
        </div>
      </div>

      {/* Agents Cards List */}
      <div className="agents-cards-list">
        {agents.map((agent) => {
          const isSelected = agent.id === selectedAgentId;
          const isRunning = agent.status === 'running';

          return (
            <div
              key={agent.id}
              id={`agent-card-${agent.id}`}
              className={`agent-card ${isRunning ? 'running-pulse' : ''} ${
                isSelected ? 'selected' : ''
              }`}
              onClick={() => onSelectAgent(agent)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  onSelectAgent(agent);
                }
              }}
            >
              {/* Top Row: Icon + Name + Status */}
              <div className="agent-card-top">
                <div className="agent-identity">
                  <div
                    className={`agent-avatar-box color-${agent.accentColor}`}
                    style={{ borderColor: agent.avatarColor }}
                  >
                    {getAgentIcon(agent.id)}
                  </div>
                  <div className="agent-name-role">
                    <h4 className="agent-card-name">{agent.name}</h4>
                    <span className="agent-card-role">{agent.role}</span>
                  </div>
                </div>

                {getStatusBadge(agent.status)}
              </div>

              {/* Middle: Short Task / Capability Description */}
              <p className="agent-card-desc">{agent.description}</p>

              {/* Bottom: Last Activity Info */}
              <div className="agent-activity-box">
                <div className="activity-label-row">
                  <span className="activity-label">Son Etkinlik</span>
                  <span className="activity-time">{agent.lastActivityTime}</span>
                </div>
                <div className="activity-text-line" title={agent.lastActivity}>
                  {agent.lastActivity}
                </div>
              </div>

              {/* Quick Specs Footer */}
              <div className="agent-card-footer">
                <div className="agent-spec-item">
                  <span className="spec-label">Model:</span>
                  <span className="spec-value">{agent.model ? agent.model.split(' ')[0] : '—'}</span>
                </div>
                <div className="agent-spec-item">
                  <span className="spec-label">Tokens:</span>
                  <span className="spec-value">{agent.totalTokens}</span>
                </div>
                <div className="inspect-arrow">
                  <ChevronRight size={14} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Panel Bottom Demo Disclaimer */}
      <div className="agent-panel-footer">
        <div className="demo-disclaimer-box">
          <Info size={13} className="disclaimer-icon" />
          <p className="disclaimer-text">
            <strong>Demo Modu:</strong> Agent telemetrisi ve etkinlik akışı arayüz
            prototipi için istemci tarafında simüle edilmektedir.
          </p>
        </div>
      </div>
    </div>
  );
};
