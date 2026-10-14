import React, { useState, useEffect } from 'react';
import {
  X,
  Target,
  ListOrdered,
  CheckSquare,
  AlertTriangle,
  Clock,
  Cpu,
  Server,
  Sparkles,
  Activity,
  CheckCircle2,
  AlertCircle,
  FolderGit2,
  FileCode2,
  FilePlus2,
  ShieldCheck,
  CheckCheck,
  History,
  Timer,
  Database
} from 'lucide-react';
import type { BackendTask, BackendTaskStatus, WorkflowRun } from '../../types';
import { getTaskRuns, approveBackendTask, rejectBackendTask, redeliverBackendTask, ApiError } from '../../services/api';

interface TaskPlanModalProps {
  isOpen: boolean;
  onClose: () => void;
  task: BackendTask | null;
  onRunWorkflow?: (taskId: string) => void;
  isRunningWorkflow?: boolean;
  onTaskUpdated?: (updatedTask: BackendTask) => void;
}

export const TaskPlanModal: React.FC<TaskPlanModalProps> = ({
  isOpen,
  onClose,
  task,
  onRunWorkflow,
  isRunningWorkflow = false,
  onTaskUpdated
}) => {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [isLoadingRuns, setIsLoadingRuns] = useState<boolean>(false);
  const [isActing, setIsActing] = useState<boolean>(false);
  const [actionMsg, setActionMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [rejectReason, setRejectReason] = useState<string>('');
  const [showRejectInput, setShowRejectInput] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && task?.id) {
      let isCurrent = true;
      Promise.resolve().then(() => {
        if (isCurrent) setIsLoadingRuns(true);
      });
      getTaskRuns(task.id)
        .then((res) => {
          if (!isCurrent) return;
          setRuns(res.runs || []);
          if (res.runs && res.runs.length > 0) {
            setSelectedRunId(res.runs[res.runs.length - 1].id);
          } else {
            setSelectedRunId(null);
          }
        })
        .catch(() => {
          if (isCurrent) setRuns([]);
        })
        .finally(() => {
          if (isCurrent) setIsLoadingRuns(false);
        });
      return () => {
        isCurrent = false;
      };
    }
  }, [isOpen, task?.id, task?.updated_at]);

  if (!isOpen || !task) return null;

  const currentRun = runs.find((r) => r.id === selectedRunId);
  const plan = currentRun ? currentRun.plan : task.plan;
  const scope = currentRun ? currentRun.scope : task.scope;
  const coder = currentRun ? currentRun.coder : task.coder;
  const tester = currentRun ? currentRun.tester : task.tester;
  const reviewer = currentRun ? currentRun.reviewer : task.reviewer;
  const events = (currentRun ? currentRun.events : task.events) || [];
  const metrics = currentRun?.agent_metrics || [];

  const formatTimestamp = (dateStr?: string | null) => {
    if (!dateStr) return '—';
    try {
      const d = new Date(dateStr);
      return d.toLocaleTimeString('tr-TR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  const getStatusBadge = (status: BackendTaskStatus) => {
    switch (status) {
      case 'reviewed':
        return (
          <span className="status-pill completed" style={{ background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
            ● REVIEWED (LangGraph)
          </span>
        );
      case 'tested':
        return (
          <span className="status-pill completed" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
            ● TESTED (LangGraph)
          </span>
        );
      case 'blocked':
        return (
          <span className="status-pill failed" style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
            ● BLOCKED (İzolasyon / İnceleme)
          </span>
        );
      case 'coded':
        return (
          <span className="status-pill completed" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            ● CODED (LangGraph)
          </span>
        );
      case 'unsupported':
        return (
          <span className="status-pill pending" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ● UNSUPPORTED (Şablon Dışı)
          </span>
        );
      case 'scoped':
        return (
          <span className="status-pill completed" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            ● SCOPED (LangGraph)
          </span>
        );
      case 'planned':
        return (
          <span className="status-pill completed" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.3)' }}>
            ● PLANNED (LangGraph)
          </span>
        );
      case 'in_progress':
        return <span className="status-pill running">● RUNNING</span>;
      case 'awaiting_approval':
        return <span className="status-pill pending">● AWAITING APPROVAL</span>;
      case 'completed':
        return <span className="status-pill completed">● COMPLETED</span>;
      case 'delivery_failed':
        return (
          <span className="status-pill failed" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ● DELIVERY FAILED
          </span>
        );
      case 'failed':
        return <span className="status-pill failed">● FAILED</span>;
      case 'queued':
      default:
        return <span className="status-pill pending">● QUEUED</span>;
    }
  };

  const getVerdictBadge = (verdict: string) => {
    switch (verdict) {
      case 'approved':
        return (
          <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '3px 10px', borderRadius: '4px', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
            ✓ APPROVED (Onaylandı)
          </span>
        );
      case 'changes_requested':
        return (
          <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '3px 10px', borderRadius: '4px', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ⚠ CHANGES REQUESTED
          </span>
        );
      case 'blocked':
      default:
        return (
          <span style={{ fontSize: '0.75rem', fontWeight: 700, padding: '3px 10px', borderRadius: '4px', background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
            ⛔ BLOCKED (Engellendi)
          </span>
        );
    }
  };

  const getSeverityBadge = (sev: string) => {
    switch (sev) {
      case 'critical':
        return <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '3px', background: 'rgba(239, 68, 68, 0.2)', color: '#ef4444' }}>CRITICAL</span>;
      case 'high':
        return <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '3px', background: 'rgba(249, 115, 22, 0.2)', color: '#f97316' }}>HIGH</span>;
      case 'medium':
        return <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '3px', background: 'rgba(245, 158, 11, 0.2)', color: '#f59e0b' }}>MEDIUM</span>;
      case 'low':
        return <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '3px', background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa' }}>LOW</span>;
      case 'info':
      default:
        return <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '2px 6px', borderRadius: '3px', background: 'rgba(148, 163, 184, 0.2)', color: '#94a3b8' }}>INFO</span>;
    }
  };

  const handleApprove = async () => {
    if (!task?.id) return;
    setIsActing(true);
    setActionMsg(null);
    try {
      const updated = await approveBackendTask(task.id, 'Arayüz üzerinden insan onayı verildi.');
      setActionMsg({ type: 'success', text: `Görev başarıyla onaylandı ve tamamlandı (status: ${updated.status})` });
      if (onTaskUpdated) onTaskUpdated(updated);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Görev onaylanırken hata oluştu.';
      setActionMsg({ type: 'error', text: msg });
    } finally {
      setIsActing(false);
    }
  };

  const handleRedeliver = async () => {
    if (!task?.id) return;
    setIsActing(true);
    setActionMsg(null);
    try {
      const updated = await redeliverBackendTask(task.id);
      const deliveryEvent = [...(updated.events || [])].reverse().find((event) =>
        event.type === 'delivery_committed' || event.type === 'delivery_reused'
      );
      const rawSha = deliveryEvent?.details?.commit;
      const sha = typeof rawSha === 'string' ? rawSha : undefined;
      setActionMsg({
        type: updated.status === 'delivery_failed' ? 'error' : 'success',
        text: updated.status === 'delivery_failed'
          ? `Teslimat yeniden denendi ve başarısız kaldı (status: ${updated.status})`
          : `Teslimat güncellendi (status: ${updated.status}${sha ? `, SHA: ${sha}` : ''})`,
      });
      if (onTaskUpdated) onTaskUpdated(updated);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Teslimat yeniden denenirken hata oluştu.';
      setActionMsg({ type: 'error', text: msg });
    } finally {
      setIsActing(false);
    }
  };

  const handleReject = async () => {
    if (!task?.id) return;
    const trimmed = rejectReason.trim();
    if (!trimmed) {
      setActionMsg({ type: 'error', text: 'Lütfen red veya değişiklik gerekçesini yazın.' });
      return;
    }
    setIsActing(true);
    setActionMsg(null);
    try {
      const updated = await rejectBackendTask(task.id, trimmed);
      setActionMsg({ type: 'success', text: `Görev değişiklik talebiyle güncellendi (status: ${updated.status})` });
      setShowRejectInput(false);
      setRejectReason('');
      if (onTaskUpdated) onTaskUpdated(updated);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : 'Görev reddedilirken hata oluştu.';
      setActionMsg({ type: 'error', text: msg });
    } finally {
      setIsActing(false);
    }
  };

  const canDecide = task.status === 'reviewed' || task.status === 'awaiting_approval';
  const canApprove = canDecide && task.reviewer?.verdict !== 'blocked';
  const canReject = canDecide;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card modal-large"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="plan-modal-title"
        style={{ maxWidth: '900px', maxHeight: '92vh', display: 'flex', flexDirection: 'column' }}
      >
        {/* Modal Header */}
        <div className="modal-header" style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '16px' }}>
          <div className="modal-title-group">
            <div className="modal-icon-badge" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
              <Sparkles size={20} />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span className="task-id-badge" style={{ fontSize: '0.75rem' }}>{task.id}</span>
                {getStatusBadge(task.status)}
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.72rem', color: '#10b981', background: 'rgba(16, 185, 129, 0.1)', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(16, 185, 129, 0.25)' }}>
                  <Database size={11} /> SQLite Persistent
                </span>
              </div>
              <h3 id="plan-modal-title" className="modal-title" style={{ fontSize: '1.2rem' }}>
                Görev Detayı & Workflow Geçmişi
              </h3>
            </div>
          </div>
          <button
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Pencereyi Kapat"
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <div className="modal-body" style={{ overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Action Message Banner */}
          {actionMsg && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: '6px',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                background: actionMsg.type === 'success' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(239, 68, 68, 0.12)',
                border: `1px solid ${actionMsg.type === 'success' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                color: actionMsg.type === 'success' ? '#10b981' : '#ef4444'
              }}
            >
              {actionMsg.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
              <span>{actionMsg.text}</span>
            </div>
          )}

          {/* Original Description */}
          <div style={{ background: 'var(--bg-card-secondary, #0b111e)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block', marginBottom: '4px' }}>
              Orijinal Görev Açıklaması
            </span>
            <p style={{ color: 'var(--text-primary)', fontSize: '0.95rem', lineHeight: '1.5', margin: 0 }}>
              {task.description}
            </p>
          </div>

          {/* HITL Approval Section */}
          <div style={{ background: 'rgba(168, 85, 247, 0.06)', border: '1px solid rgba(168, 85, 247, 0.25)', borderRadius: '8px', padding: '14px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px', flexWrap: 'wrap', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#c084fc' }}>
                <ShieldCheck size={16} />
                <h4 style={{ fontSize: '0.88rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                  İnsan Onayı & Denetimi (Human-in-the-Loop)
                </h4>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                {canApprove && (
                  <button
                    type="button"
                    onClick={handleApprove}
                    disabled={isActing}
                    style={{
                      background: '#10b981',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '6px',
                      padding: '6px 14px',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <CheckCircle2 size={13} />
                    <span>{isActing ? 'İşleniyor...' : 'Görevi Onayla (Approve)'}</span>
                  </button>
                )}
                {canReject && !showRejectInput && (
                  <button
                    type="button"
                    onClick={() => setShowRejectInput(true)}
                    disabled={isActing}
                    style={{
                      background: 'rgba(239, 68, 68, 0.15)',
                      color: '#ef4444',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      borderRadius: '6px',
                      padding: '6px 14px',
                      fontSize: '0.78rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <AlertCircle size={13} />
                    <span>Değişiklik Talep Et (Reject)</span>
                  </button>
                )}
              </div>
            </div>

            {showRejectInput && (
              <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <textarea
                  className="form-textarea"
                  rows={2}
                  placeholder="Görevin reddedilme nedeni veya yapılması gereken değişiklikler..."
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  style={{ fontSize: '0.82rem' }}
                />
                <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn-modal-cancel"
                    onClick={() => { setShowRejectInput(false); setRejectReason(''); }}
                    style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                  >
                    Vazgeç
                  </button>
                  <button
                    type="button"
                    onClick={handleReject}
                    disabled={isActing || !rejectReason.trim()}
                    style={{
                      background: '#ef4444',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '6px',
                      padding: '4px 12px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      cursor: 'pointer'
                    }}
                  >
                    {isActing ? 'Gönderiliyor...' : 'Reddi Kaydet (POST /reject)'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Workflow Runs Timeline & Selector */}
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '14px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#38bdf8' }}>
                <History size={16} />
                <h4 style={{ fontSize: '0.88rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                  Workflow Çalıştırma Geçmişi ({runs.length})
                </h4>
              </div>
              {task.status === 'delivery_failed' && (
                <button
                  className="btn-primary-action"
                  onClick={() => { void handleRedeliver(); }}
                  disabled={isActing}
                  style={{ padding: '4px 12px', fontSize: '0.78rem' }}
                >
                  <span>{isActing ? 'Teslimat deneniyor...' : 'Teslimatı Yeniden Dene'}</span>
                </button>
              )}
              {onRunWorkflow && task.status !== 'awaiting_approval' && task.status !== 'delivery_failed' && (
                <button
                  className="btn-primary-action"
                  onClick={() => onRunWorkflow(task.id)}
                  disabled={isRunningWorkflow}
                  style={{ padding: '4px 12px', fontSize: '0.78rem' }}
                >
                  <Cpu size={13} />
                  <span>{isRunningWorkflow ? "Çalıştırılıyor..." : "Yeni Run Başlat"}</span>
                </button>
              )}
            </div>

            {isLoadingRuns ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '8px 0' }}>Geçmiş çalıştırmalar yükleniyor...</div>
            ) : runs.length === 0 ? (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '8px 0' }}>
                Bu görev için henüz kaydedilmiş workflow çalıştırması bulunmuyor.
              </div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {runs.map((r) => {
                  const isSelected = r.id === selectedRunId;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => setSelectedRunId(r.id)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        padding: '6px 12px',
                        borderRadius: '6px',
                        background: isSelected ? 'rgba(56, 189, 248, 0.15)' : 'var(--bg-card-secondary, #0b111e)',
                        border: isSelected ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.08)',
                        color: isSelected ? '#38bdf8' : 'var(--text-secondary)',
                        fontSize: '0.78rem',
                        cursor: 'pointer'
                      }}
                    >
                      <span style={{ fontWeight: 700 }}>Run #{r.run_number}</span>
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>({r.id.slice(0, 8)})</span>
                      <span style={{ fontSize: '0.72rem', color: r.status === 'failed' ? '#ef4444' : '#10b981' }}>
                        ● {r.status.toUpperCase()}
                      </span>
                      {r.duration_ms && (
                        <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '2px' }}>
                          <Timer size={10} /> {(r.duration_ms / 1000).toFixed(2)}s
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Agent Metrics Breakdown (if available for this run) */}
          {metrics && metrics.length > 0 && (
            <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', color: '#a855f7' }}>
                <Timer size={16} />
                <h4 style={{ fontSize: '0.88rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                  Agent İcra Metrikleri & Süreler
                </h4>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '8px' }}>
                {metrics.map((m, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: 'var(--bg-card-secondary, #0b111e)',
                      padding: '8px 10px',
                      borderRadius: '6px',
                      border: '1px solid rgba(255, 255, 255, 0.05)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-primary)' }}>{m.agent_name}</span>
                      <span style={{
                        fontSize: '0.65rem',
                        fontWeight: 700,
                        padding: '1px 5px',
                        borderRadius: '3px',
                        background: m.status === 'completed' || m.status === 'coded' || m.status === 'tested' || m.status === 'reviewed'
                          ? 'rgba(16, 185, 129, 0.15)'
                          : m.status === 'skipped'
                          ? 'rgba(148, 163, 184, 0.15)'
                          : 'rgba(239, 68, 68, 0.15)',
                        color: m.status === 'completed' || m.status === 'coded' || m.status === 'tested' || m.status === 'reviewed'
                          ? '#10b981'
                          : m.status === 'skipped'
                          ? '#94a3b8'
                          : '#ef4444'
                      }}>
                        {m.status.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      Süre: {m.duration_ms ? `${m.duration_ms.toFixed(0)} ms` : '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* If Task is Queued and no plan yet */}
          {!plan && task.status === 'queued' && (
            <div style={{ textAlign: 'center', padding: '32px 20px', background: 'rgba(59, 130, 246, 0.05)', borderRadius: '8px', border: '1px dashed rgba(59, 130, 246, 0.3)' }}>
              <Server size={32} style={{ color: '#3b82f6', margin: '0 auto 12px', opacity: 0.8 }} />
              <h4 style={{ fontSize: '1rem', color: 'var(--text-primary)', marginBottom: '6px' }}>
                Görev Sıraya Alındı (Henüz Plan & Kapsam Üretilmedi)
              </h4>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', maxWidth: '440px', margin: '0 auto 16px' }}>
                Bu görev için henüz LangGraph iş akışı çalıştırılmadı. Aşağıdaki butona tıklayarak Planner, Scope, Coder, Tester ve Reviewer adımlarını başlatabilirsiniz.
              </p>
              {onRunWorkflow && (
                <button
                  className="btn-primary-action"
                  onClick={() => onRunWorkflow(task.id)}
                  disabled={isRunningWorkflow}
                  style={{ margin: '0 auto' }}
                >
                  <Cpu size={15} />
                  <span>{isRunningWorkflow ? "İş Akışı Çalıştırılıyor..." : "İş Akışını Çalıştır (POST /tasks/run)"}</span>
                </button>
              )}
            </div>
          )}

          {/* If Task / Run Failed */}
          {(currentRun?.error || task.error || task.status === 'failed') && (
            <div className="form-error-banner" style={{ padding: '14px' }}>
              <AlertCircle size={18} />
              <div>
                <strong>İş Akışı Hatası:</strong> {currentRun?.error || task.error || 'İş akışı sırasında bir hata oluştu.'}
              </div>
            </div>
          )}

          {/* 1. Real Plan Content */}
          {plan && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.25)', borderRadius: '8px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#60a5fa' }}>
                    <Target size={16} />
                    <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                      1. Planner Agent: Hedef & Kapsam (Goal)
                    </h4>
                  </div>
                </div>
                <p style={{ color: 'var(--text-primary)', fontSize: '0.92rem', lineHeight: '1.6', margin: 0 }}>
                  {plan.goal}
                </p>
              </div>

              {/* Subtasks */}
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: '#38bdf8' }}>
                  <ListOrdered size={16} />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                    Alt Görevler & Adımlar ({plan.subtasks.length})
                  </h4>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {plan.subtasks.map((subtask, index) => (
                    <div
                      key={index}
                      style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '10px',
                        padding: '10px 12px',
                        background: 'var(--bg-card-secondary, #0b111e)',
                        borderRadius: '6px',
                        border: '1px solid rgba(255, 255, 255, 0.04)'
                      }}
                    >
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          minWidth: '22px',
                          height: '22px',
                          borderRadius: '50%',
                          background: 'rgba(56, 189, 248, 0.15)',
                          color: '#38bdf8',
                          fontSize: '0.75rem',
                          fontWeight: 700
                        }}
                      >
                        {index + 1}
                      </span>
                      <span style={{ color: 'var(--text-primary)', fontSize: '0.875rem', lineHeight: '1.4' }}>
                        {subtask}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Acceptance Criteria */}
              <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: '#10b981' }}>
                  <CheckSquare size={16} />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                    Kabul Kriterleri ({plan.acceptance_criteria.length})
                  </h4>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {plan.acceptance_criteria.map((criteria, index) => (
                    <div
                      key={index}
                      style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '10px',
                        padding: '10px 12px',
                        background: 'rgba(16, 185, 129, 0.05)',
                        borderRadius: '6px',
                        border: '1px solid rgba(16, 185, 129, 0.18)'
                      }}
                    >
                      <CheckCircle2 size={16} style={{ color: '#10b981', flexShrink: 0, marginTop: '2px' }} />
                      <span style={{ color: 'var(--text-primary)', fontSize: '0.875rem', lineHeight: '1.4' }}>
                        {criteria}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Risks */}
              {plan.risks && plan.risks.length > 0 && (
                <div style={{ background: 'rgba(245, 158, 11, 0.06)', border: '1px solid rgba(245, 158, 11, 0.25)', borderRadius: '8px', padding: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: '#fbbf24' }}>
                    <AlertTriangle size={16} />
                    <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                      Planlama Riskleri ({plan.risks.length})
                    </h4>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {plan.risks.map((risk, index) => (
                      <div
                        key={index}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: '10px',
                          padding: '9px 12px',
                          background: 'rgba(245, 158, 11, 0.04)',
                          borderRadius: '6px',
                          border: '1px solid rgba(245, 158, 11, 0.12)'
                        }}
                      >
                        <span style={{ color: '#f59e0b', fontWeight: 700, fontSize: '0.8rem', marginTop: '1px' }}>
                          !
                        </span>
                        <span style={{ color: 'var(--text-primary)', fontSize: '0.875rem', lineHeight: '1.4' }}>
                          {risk}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 2. Real Scope Content */}
          {scope && (
            <div style={{ background: 'rgba(56, 189, 248, 0.05)', border: '1px solid rgba(56, 189, 248, 0.25)', borderRadius: '8px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#38bdf8' }}>
                <FolderGit2 size={16} />
                <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                  2. Scope Agent: Dosya Kapsamı & Etki Analizi
                </h4>
              </div>

              <p style={{ color: 'var(--text-primary)', fontSize: '0.88rem', margin: 0, lineHeight: '1.5' }}>
                {scope.summary}
              </p>

              <div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
                  <FileCode2 size={12} /> Kapsama Alınan Mevcut Dosyalar ({scope.existing_files.length})
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {scope.existing_files.map((file, i) => (
                    <span
                      key={i}
                      style={{
                        fontSize: '0.76rem',
                        fontFamily: 'monospace',
                        padding: '3px 8px',
                        borderRadius: '4px',
                        background: 'rgba(59, 130, 246, 0.15)',
                        border: '1px solid rgba(59, 130, 246, 0.3)',
                        color: '#60a5fa'
                      }}
                    >
                      {file}
                    </span>
                  ))}
                </div>
              </div>

              {scope.proposed_new_files && scope.proposed_new_files.length > 0 && (
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
                    <FilePlus2 size={12} /> Önerilen Yeni Dosyalar ({scope.proposed_new_files.length})
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {scope.proposed_new_files.map((file, i) => (
                      <span
                        key={i}
                        style={{
                          fontSize: '0.76rem',
                          fontFamily: 'monospace',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          background: 'rgba(16, 185, 129, 0.15)',
                          border: '1px solid rgba(16, 185, 129, 0.3)',
                          color: '#10b981'
                        }}
                      >
                        + {file}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 3. Real Coder Content */}
          {coder && (
            <div style={{
              background: coder.status === 'coded' ? 'rgba(16, 185, 129, 0.05)' : coder.status === 'unsupported' ? 'rgba(245, 158, 11, 0.05)' : 'rgba(239, 68, 68, 0.05)',
              border: `1px solid ${coder.status === 'coded' ? 'rgba(16, 185, 129, 0.25)' : coder.status === 'unsupported' ? 'rgba(245, 158, 11, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`,
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: coder.status === 'coded' ? '#10b981' : coder.status === 'unsupported' ? '#f59e0b' : '#ef4444' }}>
                  <FileCode2 size={16} />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                    3. Coder Agent: İzole Çalışma Alanı & Kod Üretimi
                  </h4>
                </div>
                <span style={{
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: coder.status === 'coded' ? 'rgba(16, 185, 129, 0.15)' : coder.status === 'unsupported' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                  color: coder.status === 'coded' ? '#10b981' : coder.status === 'unsupported' ? '#f59e0b' : '#ef4444'
                }}>
                  {coder.status.toUpperCase()}
                </span>
              </div>

              <p style={{ color: 'var(--text-primary)', fontSize: '0.88rem', margin: 0, lineHeight: '1.5' }}>
                {coder.summary}
              </p>

              {coder.created_files && coder.created_files.length > 0 && (
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
                    <FilePlus2 size={12} /> İzole Alanda Oluşturulan Dosyalar ({coder.created_files.length})
                  </span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {coder.created_files.map((cf, i) => {
                      const filePath = typeof cf === 'string' ? cf : (cf?.path || 'file');
                      const fileDesc = typeof cf === 'object' && cf?.description ? `— ${cf.description}` : '';
                      const fileBytes = typeof cf === 'object' && cf?.bytes !== undefined ? `${cf.bytes} B` : '';
                      return (
                        <div
                          key={i}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            padding: '6px 10px',
                            borderRadius: '6px',
                            background: 'var(--bg-card-secondary, #0b111e)',
                            border: '1px solid rgba(255, 255, 255, 0.05)',
                            fontSize: '0.8rem'
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontFamily: 'monospace', color: '#38bdf8', fontWeight: 600 }}>
                              {filePath}
                            </span>
                            {fileDesc && (
                              <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                {fileDesc}
                              </span>
                            )}
                          </div>
                          {fileBytes && (
                            <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem', fontFamily: 'monospace' }}>
                              {fileBytes}
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 4. Real Tester Content */}
          {tester && (
            <div style={{
              background: tester.status === 'tested' ? 'rgba(16, 185, 129, 0.05)' : tester.status === 'blocked' ? 'rgba(239, 68, 68, 0.05)' : 'rgba(245, 158, 11, 0.05)',
              border: `1px solid ${tester.status === 'tested' ? 'rgba(16, 185, 129, 0.25)' : tester.status === 'blocked' ? 'rgba(239, 68, 68, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`,
              borderRadius: '8px',
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '14px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: tester.status === 'tested' ? '#10b981' : tester.status === 'blocked' ? '#ef4444' : '#f59e0b' }}>
                  <CheckSquare size={16} />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                    4. Tester Agent: İzole Test Koşumu & Sonuçları
                  </h4>
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <span style={{
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    background: 'rgba(16, 185, 129, 0.15)',
                    color: '#10b981'
                  }}>
                    {tester.passed} Geçti
                  </span>
                  {tester.failed > 0 && (
                    <span style={{
                      fontSize: '0.72rem',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: 'rgba(239, 68, 68, 0.15)',
                      color: '#ef4444'
                    }}>
                      {tester.failed} Başarısız
                    </span>
                  )}
                </div>
              </div>

              <p style={{ color: 'var(--text-primary)', fontSize: '0.88rem', margin: 0, lineHeight: '1.5' }}>
                {tester.summary}
              </p>
            </div>
          )}

          {/* 5. Real Reviewer Content */}
          {reviewer && (
            <div style={{ background: 'var(--bg-card)', border: '1px solid rgba(168, 85, 247, 0.3)', borderRadius: '8px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '10px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#c084fc' }}>
                  <CheckCheck size={16} />
                  <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                    5. Reviewer Agent: Statik Kod İnceleme & Karar
                  </h4>
                </div>
                <div>
                  {getVerdictBadge(reviewer.verdict)}
                </div>
              </div>

              <p style={{ color: 'var(--text-primary)', fontSize: '0.88rem', margin: 0, lineHeight: '1.5' }}>
                {reviewer.summary}
              </p>

              {/* Reviewed Files List */}
              {reviewer.reviewed_files && reviewer.reviewed_files.length > 0 && (
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '6px' }}>
                    İncelenen Dosyalar ({reviewer.reviewed_files.length})
                  </span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    {reviewer.reviewed_files.map((file, i) => (
                      <span key={i} style={{ fontFamily: 'monospace', fontSize: '0.78rem', padding: '2px 8px', background: 'rgba(168, 85, 247, 0.1)', color: '#c084fc', borderRadius: '4px', border: '1px solid rgba(168, 85, 247, 0.2)' }}>
                        {file}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Review Findings */}
              {reviewer.findings && reviewer.findings.length > 0 && (
                <div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '8px' }}>
                    <AlertTriangle size={12} /> İnceleme Bulguları ({reviewer.findings.length})
                  </span>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {reviewer.findings.map((f) => (
                      <div
                        key={f.id}
                        style={{
                          background: 'var(--bg-card-secondary, #0b111e)',
                          borderRadius: '6px',
                          padding: '10px 12px',
                          border: '1px solid rgba(255, 255, 255, 0.08)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: '4px'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: '0.84rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                            {f.title}
                          </span>
                          {getSeverityBadge(f.severity)}
                        </div>
                        <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
                          {f.description}
                        </p>
                        {f.recommendation && (
                          <div style={{ fontSize: '0.76rem', color: '#38bdf8' }}>
                            <strong>Öneri:</strong> {f.recommendation}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}


          {/* 6. Workflow Events Timeline */}
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', color: 'var(--text-secondary)' }}>
              <Activity size={16} />
              <h4 style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', margin: 0 }}>
                6. İş Akışı Olay Günlüğü ({events.length})
              </h4>
            </div>

            {events.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: 0 }}>
                Henüz kayıtlı olay bulunmuyor.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {events.map((evt, idx) => (
                  <div
                    key={evt.id || idx}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '8px 12px',
                      background: 'var(--bg-card-secondary, #0b111e)',
                      borderRadius: '6px',
                      border: '1px solid rgba(255, 255, 255, 0.04)',
                      fontSize: '0.82rem'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span
                        style={{
                          fontSize: '0.7rem',
                          fontWeight: 700,
                          padding: '2px 6px',
                          borderRadius: '4px',
                          background: evt.source === 'REVIEWER_AGENT' ? 'rgba(168, 85, 247, 0.2)' : evt.source === 'TESTER_AGENT' ? 'rgba(16, 185, 129, 0.2)' : evt.source === 'CODER_AGENT' ? 'rgba(56, 189, 248, 0.2)' : evt.source === 'SCOPE_AGENT' ? 'rgba(56, 189, 248, 0.2)' : evt.source === 'PLANNER_AGENT' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                          color: evt.source === 'REVIEWER_AGENT' ? '#c084fc' : evt.source === 'TESTER_AGENT' ? '#10b981' : evt.source === 'CODER_AGENT' ? '#38bdf8' : evt.source === 'SCOPE_AGENT' ? '#38bdf8' : evt.source === 'PLANNER_AGENT' ? '#60a5fa' : 'var(--text-secondary)'
                        }}
                      >
                        {evt.source}
                      </span>
                      <span style={{ color: 'var(--text-primary)' }}>{evt.message}</span>
                    </div>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' }}>
                      <Clock size={11} />
                      {formatTimestamp(evt.timestamp)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="modal-footer" style={{ borderTop: '1px solid var(--border-subtle)', padding: '14px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            <Server size={13} />
            <span>FastAPI + SQLite + LangGraph (Planner + Scope + Coder + Tester + Reviewer)</span>
          </div>
          <button type="button" className="btn-modal-cancel" onClick={onClose}>
            Kapat
          </button>
        </div>
      </div>
    </div>
  );
};
