import React from 'react';
import {
  CheckCircle2,
  Loader2,
  Clock,
  AlertCircle,
  FileCode2,
  ChevronRight,
  Cpu,
  Layers,
  Target,
  ListOrdered,
  CheckSquare,
  AlertTriangle,
  Sparkles,
  FolderGit2,
  FilePlus2,
  ShieldCheck
} from 'lucide-react';
import type { PipelineStep, StepKey, StepStatus, BackendTask } from '../../types';

interface TimelineProps {
  steps: PipelineStep[];
  selectedStepKey: StepKey;
  onSelectStep: (key: StepKey) => void;
  activeBackendTask?: BackendTask | null;
  onOpenPlanModal?: (task: BackendTask) => void;
}

export const Timeline: React.FC<TimelineProps> = ({
  steps,
  selectedStepKey,
  onSelectStep,
  activeBackendTask,
  onOpenPlanModal
}) => {
  const selectedStep = steps.find((s) => s.key === selectedStepKey) || steps[0];
  const hasLivePlan = selectedStepKey === 'plan' && activeBackendTask && activeBackendTask.plan;
  const hasLiveScope = selectedStepKey === 'scope' && activeBackendTask && activeBackendTask.scope;
  const hasLiveCoder = selectedStepKey === 'edit' && activeBackendTask && activeBackendTask.coder;
  const hasLiveTester = selectedStepKey === 'validate' && activeBackendTask && activeBackendTask.tester;
  const hasLiveReviewer = selectedStepKey === 'review' && activeBackendTask && activeBackendTask.reviewer;

  const getStatusIcon = (status: StepStatus) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="status-icon completed-icon" size={16} />;
      case 'running':
        return <Loader2 className="status-icon running-icon spinning" size={16} />;
      case 'failed':
        return <AlertCircle className="status-icon failed-icon" size={16} />;
      case 'pending':
      default:
        return <Clock className="status-icon pending-icon" size={16} />;
    }
  };

  const getStatusBadge = (status: StepStatus) => {
    switch (status) {
      case 'completed':
        return <span className="status-pill completed">Completed</span>;
      case 'running':
        return <span className="status-pill running">Running</span>;
      case 'failed':
        return <span className="status-pill failed">Failed</span>;
      case 'pending':
      default:
        return <span className="status-pill pending">Pending</span>;
    }
  };

  return (
    <div className="pipeline-container">
      {/* Pipeline Header */}
      <div className="pipeline-header">
        <div className="pipeline-title-group">
          <div className="pipeline-icon-box">
            <Layers size={18} className="pipeline-icon" />
          </div>
          <div>
            <h2 className="pipeline-title">Autonomous Pipeline</h2>
            <p className="pipeline-subtitle">
              Sıralı AI agent orkestrasyon adımları ve canlı yürütme grafiği
            </p>
          </div>
        </div>

        <div className="pipeline-header-actions">
          <span className="pipeline-mode-badge">
            <span className="dot active" />
            Active Stage: <strong>{steps.find(s => s.status === 'running')?.name || 'Idle'}</strong>
          </span>
        </div>
      </div>

      <div className="pipeline-content-grid">
        {/* Left Column: Vertical Timeline Steps */}
        <div className="pipeline-timeline-column">
          <div className="timeline-steps-wrapper">
            {steps.map((step, index) => {
              const isSelected = step.key === selectedStepKey;
              const isLast = index === steps.length - 1;

              return (
                <div
                  key={step.id}
                  className={`timeline-node-card ${step.status} ${
                    isSelected ? 'selected' : ''
                  }`}
                  onClick={() => onSelectStep(step.key)}
                  id={`pipeline-step-${step.key}`}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      onSelectStep(step.key);
                    }
                  }}
                >
                  {/* Step Connector Line */}
                  {!isLast && (
                    <div
                      className={`timeline-connector-line ${
                        step.status === 'completed' ? 'completed' : ''
                      }`}
                    />
                  )}

                  {/* Step Left Node Badge */}
                  <div className={`step-node-badge ${step.status}`}>
                    {getStatusIcon(step.status)}
                  </div>

                  {/* Step Main Info */}
                  <div className="step-main-info">
                    <div className="step-headline">
                      <span className="step-number-tag">{step.stepNumber}. {step.name}</span>
                      {getStatusBadge(step.status)}
                    </div>
                    <p className="step-short-desc">{step.shortDesc}</p>

                    <div className="step-meta-row">
                      <span className="meta-agent-tag">
                        <Cpu size={12} />
                        {step.assignedAgent}
                      </span>
                      {step.duration && (
                        <span className="meta-duration-tag">
                          <Clock size={12} />
                          {step.duration}
                        </span>
                      )}
                    </div>

                    {/* Mini progress bar if running */}
                    {step.status === 'running' && (
                      <div className="step-progress-wrapper">
                        <div
                          className="step-progress-fill"
                          style={{ width: `${step.progress}%` }}
                        />
                      </div>
                    )}
                  </div>

                  <div className="step-arrow-right">
                    <ChevronRight size={16} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Selected Step Inspector */}
        <div className="pipeline-detail-column">
          <div className="step-inspector-card">
            <div className="inspector-header">
              <div className="inspector-title-row">
                <span className="inspector-step-badge">
                  Step {selectedStep.stepNumber} of 5
                </span>
                <span className={`status-pill ${selectedStep.status}`}>
                  {selectedStep.status.toUpperCase()}
                </span>
              </div>
              <h3 className="inspector-step-title">{selectedStep.name} Stage</h3>
              <p className="inspector-step-desc">{selectedStep.detailedDesc}</p>
            </div>

            <div className="inspector-body">
              {/* If real live plan exists for Plan step */}
              {hasLivePlan && activeBackendTask?.plan && (
                <div style={{ background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.25)', borderRadius: '8px', padding: '14px', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#60a5fa', fontWeight: 700, fontSize: '0.85rem' }}>
                      <Sparkles size={15} />
                      <span>Gerçek LangGraph Planner Çıktısı ({activeBackendTask.id})</span>
                    </div>
                    {onOpenPlanModal && (
                      <button
                        type="button"
                        onClick={() => onOpenPlanModal(activeBackendTask)}
                        style={{ fontSize: '0.75rem', color: '#38bdf8', textDecoration: 'underline', cursor: 'pointer' }}
                      >
                        Tam Detay &rarr;
                      </button>
                    )}
                  </div>

                  {/* Goal */}
                  <div style={{ marginBottom: '10px' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Target size={11} /> Hedef
                    </span>
                    <p style={{ fontSize: '0.84rem', color: 'var(--text-primary)', margin: '2px 0 0', lineHeight: '1.4' }}>
                      {activeBackendTask.plan.goal}
                    </p>
                  </div>

                  {/* Subtask snippet */}
                  <div style={{ marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <ListOrdered size={11} /> Alt Görevler ({activeBackendTask.plan.subtasks.length})
                    </span>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                      {activeBackendTask.plan.subtasks.slice(0, 3).map((st, i) => (
                        <div key={i} style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', background: 'var(--bg-card-secondary, #0b111e)', padding: '4px 8px', borderRadius: '4px' }}>
                          {st}
                        </div>
                      ))}
                      {activeBackendTask.plan.subtasks.length > 3 && (
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          + {activeBackendTask.plan.subtasks.length - 3} alt görev daha...
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Criteria & Risks counter */}
                  <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                    <span style={{ fontSize: '0.72rem', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '2px 6px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <CheckSquare size={11} /> {activeBackendTask.plan.acceptance_criteria.length} Kabul Kriteri
                    </span>
                    {activeBackendTask.plan.risks.length > 0 && (
                      <span style={{ fontSize: '0.72rem', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', padding: '2px 6px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <AlertTriangle size={11} /> {activeBackendTask.plan.risks.length} Risk
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* If real live scope exists for Scope step */}
              {hasLiveScope && activeBackendTask?.scope && (
                <div style={{ background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: '8px', padding: '14px', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#38bdf8', fontWeight: 700, fontSize: '0.85rem' }}>
                      <FolderGit2 size={15} />
                      <span>Gerçek LangGraph Scope Çıktısı ({activeBackendTask.id})</span>
                    </div>
                    {onOpenPlanModal && (
                      <button
                        type="button"
                        onClick={() => onOpenPlanModal(activeBackendTask)}
                        style={{ fontSize: '0.75rem', color: '#38bdf8', textDecoration: 'underline', cursor: 'pointer' }}
                      >
                        Tam Detay &rarr;
                      </button>
                    )}
                  </div>

                  {/* Summary */}
                  <p style={{ fontSize: '0.84rem', color: 'var(--text-primary)', margin: '0 0 10px', lineHeight: '1.4' }}>
                    {activeBackendTask.scope.summary}
                  </p>

                  {/* Existing files list */}
                  <div style={{ marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <FileCode2 size={11} /> Kapsama Alınan Mevcut Dosyalar ({activeBackendTask.scope.existing_files.length})
                    </span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                      {activeBackendTask.scope.existing_files.map((file, i) => (
                        <span key={i} style={{ fontSize: '0.74rem', color: '#60a5fa', background: 'rgba(59, 130, 246, 0.12)', border: '1px solid rgba(59, 130, 246, 0.25)', padding: '2px 6px', borderRadius: '4px', fontFamily: 'monospace' }}>
                          {file}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Proposed new files list */}
                  {activeBackendTask.scope.proposed_new_files.length > 0 && (
                    <div style={{ marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <FilePlus2 size={11} /> Önerilen Yeni Dosyalar ({activeBackendTask.scope.proposed_new_files.length})
                      </span>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                        {activeBackendTask.scope.proposed_new_files.map((file, i) => (
                          <span key={i} style={{ fontSize: '0.74rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.25)', padding: '2px 6px', borderRadius: '4px', fontFamily: 'monospace' }}>
                            + {file}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Safe out of scope banner */}
                  <div style={{ marginTop: '8px', fontSize: '0.72rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.08)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ShieldCheck size={12} />
                    <span>Hassas dosyalar (.env, .git, .venv, node_modules) güvenle dışlandı</span>
                  </div>
                </div>
              )}

              {/* If real live coder exists for Edit step */}
              {hasLiveCoder && activeBackendTask?.coder && (
                <div style={{
                  background: activeBackendTask.coder.status === 'coded' ? 'rgba(16, 185, 129, 0.08)' : activeBackendTask.coder.status === 'unsupported' ? 'rgba(245, 158, 11, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                  border: `1px solid ${activeBackendTask.coder.status === 'coded' ? 'rgba(16, 185, 129, 0.25)' : activeBackendTask.coder.status === 'unsupported' ? 'rgba(245, 158, 11, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`,
                  borderRadius: '8px',
                  padding: '14px',
                  marginBottom: '16px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: activeBackendTask.coder.status === 'coded' ? '#10b981' : activeBackendTask.coder.status === 'unsupported' ? '#f59e0b' : '#ef4444', fontWeight: 700, fontSize: '0.85rem' }}>
                      <FileCode2 size={15} />
                      <span>Gerçek LangGraph Coder Çıktısı ({activeBackendTask.id})</span>
                    </div>
                    {onOpenPlanModal && (
                      <button
                        type="button"
                        onClick={() => onOpenPlanModal(activeBackendTask)}
                        style={{ fontSize: '0.75rem', color: '#38bdf8', textDecoration: 'underline', cursor: 'pointer' }}
                      >
                        Tam Detay &rarr;
                      </button>
                    )}
                  </div>

                  {/* Summary */}
                  <p style={{ fontSize: '0.84rem', color: 'var(--text-primary)', margin: '0 0 10px', lineHeight: '1.4' }}>
                    {activeBackendTask.coder.summary}
                  </p>

                  {/* Created files list */}
                  {activeBackendTask.coder.created_files.length > 0 && (
                    <div style={{ marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <FilePlus2 size={11} /> İzole Alanda Oluşturulan Dosyalar ({activeBackendTask.coder.created_files.length})
                      </span>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                        {activeBackendTask.coder.created_files.map((cf, i) => {
                          const filePath = typeof cf === 'string' ? cf : (cf?.path || 'file');
                          const fileBytes = typeof cf === 'object' && cf?.bytes !== undefined ? `${cf.bytes} B` : '';
                          return (
                            <div key={i} style={{ fontSize: '0.74rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.25)', padding: '3px 8px', borderRadius: '4px', fontFamily: 'monospace', display: 'flex', justifyContent: 'space-between' }}>
                              <span>{filePath}</span>
                              {fileBytes && <span style={{ color: 'var(--text-muted)' }}>{fileBytes}</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Limitations banner */}
                  <div style={{ marginTop: '8px', fontSize: '0.72rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.08)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ShieldCheck size={12} />
                    <span>İzole workspace'e yazıldı; ana kaynaklar ve gizli dosyalar korunuyor</span>
                  </div>
                </div>
              )}

              {/* If real live tester exists for Validate step */}
              {hasLiveTester && activeBackendTask?.tester && (
                <div style={{
                  background: activeBackendTask.tester.status === 'tested' ? 'rgba(16, 185, 129, 0.08)' : activeBackendTask.tester.status === 'blocked' ? 'rgba(239, 68, 68, 0.08)' : 'rgba(245, 158, 11, 0.08)',
                  border: `1px solid ${activeBackendTask.tester.status === 'tested' ? 'rgba(16, 185, 129, 0.25)' : activeBackendTask.tester.status === 'blocked' ? 'rgba(239, 68, 68, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`,
                  borderRadius: '8px',
                  padding: '14px',
                  marginBottom: '16px'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: activeBackendTask.tester.status === 'tested' ? '#10b981' : activeBackendTask.tester.status === 'blocked' ? '#ef4444' : '#f59e0b', fontWeight: 700, fontSize: '0.85rem' }}>
                      <CheckSquare size={15} />
                      <span>Gerçek LangGraph Tester Çıktısı ({activeBackendTask.id})</span>
                    </div>
                    {onOpenPlanModal && (
                      <button
                        type="button"
                        onClick={() => onOpenPlanModal(activeBackendTask)}
                        style={{ fontSize: '0.75rem', color: '#38bdf8', textDecoration: 'underline', cursor: 'pointer' }}
                      >
                        Tam Detay &rarr;
                      </button>
                    )}
                  </div>

                  {/* Summary */}
                  <p style={{ fontSize: '0.84rem', color: 'var(--text-primary)', margin: '0 0 10px', lineHeight: '1.4' }}>
                    {activeBackendTask.tester.summary}
                  </p>

                  {/* Test results count */}
                  <div style={{ display: 'flex', gap: '6px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.72rem', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
                      {activeBackendTask.tester.passed} Başarılı Test
                    </span>
                    {activeBackendTask.tester.failed > 0 && (
                      <span style={{ fontSize: '0.72rem', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
                        {activeBackendTask.tester.failed} Başarısız Test
                      </span>
                    )}
                  </div>

                  {/* Test case list */}
                  {activeBackendTask.tester.test_results.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '4px' }}>
                      {activeBackendTask.tester.test_results.map((tr, i) => (
                        <div key={i} style={{ fontSize: '0.74rem', color: tr.status === 'passed' ? '#10b981' : '#ef4444', background: 'var(--bg-card-secondary, #0b111e)', border: '1px solid rgba(255, 255, 255, 0.05)', padding: '4px 8px', borderRadius: '4px', fontFamily: 'monospace', display: 'flex', justifyContent: 'space-between' }}>
                          <span>{tr.status === 'passed' ? '✓' : '✗'} {tr.name}</span>
                          <span style={{ color: 'var(--text-muted)' }}>{tr.duration_ms} ms</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Security banner */}
                  <div style={{ marginTop: '8px', fontSize: '0.72rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.08)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ShieldCheck size={12} />
                    <span>Ağ erişimi kapalı, 5.0s zaman aşımı limitli izole ortamda koşuldu</span>
                  </div>
                </div>
              )}

              {/* Live Reviewer Agent Result Inspector Box */}
              {hasLiveReviewer && activeBackendTask && activeBackendTask.reviewer && (
                <div className="inspector-card-highlight" style={{ marginTop: '12px', borderLeft: `4px solid ${activeBackendTask.reviewer.verdict === 'approved' ? '#10b981' : activeBackendTask.reviewer.verdict === 'changes_requested' ? '#f59e0b' : '#ef4444'}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Sparkles size={16} style={{ color: activeBackendTask.reviewer.verdict === 'approved' ? '#10b981' : activeBackendTask.reviewer.verdict === 'changes_requested' ? '#f59e0b' : '#ef4444' }} />
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>Reviewer Agent: Kod İnceleme & Karar</span>
                    </div>
                    <span style={{
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: activeBackendTask.reviewer.verdict === 'approved' ? 'rgba(16, 185, 129, 0.2)' : activeBackendTask.reviewer.verdict === 'changes_requested' ? 'rgba(245, 158, 11, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                      color: activeBackendTask.reviewer.verdict === 'approved' ? '#10b981' : activeBackendTask.reviewer.verdict === 'changes_requested' ? '#f59e0b' : '#ef4444'
                    }}>
                      {activeBackendTask.reviewer.verdict === 'approved' ? '✓ Approved' : activeBackendTask.reviewer.verdict === 'changes_requested' ? '⚠ Changes Requested' : '⛔ Blocked'}
                    </span>
                  </div>

                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '8px', lineHeight: 1.4 }}>
                    {activeBackendTask.reviewer.summary}
                  </p>

                  {/* Findings stats */}
                  <div style={{ display: 'flex', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '0.72rem', background: 'rgba(255, 255, 255, 0.05)', color: 'var(--text-muted)', padding: '2px 8px', borderRadius: '4px' }}>
                      {activeBackendTask.reviewer.reviewed_files.length} Dosya İncelendi
                    </span>
                    <span style={{ fontSize: '0.72rem', background: activeBackendTask.reviewer.findings.length === 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)', color: activeBackendTask.reviewer.findings.length === 0 ? '#10b981' : '#f59e0b', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
                      {activeBackendTask.reviewer.findings.length} Bulgu
                    </span>
                  </div>

                  {/* Findings list */}
                  {activeBackendTask.reviewer.findings.length > 0 && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '6px', maxHeight: '180px', overflowY: 'auto' }}>
                      {activeBackendTask.reviewer.findings.map((f) => {
                        const sevColor = f.severity === 'critical' ? '#ef4444' : f.severity === 'high' ? '#f97316' : f.severity === 'medium' ? '#f59e0b' : '#3b82f6';
                        return (
                          <div key={f.id} style={{ fontSize: '0.74rem', background: 'var(--bg-card-secondary, #0b111e)', border: `1px solid ${sevColor}33`, padding: '6px 8px', borderRadius: '4px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                              <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{f.title}</span>
                              <span style={{ fontSize: '0.68rem', background: `${sevColor}22`, color: sevColor, padding: '1px 5px', borderRadius: '3px', fontWeight: 700, textTransform: 'uppercase' }}>{f.severity}</span>
                            </div>
                            <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: '2px 0' }}>{f.description}</p>
                            {f.recommendation && (
                              <p style={{ fontSize: '0.68rem', color: '#10b981', margin: '2px 0' }}>💡 {f.recommendation}</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Read only notice */}
                  <div style={{ marginTop: '8px', fontSize: '0.72rem', color: '#8b5cf6', background: 'rgba(139, 92, 246, 0.08)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <ShieldCheck size={12} />
                    <span>Salt okunur AST analizi; dosyalara dokunulmadı, komut/ağ çağrısı yapılmadı</span>
                  </div>
                </div>
              )}

              {/* Assigned Agent Box */}
              <div className="inspector-info-row">
                <span className="info-row-label">Sorumlu Agent</span>
                <div className="agent-lead-chip">
                  <Cpu size={14} className="chip-icon" />
                  <span className="chip-agent-name">{selectedStep.assignedAgent}</span>
                  <span className="chip-role">({selectedStep.agentRole})</span>
                </div>
              </div>

              {/* Execution Duration */}
              <div className="inspector-info-row">
                <span className="info-row-label">Yürütme Süresi</span>
                <span className="info-row-val">{selectedStep.duration || 'Henüz başlamadı'}</span>
              </div>

              {/* Inputs & Outputs */}
              {selectedStep.inputs && selectedStep.inputs.length > 0 && (
                <div className="inspector-section">
                  <span className="section-label">Girdi Kaynakları</span>
                  <div className="tag-cloud">
                    {selectedStep.inputs.map((inp, idx) => (
                      <span key={idx} className="data-tag input-tag">
                        {inp}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedStep.outputs && selectedStep.outputs.length > 0 && (
                <div className="inspector-section">
                  <span className="section-label">Üretilen Çıktılar</span>
                  <div className="tag-cloud">
                    {selectedStep.outputs.map((out, idx) => (
                      <span key={idx} className="data-tag output-tag">
                        {out}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Generated Artifacts */}
              <div className="inspector-section">
                <div className="section-header-flex">
                  <span className="section-label">Üretilen Dosyalar / Artifacts</span>
                  <span className="artifact-count">
                    {selectedStep.artifacts.length} dosya
                  </span>
                </div>

                {selectedStep.artifacts.length === 0 ? (
                  <div className="empty-artifacts-box">
                    <p>Bu aşamada henüz artifact üretilmedi.</p>
                  </div>
                ) : (
                  <div className="artifacts-list">
                    {selectedStep.artifacts.map((art, idx) => (
                      <div key={idx} className="artifact-item-card">
                        <div className="art-left">
                          <FileCode2 size={16} className="art-icon" />
                          <div>
                            <span className="art-name">{art.name}</span>
                            <span className="art-desc">{art.description}</span>
                          </div>
                        </div>
                        <span className="art-size">{art.size}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Inspector Footer Actions */}
            <div className="inspector-footer">
              <div className="demo-notice-inline">
                <span>{(hasLivePlan || hasLiveScope || hasLiveCoder || hasLiveTester) ? "FastAPI + LangGraph canlı backend verisi devrede" : "Demo verisi üzerinden denetleniyor"}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
