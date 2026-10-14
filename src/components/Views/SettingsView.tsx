import React from 'react';
import { ShieldCheck, Cpu } from 'lucide-react';

export const SettingsView: React.FC = () => {
  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <h2 className="view-title">Orchestration & Swarm Settings</h2>
          <p className="view-subtitle">
            AI Agent orkestrasyon kuralları, model atamaları ve güvenlik yapılandırması
          </p>
        </div>
      </div>

      <div className="settings-grid">
        {/* Model Configurations */}
        <div className="settings-card">
          <div className="settings-card-header">
            <Cpu size={18} className="settings-icon" />
            <h3 className="settings-card-title">Model Profiles (Demo)</h3>
          </div>
          <p className="settings-card-desc">
            Her geliştirme aşamasında atanacak birincil ve yedek LLM modelleri.
          </p>

          <div className="settings-field-group">
            <div className="settings-field">
              <label className="field-label">Architect Model</label>
              <select className="field-select" defaultValue="claude-3-7">
                <option value="claude-3-7">Claude 3.7 Sonnet (Thinking)</option>
                <option value="deepseek-r1">DeepSeek R1 Architecture</option>
                <option value="gemini-3-7">Gemini 3.7 Pro</option>
              </select>
            </div>

            <div className="settings-field">
              <label className="field-label">Coder Agent Model</label>
              <select className="field-select" defaultValue="gemini-3-7-flash">
                <option value="gemini-3-7-flash">Gemini 3.7 Flash Thinking</option>
                <option value="claude-3-7">Claude 3.7 Sonnet Code</option>
                <option value="gpt-4-5">GPT-4.5 Turbo</option>
              </select>
            </div>

            <div className="settings-field">
              <label className="field-label">Test Agent Model</label>
              <select className="field-select" defaultValue="gpt-4-5">
                <option value="gpt-4-5">GPT-4.5 Turbo (Testing suite)</option>
                <option value="gemini-3-7">Gemini 3.7 Flash</option>
              </select>
            </div>
          </div>
        </div>

        {/* Security & Isolation */}
        <div className="settings-card">
          <div className="settings-card-header">
            <ShieldCheck size={18} className="settings-icon" />
            <h3 className="settings-card-title">Security & Sandboxing</h3>
          </div>
          <p className="settings-card-desc">
            Otomatik dosya düzenleme ve komut yürütme izin politikaları.
          </p>

          <div className="settings-toggle-list">
            <div className="toggle-row">
              <div>
                <span className="toggle-title">Strict AST Validation</span>
                <p className="toggle-sub">Kod yamaları uygulanmadan önce TypeScript AST denetimi yap</p>
              </div>
              <input type="checkbox" defaultChecked className="toggle-checkbox" />
            </div>

            <div className="toggle-row">
              <div>
                <span className="toggle-title">Secret Leak Interceptor</span>
                <p className="toggle-sub">API key veya token sızıntılarını PR aşamasında engelle</p>
              </div>
              <input type="checkbox" defaultChecked className="toggle-checkbox" />
            </div>

            <div className="toggle-row">
              <div>
                <span className="toggle-title">Autonomous Git Commit</span>
                <p className="toggle-sub">Testler geçtikten sonra hedef branch'e otomatik commit at</p>
              </div>
              <input type="checkbox" defaultChecked className="toggle-checkbox" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
