import React, { useState } from 'react';
import {
  Plus,
  GitBranch,
  RefreshCw,
  Server,
  AlertCircle,
  CheckCircle2,
  Clock,
  Layers,
  FileText,
  Target,
  ListOrdered,
  CheckSquare,
  AlertTriangle,
  Eye,
  Activity,
  Sparkles
} from 'lucide-react';
import type { TaskItem, BackendTask, BackendTaskStatus } from '../../types';
import { TaskPlanModal } from '../Modals/TaskPlanModal';
import { runBackendTask, ApiError } from '../../services/api';

interface TasksViewProps {
  demoTasks: TaskItem[];
  backendTasks: BackendTask[];
  isLoadingBackend: boolean;
  backendError: string | null;
  onRefreshBackend: () => void;
  onOpenNewTaskModal: () => void;
  onUpdateBackendTask?: (updatedTask: BackendTask) => void;
}

export const TasksView: React.FC<TasksViewProps> = ({
  demoTasks,
  backendTasks,
  isLoadingBackend,
  backendError,
  onRefreshBackend,
  onOpenNewTaskModal,
  onUpdateBackendTask
}) => {
  const [activeTab, setActiveTab] = useState<'backend' | 'demo'>('backend');
  const [selectedTaskForPlan, setSelectedTaskForPlan] = useState<BackendTask | null>(null);
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const formatTimestamp = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleString('tr-TR', {
        month: 'short',
        day: 'numeric',
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
          <span className="priority-badge priority-low" style={{ background: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.3)' }}>
            ● REVIEWED
          </span>
        );
      case 'tested':
        return (
          <span className="priority-badge priority-low" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
            ● TESTED
          </span>
        );
      case 'blocked':
        return (
          <span className="priority-badge priority-critical" style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
            ● BLOCKED
          </span>
        );
      case 'coded':
        return (
          <span className="priority-badge priority-low" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            ● CODED
          </span>
        );
      case 'unsupported':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ● UNSUPPORTED
          </span>
        );
      case 'scoped':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
            ● SCOPED
          </span>
        );
      case 'planned':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.3)' }}>
            ● PLANNED
          </span>
        );
      case 'in_progress':
      case 'planning':
      case 'scoping':
      case 'coding':
      case 'testing':
      case 'reviewing':
        return (
          <span className="priority-badge priority-high">
            ● RUNNING
          </span>
        );
      case 'awaiting_approval':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', border: '1px solid rgba(59, 130, 246, 0.3)' }}>
            ● AWAITING APPROVAL
          </span>
        );
      case 'changes_requested':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ● CHANGES REQUESTED
          </span>
        );
      case 'cancelled':
        return (
          <span className="priority-badge" style={{ background: 'rgba(100, 116, 139, 0.15)', color: '#94a3b8', border: '1px solid rgba(100, 116, 139, 0.3)' }}>
            ● CANCELLED
          </span>
        );
      case 'completed':
        return (
          <span className="priority-badge priority-low">
            ● COMPLETED
          </span>
        );
      case 'delivery_failed':
        return (
          <span className="priority-badge priority-medium" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
            ● DELIVERY FAILED
          </span>
        );
      case 'failed':
        return (
          <span className="priority-badge priority-critical">
            ● FAILED
          </span>
        );
      case 'queued':
      default:
        return (
          <span className="priority-badge priority-medium">
            ● QUEUED
          </span>
        );
    }
  };

  const handleRunPlanner = async (taskId: string) => {
    setActionError(null);
    setRunningTaskId(taskId);
    try {
      const updated = await runBackendTask(taskId);
      if (onUpdateBackendTask) {
        onUpdateBackendTask(updated);
      }
      if (selectedTaskForPlan && selectedTaskForPlan.id === taskId) {
        setSelectedTaskForPlan(updated);
      }
      onRefreshBackend();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setActionError(err.message);
      } else {
        setActionError('Planner çalıştırılırken bir hata oluştu.');
      }
    } finally {
      setRunningTaskId(null);
    }
  };

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <h2 className="view-title">Autonomous Task Board</h2>
          <p className="view-subtitle">
            FastAPI Backend ve LangGraph Planner Agent tarafından yönetilen gerçek görevler ve planlar
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            className="sim-btn"
            style={{ padding: '8px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
            onClick={onRefreshBackend}
            disabled={isLoadingBackend}
            title="Backend görevlerini yeniden yükle (GET /tasks)"
          >
            <RefreshCw size={14} className={isLoadingBackend ? 'animate-spin' : ''} />
            <span>Yenile</span>
          </button>
          <button className="btn-primary-action" onClick={onOpenNewTaskModal}>
            <Plus size={16} />
            <span>New Task</span>
          </button>
        </div>
      </div>

      {/* Tabs: Backend API Tasks vs Demo Tasks */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
        <button
          onClick={() => setActiveTab('backend')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 16px',
            background: activeTab === 'backend' ? 'var(--accent-primary, #3b82f6)' : 'transparent',
            color: activeTab === 'backend' ? '#fff' : 'var(--text-secondary, #94a3b8)',
            borderRadius: '6px',
            border: 'none',
            fontWeight: 600,
            fontSize: '0.875rem',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          <Server size={15} />
          <span>Gerçek API Görevleri & Planlar ({backendTasks.length})</span>
          <span style={{ fontSize: '0.7rem', padding: '2px 6px', borderRadius: '4px', background: 'rgba(255,255,255,0.2)' }}>
            GET /tasks
          </span>
        </button>

        <button
          onClick={() => setActiveTab('demo')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 16px',
            background: activeTab === 'demo' ? 'var(--accent-primary, #3b82f6)' : 'transparent',
            color: activeTab === 'demo' ? '#fff' : 'var(--text-secondary, #94a3b8)',
            borderRadius: '6px',
            border: 'none',
            fontWeight: 600,
            fontSize: '0.875rem',
            cursor: 'pointer',
            transition: 'all 0.2s'
          }}
        >
          <Layers size={15} />
          <span>Demo Simülasyon Görevleri ({demoTasks.length})</span>
        </button>
      </div>

      {/* Content for Backend Tasks Tab */}
      {activeTab === 'backend' && (
        <div>
          {/* Action Error Banner */}
          {actionError && (
            <div className="form-error-banner" style={{ marginBottom: '16px' }}>
              <AlertCircle size={16} />
              <span>{actionError}</span>
            </div>
          )}

          {/* Backend Connection Error State */}
          {backendError && (
            <div className="form-error-banner" style={{ marginBottom: '20px', padding: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <AlertCircle size={18} />
                <div>
                  <strong>Backend Bağlantı Hatası:</strong> {backendError}
                </div>
              </div>
              <button
                className="sim-btn"
                onClick={onRefreshBackend}
                style={{ padding: '4px 10px', fontSize: '0.75rem' }}
              >
                Yeniden Dene
              </button>
            </div>
          )}

          {/* Loading State */}
          {isLoadingBackend && (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 12px' }} />
              <p>Backend'den görevler ve planlar yükleniyor (GET /tasks)...</p>
            </div>
          )}

          {/* Empty State */}
          {!isLoadingBackend && !backendError && backendTasks.length === 0 && (
            <div style={{ padding: '48px', textAlign: 'center', background: 'var(--card-bg)', borderRadius: '8px', border: '1px dashed var(--border-color)' }}>
              <Server size={36} style={{ color: 'var(--text-secondary)', margin: '0 auto 12px', opacity: 0.6 }} />
              <h3 style={{ fontSize: '1.1rem', marginBottom: '6px' }}>Henüz Backend Görevi Yok</h3>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', maxWidth: '440px', margin: '0 auto 16px' }}>
                FastAPI servisine henüz kayıtlı bir görev bulunmuyor. Yeni bir görev oluşturarak <code>POST /tasks</code> ve <code>POST /tasks/run</code> endpoint'lerini test edebilirsiniz.
              </p>
              <button className="btn-primary-action" onClick={onOpenNewTaskModal} style={{ margin: '0 auto' }}>
                <Plus size={15} />
                <span>İlk Görevi Oluştur & Planla</span>
              </button>
            </div>
          )}

          {/* Tasks Grid with Real Plans */}
          {!isLoadingBackend && backendTasks.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: '16px' }}>
              {backendTasks.map((task) => {
                const isRunning = runningTaskId === task.id;
                const hasPlan = !!task.plan;

                return (
                  <div
                    key={task.id}
                    className="board-task-card active-card"
                    style={{
                      borderLeft: task.status === 'reviewed' ? '3px solid #c084fc' : task.status === 'tested' ? '3px solid #10b981' : task.status === 'blocked' ? '3px solid #ef4444' : task.status === 'coded' ? '3px solid #38bdf8' : task.status === 'scoped' ? '3px solid #38bdf8' : task.status === 'planned' ? '3px solid #3b82f6' : task.status === 'unsupported' ? '3px solid #f59e0b' : task.status === 'failed' ? '3px solid #ef4444' : '3px solid #64748b',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between'
                    }}
                  >
                    <div>
                      {/* Top Header */}
                      <div className="board-card-top" style={{ marginBottom: '10px' }}>
                        <span className="task-id-badge" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa' }}>
                          {task.id}
                        </span>
                        {getStatusBadge(task.status)}
                      </div>

                      {/* Task Description */}
                      <p className="board-task-desc" style={{ color: 'var(--text-primary)', fontSize: '0.92rem', fontWeight: 500, marginBottom: '12px' }}>
                        {task.description}
                      </p>

                      {/* If Coder Output Exists */}
                      {task.coder && (
                        <div style={{ background: task.coder.status === 'coded' ? 'rgba(56, 189, 248, 0.08)' : 'rgba(245, 158, 11, 0.08)', border: `1px solid ${task.coder.status === 'coded' ? 'rgba(56, 189, 248, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`, borderRadius: '6px', padding: '8px 10px', marginBottom: '8px' }}>
                          <span style={{ fontSize: '0.72rem', fontWeight: 700, color: task.coder.status === 'coded' ? '#38bdf8' : '#f59e0b', textTransform: 'uppercase' }}>
                            Coder: {task.coder.status === 'coded' ? `${task.coder.created_files.length} Dosya Üretildi` : 'Desteklenmeyen Görev'}
                          </span>
                        </div>
                      )}

                      {/* If Tester Output Exists */}
                      {task.tester && (
                        <div style={{ background: task.tester.status === 'tested' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)', border: `1px solid ${task.tester.status === 'tested' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'}`, borderRadius: '6px', padding: '8px 10px', marginBottom: '8px' }}>
                          <span style={{ fontSize: '0.72rem', fontWeight: 700, color: task.tester.status === 'tested' ? '#10b981' : '#ef4444', textTransform: 'uppercase' }}>
                            Tester: {task.tester.status === 'tested' ? `${task.tester.passed} Test Başarılı (0 Hata)` : task.tester.status === 'blocked' ? 'İzolasyon Nedeniyle Engellendi' : `${task.tester.failed} Test Başarısız`}
                          </span>
                          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '2px 0 0', lineHeight: '1.3' }}>
                            {task.tester.summary}
                          </p>
                        </div>
                      )}

                      {/* If Reviewer Output Exists */}
                      {task.reviewer && (
                        <div style={{ background: 'rgba(168, 85, 247, 0.08)', border: `1px solid ${task.reviewer.verdict === 'approved' ? 'rgba(16, 185, 129, 0.3)' : task.reviewer.verdict === 'changes_requested' ? 'rgba(245, 158, 11, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`, borderRadius: '6px', padding: '8px 10px', marginBottom: '10px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.72rem', fontWeight: 700, color: '#c084fc', textTransform: 'uppercase' }}>
                              Reviewer: {task.reviewer.verdict.toUpperCase()}
                            </span>
                            <span style={{ fontSize: '0.7rem', color: task.reviewer.findings.length > 0 ? '#f59e0b' : '#10b981' }}>
                              {task.reviewer.findings.length} Bulgu
                            </span>
                          </div>
                          <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '2px 0 0', lineHeight: '1.3' }}>
                            {task.reviewer.summary}
                          </p>
                        </div>
                      )}

                      {/* If Plan Exists (status === 'planned' or scoped/coded) */}
                      {hasPlan && task.plan && (
                        <div style={{ background: 'rgba(59, 130, 246, 0.06)', border: '1px solid rgba(59, 130, 246, 0.2)', borderRadius: '6px', padding: '10px 12px', marginBottom: '12px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#60a5fa', fontSize: '0.78rem', fontWeight: 600, marginBottom: '4px' }}>
                            <Target size={13} />
                            <span>HEDEF (GOAL)</span>
                          </div>
                          <p style={{ fontSize: '0.82rem', color: 'var(--text-primary)', margin: 0, lineHeight: '1.4', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                            {task.plan.goal}
                          </p>

                          {/* Quick Counters */}
                          <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: '0.72rem', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '2px 6px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <ListOrdered size={11} />
                              {task.plan.subtasks.length} Alt Adım
                            </span>
                            <span style={{ fontSize: '0.72rem', background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', padding: '2px 6px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <CheckSquare size={11} />
                              {task.plan.acceptance_criteria.length} Kriter
                            </span>
                            {task.plan.risks && task.plan.risks.length > 0 && (
                              <span style={{ fontSize: '0.72rem', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', padding: '2px 6px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <AlertTriangle size={11} />
                                {task.plan.risks.length} Risk
                              </span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* If Task Failed */}
                      {task.status === 'failed' && (
                        <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.25)', borderRadius: '6px', padding: '8px 10px', marginBottom: '12px', fontSize: '0.8rem', color: '#ef4444' }}>
                          {task.error || 'İş akışı başarısız oldu.'}
                        </div>
                      )}

                      {/* Events summary */}
                      {task.events && task.events.length > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '10px' }}>
                          <Activity size={12} />
                          <span>{task.events.length} olay kaydedildi</span>
                        </div>
                      )}
                    </div>

                    {/* Card Actions & Footer */}
                    <div>
                      <div style={{ display: 'flex', gap: '8px', marginBottom: '10px' }}>
                        {/* View Plan Button */}
                        <button
                          type="button"
                          className="sim-btn"
                          style={{ flex: 1, padding: '6px 10px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                          onClick={() => setSelectedTaskForPlan(task)}
                        >
                          <Eye size={13} />
                          <span>{hasPlan ? "Planı İncele" : "Detaylar"}</span>
                        </button>

                        {/* Run Planner Button (if queued) */}
                        {task.status === 'queued' && (
                          <button
                            type="button"
                            className="btn-primary-action"
                            style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px' }}
                            onClick={() => handleRunPlanner(task.id)}
                            disabled={isRunning}
                          >
                            {isRunning ? (
                              <RefreshCw size={12} className="animate-spin" />
                            ) : (
                              <Sparkles size={12} />
                            )}
                            <span>{isRunning ? "Planlanıyor..." : "Planla"}</span>
                          </button>
                        )}
                      </div>

                      <div className="board-card-footer" style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px' }}>
                        <div className="branch-tag" style={{ color: '#10b981' }}>
                          <CheckCircle2 size={12} />
                          <span>FastAPI Verified</span>
                        </div>
                        <span className="task-time" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Clock size={11} />
                          {formatTimestamp(task.created_at)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Content for Demo Tasks Tab */}
      {activeTab === 'demo' && (
        <div>
          <div style={{ background: 'rgba(234, 179, 8, 0.08)', border: '1px solid rgba(234, 179, 8, 0.25)', padding: '10px 14px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.85rem', color: '#facc15', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FileText size={15} />
            <span>Bu liste arayüz önizlemesi için kullanılan yerel örnek demo görevleridir. Gerçek API görevleri ve Planner çıktıları için "Gerçek API Görevleri & Planlar" sekmesine bakınız.</span>
          </div>

          <div className="task-columns-grid">
            {/* In Progress Column */}
            <div className="task-column">
              <div className="column-header">
                <div className="col-title-left">
                  <span className="col-dot blue" />
                  <span className="col-title">In Progress (Demo)</span>
                </div>
                <span className="col-count">
                  {demoTasks.filter((t) => t.status === 'in_progress').length}
                </span>
              </div>

              <div className="column-cards-list">
                {demoTasks
                  .filter((t) => t.status === 'in_progress')
                  .map((task) => (
                    <div key={task.id} className="board-task-card active-card">
                      <div className="board-card-top">
                        <span className="task-id-badge">{task.id}</span>
                        <span className={`priority-badge priority-${task.priority}`}>
                          {task.priority}
                        </span>
                      </div>
                      <h4 className="board-task-title">{task.title}</h4>
                      <p className="board-task-desc">{task.description}</p>
                      <div className="board-card-footer">
                        <div className="branch-tag">
                          <GitBranch size={12} />
                          <span>{task.branch}</span>
                        </div>
                        <span className="task-time">{task.createdAt}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            {/* Completed Column */}
            <div className="task-column">
              <div className="column-header">
                <div className="col-title-left">
                  <span className="col-dot green" />
                  <span className="col-title">Completed (Demo)</span>
                </div>
                <span className="col-count">
                  {demoTasks.filter((t) => t.status === 'completed').length}
                </span>
              </div>

              <div className="column-cards-list">
                {demoTasks
                  .filter((t) => t.status === 'completed')
                  .map((task) => (
                    <div key={task.id} className="board-task-card">
                      <div className="board-card-top">
                        <span className="task-id-badge">{task.id}</span>
                        <span className={`priority-badge priority-${task.priority}`}>
                          {task.priority}
                        </span>
                      </div>
                      <h4 className="board-task-title">{task.title}</h4>
                      <p className="board-task-desc">{task.description}</p>
                      <div className="board-card-footer">
                        <div className="branch-tag">
                          <GitBranch size={12} />
                          <span>{task.branch}</span>
                        </div>
                        <span className="task-time">{task.createdAt}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Task Plan Details Modal */}
      <TaskPlanModal
        isOpen={!!selectedTaskForPlan}
        onClose={() => setSelectedTaskForPlan(null)}
        task={selectedTaskForPlan}
        onRunWorkflow={handleRunPlanner}
        isRunningWorkflow={runningTaskId === selectedTaskForPlan?.id}
        onTaskUpdated={(updated) => {
          setSelectedTaskForPlan(updated);
          if (onUpdateBackendTask) {
            onUpdateBackendTask(updated);
          }
          onRefreshBackend();
        }}
      />
    </div>
  );
};

