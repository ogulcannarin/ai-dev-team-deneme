import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  GitBranch,
  AlertCircle,
  Play,
  CheckCircle2,
  FileCode2,
  Cpu,
  Loader2,
  Server,
  Target,
  Bot
} from 'lucide-react';
import { createBackendTask, runBackendTask, getLLMInfo, ApiError } from '../../services/api';
import type { BackendTask, LLMProviderInfo } from '../../types';

interface NewTaskModalProps {
  isOpen: boolean;
  onClose: () => void;
  onTaskCreated: (backendTask: BackendTask, extraInfo?: {
    title: string;
    priority: 'low' | 'medium' | 'high' | 'critical';
    branch: string;
    selectedAgents: string[];
  }) => void;
}

export const NewTaskModal: React.FC<NewTaskModalProps> = ({
  isOpen,
  onClose,
  onTaskCreated
}) => {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<'low' | 'medium' | 'high' | 'critical'>('high');
  const [branch, setBranch] = useState('feat/user-auth-rate-limit');
  const [plannerMode, setPlannerMode] = useState<'deterministic' | 'llm'>('deterministic');
  const [coderMode, setCoderMode] = useState<'deterministic' | 'llm'>('deterministic');
  const [llmInfo, setLlmInfo] = useState<LLMProviderInfo | null>(null);
  const [selectedAgents, setSelectedAgents] = useState<string[]>([
    'agent-architect',
    'agent-coder',
    'agent-test'
  ]);
  const [autoRunWorkflow, setAutoRunWorkflow] = useState(true);
  const [requireHumanApproval, setRequireHumanApproval] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [createdSuccess, setCreatedSuccess] = useState<BackendTask | null>(null);

  useEffect(() => {
    if (isOpen) {
      getLLMInfo()
        .then((info) => {
          setLlmInfo(info);
          if (info.default_planner_mode === 'llm') {
            setPlannerMode('llm');
          }
          if (info.default_coder_mode === 'llm') {
            setCoderMode('llm');
          }
        })
        .catch(() => {
          setLlmInfo(null);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const isMockProvider = llmInfo?.provider === 'mock' || llmInfo?.model?.toLowerCase().includes('mock');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedDesc = description.trim();
    if (!trimmedDesc) {
      setError('Lütfen görev gereksinimlerini veya açıklamasını girin (Açıklama boş olamaz).');
      return;
    }

    const taskTitle = title.trim() || trimmedDesc.slice(0, 50);

    setError(null);
    setIsLoading(true);
    setLoadingStep('1/2 Görev kaydediliyor (POST /tasks)...');

    try {
      // 1. POST /tasks
      const initialTask = await createBackendTask(
        trimmedDesc,
        plannerMode,
        coderMode,
        requireHumanApproval
      );
      let finalTask = initialTask;

      // 2. POST /tasks/{task_id}/run (LangGraph StateGraph Autonomous Workflow)
      if (autoRunWorkflow) {
        setLoadingStep(`2/2 Agent iş akışı çalıştırılıyor (Planner → Scope → Coder → Test → Review)...`);
        finalTask = await runBackendTask(
          initialTask.id,
          plannerMode,
          coderMode,
          requireHumanApproval
        );
      }

      setCreatedSuccess(finalTask);

      onTaskCreated(finalTask, {
        title: taskTitle,
        priority,
        branch: branch.trim() || 'main',
        selectedAgents
      });

      // Brief feedback delay before closing
      setTimeout(() => {
        setIsLoading(false);
        setLoadingStep('');
        setCreatedSuccess(null);
        setTitle('');
        setDescription('');
        onClose();
      }, 1000);
    } catch (err: unknown) {
      setIsLoading(false);
      setLoadingStep('');
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Görev oluşturulurken veya yürütülürken beklenmeyen bir hata meydana geldi.');
      }
    }
  };

  const toggleAgent = (agentId: string) => {
    if (selectedAgents.includes(agentId)) {
      if (selectedAgents.length > 1) {
        setSelectedAgents(selectedAgents.filter((id) => id !== agentId));
      }
    } else {
      setSelectedAgents([...selectedAgents, agentId]);
    }
  };

  const sampleTasks = [
    {
      title: 'Hesaplama Fonksiyonu ve Doğrulama Testleri',
      desc: 'Toplama, çıkarma, çarpma ve bölme işlemlerini içeren tip güvenli bir hesaplama modülü ve birim testlerini üret.',
      branch: 'feat/calculator-module'
    },
    {
      title: 'E-posta Filtreleme ve RFC Doğrulama Modülü',
      desc: 'Geçerli e-posta adreslerini filtreleyen, domain ve regex kontrolü yapan güvenli bir email validator fonksiyonu oluştur.',
      branch: 'feat/email-filter'
    },
    {
      title: 'IP Bazlı Token Bucket Rate Limiter',
      desc: 'İstemci IP adreslerine göre istek sınırlaması uygulayan ve 429 yanıtı veren kayan pencereli rate limiter geliştir.',
      branch: 'feat/rate-limiter'
    }
  ];

  const applyTemplate = (tpl: typeof sampleTasks[0]) => {
    setTitle(tpl.title);
    setDescription(tpl.desc);
    setBranch(tpl.branch);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card modal-medium"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        {/* Modal Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <div className="modal-icon-badge">
              <Sparkles size={18} />
            </div>
            <div>
              <h3 id="modal-title" className="modal-title">
                Yeni Otonom Görev Başlat
              </h3>
              <p className="modal-subtitle">
                FastAPI Backend ve LangGraph Agent Pipeline iş akışına yeni görev gönder
              </p>
            </div>
          </div>
          <button
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Pencereyi Kapat"
            disabled={isLoading}
          >
            <X size={18} />
          </button>
        </div>

        {/* LLM Provider Status Banner */}
        {isMockProvider ? (
          <div className="modal-demo-banner" style={{ background: 'rgba(234, 179, 8, 0.09)', borderColor: 'rgba(234, 179, 8, 0.3)' }}>
            <Bot size={16} className="demo-banner-icon" style={{ color: '#eab308' }} />
            <div className="demo-banner-text">
              <strong style={{ color: '#facc15' }}>Mock LLM Modu Aktif:</strong> Sistem güvenli yerel Mock LLM sağlayıcısı (<code>{llmInfo?.model || 'mock-llm-v1'}</code>) ile çalışmaktadır. Harici API çağrısı yapılmaz; deterministik ve güvenli çıktılar üretilir.
            </div>
          </div>
        ) : (
          <div className="modal-demo-banner" style={{ background: 'rgba(59, 130, 246, 0.08)', borderColor: 'rgba(59, 130, 246, 0.25)' }}>
            <Server size={15} className="demo-banner-icon" style={{ color: '#3b82f6' }} />
            <div className="demo-banner-text">
              <strong>LangGraph Pipeline:</strong> Görev <code>POST /tasks</code> ile kaydedilir ve <code>POST /tasks/run</code> ile Planner, Scope, Coder, Docker Sandbox Tester ve Reviewer ajanlarından sırayla geçer.
            </div>
          </div>
        )}

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="modal-form">
          {/* Quick Templates */}
          <div className="form-group">
            <label className="form-label">
              <span>Hızlı Şablonlar (Örnek Görevler)</span>
            </label>
            <div className="template-chips-grid">
              {sampleTasks.map((tpl, i) => (
                <button
                  key={i}
                  type="button"
                  className="template-chip"
                  onClick={() => applyTemplate(tpl)}
                  disabled={isLoading}
                >
                  <FileCode2 size={13} className="tpl-icon" />
                  <span className="tpl-title">{tpl.title}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Task Title */}
          <div className="form-group">
            <label className="form-label" htmlFor="task-title-input">
              <span>Görev Başlığı</span>
            </label>
            <input
              id="task-title-input"
              type="text"
              className="form-input"
              placeholder="Örn: Hesaplama modülü ve unit testleri"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={isLoading}
            />
          </div>

          {/* Task Description */}
          <div className="form-group">
            <label className="form-label" htmlFor="task-desc-input">
              <span>Gereksinimler & Görev Açıklaması (<code>description</code>)</span>
              <span className="required-star">*</span>
            </label>
            <textarea
              id="task-desc-input"
              className="form-textarea"
              rows={4}
              placeholder="Agent ekibine ve backend'e iletilecek görev açıklaması ve kabul kriterleri (Boş bırakılamaz)..."
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                if (error) setError(null);
              }}
              required
              disabled={isLoading}
            />
          </div>

          {/* Target Branch & Priority */}
          <div className="form-row-2">
            <div className="form-group">
              <label className="form-label" htmlFor="branch-input">
                <GitBranch size={13} />
                <span>Hedef Branch</span>
              </label>
              <input
                id="branch-input"
                type="text"
                className="form-input"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                placeholder="feat/your-branch-name"
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="priority-select">
                <span>Öncelik Seviyesi</span>
              </label>
              <select
                id="priority-select"
                className="form-select"
                value={priority}
                onChange={(e) =>
                  setPriority(
                    e.target.value as 'low' | 'medium' | 'high' | 'critical'
                  )
                }
                disabled={isLoading}
              >
                <option value="low">Low (Düşük)</option>
                <option value="medium">Medium (Normal)</option>
                <option value="high">High (Yüksek)</option>
                <option value="critical">Critical (Kritik)</option>
              </select>
            </div>
          </div>

          {/* Planner & Coder Execution Modes Grid */}
          <div className="form-row-2">
            {/* Planner Mode */}
            <div className="form-group">
              <label className="form-label">
                <Sparkles size={13} />
                <span>Planner Modu</span>
              </label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="button"
                  onClick={() => setPlannerMode('deterministic')}
                  disabled={isLoading}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '6px',
                    background: plannerMode === 'deterministic' ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-card-secondary, #0b111e)',
                    border: plannerMode === 'deterministic' ? '1px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    color: plannerMode === 'deterministic' ? '#60a5fa' : 'var(--text-muted)'
                  }}
                >
                  Deterministik
                </button>
                <button
                  type="button"
                  onClick={() => setPlannerMode('llm')}
                  disabled={isLoading}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '6px',
                    background: plannerMode === 'llm' ? 'rgba(168, 85, 247, 0.15)' : 'var(--bg-card-secondary, #0b111e)',
                    border: plannerMode === 'llm' ? '1px solid #a855f7' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    color: plannerMode === 'llm' ? '#c084fc' : 'var(--text-muted)'
                  }}
                >
                  {isMockProvider ? 'LLM (Mock)' : 'LLM'}
                </button>
              </div>
            </div>

            {/* Coder Mode */}
            <div className="form-group">
              <label className="form-label">
                <FileCode2 size={13} />
                <span>Coder Modu</span>
              </label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button
                  type="button"
                  onClick={() => setCoderMode('deterministic')}
                  disabled={isLoading}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '6px',
                    background: coderMode === 'deterministic' ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-card-secondary, #0b111e)',
                    border: coderMode === 'deterministic' ? '1px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    color: coderMode === 'deterministic' ? '#60a5fa' : 'var(--text-muted)'
                  }}
                >
                  Deterministik
                </button>
                <button
                  type="button"
                  onClick={() => setCoderMode('llm')}
                  disabled={isLoading}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: '6px',
                    background: coderMode === 'llm' ? 'rgba(168, 85, 247, 0.15)' : 'var(--bg-card-secondary, #0b111e)',
                    border: coderMode === 'llm' ? '1px solid #a855f7' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    color: coderMode === 'llm' ? '#c084fc' : 'var(--text-muted)'
                  }}
                >
                  {isMockProvider ? 'LLM (Mock)' : 'LLM'}
                </button>
              </div>
            </div>
          </div>

          {/* Auto Workflow Switch */}
          <div style={{ background: 'var(--bg-card-secondary, #0b111e)', padding: '10px 14px', borderRadius: '6px', border: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Target size={15} style={{ color: '#38bdf8' }} />
              <div>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block' }}>
                  Otonom Pipeline'ı Otomatik Başlat
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Görev kaydedildikten hemen sonra <code>POST /tasks/run</code> ile Planner → Scope → Coder → Test → Reviewer zincirini çalıştırır
                </span>
              </div>
            </div>
            <input
              type="checkbox"
              id="auto-workflow-toggle"
              checked={autoRunWorkflow}
              onChange={(e) => setAutoRunWorkflow(e.target.checked)}
              disabled={isLoading}
              style={{ width: '16px', height: '16px', accentColor: '#3b82f6', cursor: 'pointer' }}
            />
          </div>

          <div style={{ background: 'var(--bg-card-secondary, #0b111e)', padding: '10px 14px', borderRadius: '6px', border: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Target size={15} style={{ color: '#c084fc' }} />
              <div>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)', display: 'block' }}>
                  İnsan onayı gerekli
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  Kapalıyken reviewer approved sonrası görev reviewed kalır. Açıkken görev awaiting_approval durumunda bekler.
                </span>
              </div>
            </div>
            <input
              type="checkbox"
              id="require-human-approval-toggle"
              checked={requireHumanApproval}
              onChange={(e) => setRequireHumanApproval(e.target.checked)}
              disabled={isLoading}
              style={{ width: '16px', height: '16px', accentColor: '#a855f7', cursor: 'pointer' }}
            />
          </div>

          {/* Agent Selection */}
          <div className="form-group">
            <label className="form-label">
              <Cpu size={13} />
              <span>Görevlendirilecek Agent Birimleri</span>
            </label>
            <div className="agent-selection-pills">
              {[
                { id: 'agent-architect', name: 'Planner (Architect)' },
                { id: 'agent-scope', name: 'Scope' },
                { id: 'agent-coder', name: 'Coder' },
                { id: 'agent-test', name: 'Tester (Docker)' },
                { id: 'agent-reviewer', name: 'Semantic Reviewer' }
              ].map((ag) => {
                const isChecked = selectedAgents.includes(ag.id);
                return (
                  <button
                    key={ag.id}
                    type="button"
                    className={`agent-toggle-pill ${isChecked ? 'active' : ''}`}
                    onClick={() => toggleAgent(ag.id)}
                    disabled={isLoading}
                  >
                    <CheckCircle2 size={13} className="check-icon" />
                    <span>{ag.name}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Success Banner */}
          {createdSuccess && (
            <div className="form-error-banner" style={{ background: 'rgba(16, 185, 129, 0.12)', borderColor: 'rgba(16, 185, 129, 0.3)', color: '#10b981' }}>
              <CheckCircle2 size={16} />
              <span>
                Backend görevi oluşturuldu! ID: <strong>{createdSuccess.id}</strong> (Durum: <strong>{createdSuccess.status.toUpperCase()}</strong>)
              </span>
            </div>
          )}

          {/* Error Banner */}
          {error && (
            <div className="form-error-banner">
              <AlertCircle size={14} />
              <span>{error}</span>
            </div>
          )}

          {/* Modal Footer */}
          <div className="modal-footer">
            <button
              type="button"
              className="btn-modal-cancel"
              onClick={onClose}
              disabled={isLoading}
            >
              İptal
            </button>
            <button
              type="submit"
              className="btn-modal-submit"
              disabled={isLoading || !description.trim()}
            >
              {isLoading ? (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  <span>{loadingStep || "İşleniyor..."}</span>
                </>
              ) : (
                <>
                  <Play size={15} />
                  <span>{autoRunWorkflow ? 'Görevi Oluştur & Başlat' : 'Görevi Oluştur (Kuyruğa Al)'}</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
