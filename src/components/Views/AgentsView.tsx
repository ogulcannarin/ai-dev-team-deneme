import React from 'react';
import type { Agent } from '../../types';
import { Bot, Cpu } from 'lucide-react';

interface AgentsViewProps {
  agents: Agent[];
  onSelectAgent: (agent: Agent) => void;
}

export const AgentsView: React.FC<AgentsViewProps> = ({ agents, onSelectAgent }) => {
  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 className="view-title">Agent Swarm Registry</h2>
          <p className="view-subtitle">
            Yazılım geliştirme sürecinde aktif görev alan tüm otonom ajanların durumu ve telemetrisi
          </p>
        </div>
        <div className="view-badge-tag">
          <Cpu size={14} />
          <span>5 Active Units • Demo</span>
        </div>
      </div>

      <div className="agents-grid-view">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className="agent-detail-card"
            onClick={() => onSelectAgent(agent)}
            role="button"
            tabIndex={0}
          >
            <div className="card-top-header">
              <div className="agent-identity">
                <div className={`agent-avatar-box color-${agent.accentColor}`}>
                  <Bot size={18} />
                </div>
                <div>
                  <h3 className="card-agent-name">{agent.name}</h3>
                  <span className="card-agent-role">{agent.role}</span>
                </div>
              </div>
              <span className={`status-pill ${agent.status}`}>
                {agent.status}
              </span>
            </div>

            <p className="card-desc">{agent.description}</p>

            <div className="card-stats-grid">
              <div className="stat-pill">
                <span className="stat-name">Model</span>
                <span className="stat-val">{agent.model ? agent.model.split(' ')[0] : '—'}</span>
              </div>
              <div className="stat-pill">
                <span className="stat-name">Token</span>
                <span className="stat-val">{agent.totalTokens}</span>
              </div>
              <div className="stat-pill">
                <span className="stat-name">Gecikme</span>
                <span className="stat-val">{agent.latencyMs}ms</span>
              </div>
              <div className="stat-pill">
                <span className="stat-name">Başarı</span>
                <span className="stat-val text-green">{agent.successRate}</span>
              </div>
            </div>

            <div className="card-skills-section">
              <span className="skills-heading">Yetkinlikler:</span>
              <div className="skills-wrap">
                {agent.capabilities.map((cap, i) => (
                  <span key={i} className="skill-mini-tag">
                    {cap}
                  </span>
                ))}
              </div>
            </div>

            <div className="card-footer-action">
              <span className="inspect-btn-text">Ayrıntıları İncele & Prompt Gör &rarr;</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
