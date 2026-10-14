import { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { Timeline } from './components/Pipeline/Timeline';
import { AgentCards } from './components/Agents/AgentCards';
import { OutputLogs } from './components/Terminal/OutputLogs';
import { NewTaskModal } from './components/Modals/NewTaskModal';
import { AgentDetailModal } from './components/Modals/AgentDetailModal';
import { TaskPlanModal } from './components/Modals/TaskPlanModal';
import { AgentsView } from './components/Views/AgentsView';
import { RunsView } from './components/Views/RunsView';
import { TasksView } from './components/Views/TasksView';
import { FilesView } from './components/Views/FilesView';
import { SettingsView } from './components/Views/SettingsView';

import {
  INITIAL_STEPS,
  INITIAL_AGENTS,
  INITIAL_LOGS,
  INITIAL_TASKS
} from './data/mockData';

import type {
  NavTab,
  PipelineStep,
  StepKey,
  Agent,
  LogEntry,
  TaskItem,
  LogLevel,
  BackendTask,
  BackendTaskStatus,
  LLMProviderInfo
} from './types';

import {
  getBackendTasks,
  getBackendTaskById,
  getHealth,
  getLLMInfo,
  ApiError,
  API_BASE_URL
} from './services/api';
import './App.css';
import { Info, CheckCircle2, AlertCircle } from 'lucide-react';

const TERMINAL_STATUSES: BackendTaskStatus[] = [
  'reviewed',
  'tested',
  'coded',
  'scoped',
  'planned',
  'completed',
  'delivery_failed',
  'failed',
  'unsupported',
  'blocked',
  'cancelled',
  'changes_requested',
  'awaiting_approval'
];

function isTerminalStatus(status: BackendTaskStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function derivePipelineStepsFromTask(backendTask: BackendTask): PipelineStep[] {
  return INITIAL_STEPS.map((s, idx) => {
    // Step 1: Plan (Planner Agent)
    if (idx === 0) {
      const isPlanning = backendTask.status === 'planning';
      const hasPlan = !!backendTask.plan;
      const isFailed = backendTask.status === 'failed' && !hasPlan;

      return {
        ...s,
        status: isPlanning ? 'running' : hasPlan ? 'completed' : isFailed ? 'failed' : 'pending',
        duration: hasPlan ? '1.4s (Planner Agent)' : isPlanning ? 'Plan hazırlanıyor...' : '—',
        progress: hasPlan ? 100 : isPlanning ? 60 : 0,
        artifacts: hasPlan && backendTask.plan
          ? [
              {
                name: 'architecture-plan.json',
                type: 'JSON',
                size: '2.8 KB',
                description: backendTask.plan.goal
              }
            ]
          : []
      };
    }

    // Step 2: Scope (Scope Agent)
    if (idx === 1) {
      const isScoping = backendTask.status === 'scoping';
      const hasScope = !!backendTask.scope;
      const isFailed = backendTask.status === 'failed' && !hasScope && !backendTask.plan;

      return {
        ...s,
        status: isScoping ? 'running' : hasScope ? 'completed' : isFailed ? 'failed' : 'pending',
        duration: hasScope ? '0.8s (Scope Agent)' : isScoping ? 'Kapsam taranıyor...' : '—',
        progress: hasScope ? 100 : isScoping ? 50 : 0,
        artifacts: hasScope && backendTask.scope
          ? [
              {
                name: 'target_files_manifest.json',
                type: 'JSON',
                size: '2.1 KB',
                description: backendTask.scope.summary
              }
            ]
          : []
      };
    }

    // Step 3: Edit / Coder (Coder Agent)
    if (idx === 2) {
      const isCoding = backendTask.status === 'coding';
      const isCoded = backendTask.coder && backendTask.coder.status === 'coded';
      const isUnsupported = backendTask.coder && backendTask.coder.status === 'unsupported';
      const isFailed = (backendTask.coder && backendTask.coder.status === 'failed') || isUnsupported;

      return {
        ...s,
        status: isCoding ? 'running' : isCoded ? 'completed' : isFailed ? 'failed' : 'pending',
        duration: isCoded ? '1.2s (Coder Agent)' : isUnsupported ? 'Desteklenmeyen Şablon' : isCoding ? 'Kod üretiliyor...' : '—',
        progress: isCoded ? 100 : isCoding ? 65 : 0,
        artifacts: isCoded && backendTask.coder
          ? backendTask.coder.created_files.map((cf) => {
              const filePath = typeof cf === 'string' ? cf : (cf?.path || 'file');
              const fileName = filePath.split('/').pop()?.split('\\').pop() || filePath;
              const fileSize = typeof cf === 'object' && cf?.bytes !== undefined ? `${cf.bytes} B` : '—';
              const fileDesc = typeof cf === 'object' && cf?.description ? cf.description : 'İzole alanda oluşturulan kaynak dosya';
              return {
                name: fileName,
                type: 'Python',
                size: fileSize,
                description: fileDesc
              };
            })
          : []
      };
    }

    // Step 4: Validate / Tester (Docker Tester Agent)
    if (idx === 3) {
      const isTesting = backendTask.status === 'testing';
      const isTested = backendTask.tester && backendTask.tester.status === 'tested';
      const isBlocked = backendTask.tester && backendTask.tester.status === 'blocked';
      const isFailed = backendTask.tester && (backendTask.tester.status === 'failed' || isBlocked);

      return {
        ...s,
        status: isTesting ? 'running' : isTested ? 'completed' : isFailed ? 'failed' : 'pending',
        duration: isTested ? `${backendTask.tester?.passed} test başarılı (Tester Agent)` : isBlocked ? 'İzolasyon Engeli' : isTesting ? 'Sandbox testleri koşuluyor...' : '—',
        progress: isTested ? 100 : isTesting ? 75 : isFailed ? 40 : 0,
        artifacts: isTested
          ? [
              {
                name: 'test_feature.py',
                type: 'Python Test',
                size: '1.8 KB',
                description: `${backendTask.tester?.passed} test senaryosu başarıyla doğrulandı.`
              }
            ]
          : []
      };
    }

    // Step 5: Review / Semantic Reviewer (AST & Rule Reviewer)
    if (idx === 4) {
      const isReviewing = backendTask.status === 'reviewing';
      const isReviewerDone = !!backendTask.reviewer;
      const isApproved = backendTask.reviewer?.verdict === 'approved';
      const isChangesRequested = backendTask.reviewer?.verdict === 'changes_requested';
      const isBlocked = backendTask.reviewer?.verdict === 'blocked';

      return {
        ...s,
        status: isReviewing ? 'running' : isApproved ? 'completed' : (isChangesRequested || isBlocked) ? 'failed' : 'pending',
        duration: isApproved ? 'Approved (Reviewer)' : isChangesRequested ? 'Changes Requested' : isBlocked ? 'Blocked' : isReviewing ? 'AST ve semantik kurallar inceleniyor...' : '—',
        progress: isApproved ? 100 : isReviewerDone ? 75 : isReviewing ? 80 : 0,
        artifacts: isReviewerDone
          ? [
              {
                name: 'code_review_report.json',
                type: 'JSON Report',
                size: '1.4 KB',
                description: backendTask.reviewer?.summary || 'Statik kod inceleme raporu'
              }
            ]
          : []
      };
    }

    // Step 6: PR (Standby / Complete)
    const isWorkflowFinished = backendTask.status === 'completed' || (backendTask.reviewer?.verdict === 'approved' && backendTask.status === 'reviewed');
    return {
      ...s,
      status: isWorkflowFinished ? 'completed' : 'pending',
      duration: isWorkflowFinished ? 'Hazır' : '—',
      progress: isWorkflowFinished ? 100 : 0,
      artifacts: []
    };
  });
}

function deriveAgentsFromTask(backendTask: BackendTask, baseAgents: Agent[]): Agent[] {
  return baseAgents.map((ag) => {
    if (ag.id === 'agent-architect') {
      const isPlanning = backendTask.status === 'planning';
      const hasPlan = !!backendTask.plan;
      return {
        ...ag,
        status: isPlanning ? 'running' : hasPlan ? 'completed' : 'idle',
        lastActivity: hasPlan ? 'Plan başarıyla oluşturuldu' : isPlanning ? 'Gereksinimler ayrıştırılıyor...' : ag.lastActivity
      };
    }
    if (ag.id === 'agent-scope') {
      const isScoping = backendTask.status === 'scoping';
      const hasScope = !!backendTask.scope;
      return {
        ...ag,
        status: isScoping ? 'running' : hasScope ? 'completed' : 'idle',
        lastActivity: hasScope ? `${backendTask.scope?.proposed_new_files.length || 0} dosya kapsama alındı` : isScoping ? 'Bağımlılıklar taranıyor...' : ag.lastActivity
      };
    }
    if (ag.id === 'agent-coder') {
      const isCoding = backendTask.status === 'coding';
      const isCoded = backendTask.coder && backendTask.coder.status === 'coded';
      const isFailed = backendTask.coder && (backendTask.coder.status === 'failed' || backendTask.coder.status === 'unsupported');
      return {
        ...ag,
        status: isCoding ? 'running' : isCoded ? 'completed' : isFailed ? 'error' : 'idle',
        lastActivity: isCoded ? `${backendTask.coder?.created_files.length} dosya yazıldı` : isCoding ? 'Kaynak kod üretiliyor...' : ag.lastActivity
      };
    }
    if (ag.id === 'agent-test') {
      const isTesting = backendTask.status === 'testing';
      const isTested = backendTask.tester && backendTask.tester.status === 'tested';
      const isBlocked = backendTask.tester && backendTask.tester.status === 'blocked';
      const isFailed = backendTask.tester && backendTask.tester.status === 'failed';
      return {
        ...ag,
        status: isTesting ? 'running' : isTested ? 'completed' : (isBlocked || isFailed) ? 'error' : 'idle',
        lastActivity: isTested ? `${backendTask.tester?.passed} test doğrulandı` : isBlocked ? 'Güvenlik nedeniyle bloklandı' : isTesting ? 'Docker sandbox yürütülüyor...' : ag.lastActivity
      };
    }
    if (ag.id === 'agent-security' || ag.id === 'agent-reviewer') {
      const isReviewing = backendTask.status === 'reviewing';
      const isApproved = backendTask.reviewer?.verdict === 'approved';
      const isRejected = backendTask.reviewer && backendTask.reviewer.verdict !== 'approved';
      return {
        ...ag,
        status: isReviewing ? 'running' : isApproved ? 'completed' : isRejected ? 'error' : 'idle',
        lastActivity: isApproved ? 'Kod incelemesi onaylandı' : isRejected ? `Bulgu: ${backendTask.reviewer?.findings.length}` : isReviewing ? 'AST doğrulaması yapılıyor...' : ag.lastActivity
      };
    }
    return ag;
  });
}

function App() {
  const [activeTab, setActiveTab] = useState<NavTab>('orchestration');
  const [steps, setSteps] = useState<PipelineStep[]>(INITIAL_STEPS);
  const [selectedStepKey, setSelectedStepKey] = useState<StepKey>('plan');
  const [agents, setAgents] = useState<Agent[]>(INITIAL_AGENTS);
  const [logs, setLogs] = useState<LogEntry[]>(INITIAL_LOGS);
  const [demoTasks, setDemoTasks] = useState<TaskItem[]>(INITIAL_TASKS);

  // Backend API states
  const [backendTasks, setBackendTasks] = useState<BackendTask[]>([]);
  const [activeBackendTask, setActiveBackendTask] = useState<BackendTask | null>(null);
  const [isLoadingBackend, setIsLoadingBackend] = useState<boolean>(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean | null>(null);
  const [llmInfo, setLlmInfo] = useState<LLMProviderInfo | null>(null);

  // Modals & Drawers
  const [isNewTaskModalOpen, setIsNewTaskModalOpen] = useState(false);
  const [selectedAgentForModal, setSelectedAgentForModal] = useState<Agent | null>(null);
  const [selectedTaskForPlanModal, setSelectedTaskForPlanModal] = useState<BackendTask | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Set of already logged backend event IDs to avoid duplicate log rows
  const loggedEventIdsRef = useRef<Set<string>>(new Set());
  const isPollingBusyRef = useRef<boolean>(false);

  // Toast notification for user feedback
  const [toastMessage, setToastMessage] = useState<{
    text: string;
    type: 'info' | 'success' | 'warning';
  } | null>(null);

  const showToast = useCallback((text: string, type: 'info' | 'success' | 'warning' = 'info') => {
    setToastMessage({ text, type });
    setTimeout(() => {
      setToastMessage(null);
    }, 4500);
  }, []);

  const addLog = useCallback((
    message: string,
    level: LogLevel = 'info',
    source: string = 'SYSTEM',
    stepKey?: StepKey
  ) => {
    const timeStr = new Date().toLocaleTimeString('tr-TR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
    const newEntry: LogEntry = {
      id: `log-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
      timestamp: timeStr,
      level,
      source,
      message,
      stepKey
    };
    setLogs((prev) => [...prev, newEntry]);
  }, []);

  // Synchronize a task and its events into the UI state
  const syncTaskIntoState = useCallback((task: BackendTask, options?: { showNotification?: boolean }) => {
    setActiveBackendTask(task);
    setBackendTasks((prev) => [task, ...prev.filter((t) => t.id !== task.id)]);

    // Update pipeline steps
    const newSteps = derivePipelineStepsFromTask(task);
    setSteps(newSteps);

    // Update agents cards
    setAgents((prev) => deriveAgentsFromTask(task, prev));

    // Auto-select latest active step
    if (task.reviewer) {
      setSelectedStepKey('review');
    } else if (task.tester) {
      setSelectedStepKey('validate');
    } else if (task.coder) {
      setSelectedStepKey('edit');
    } else if (task.scope) {
      setSelectedStepKey('scope');
    } else if (task.plan) {
      setSelectedStepKey('plan');
    }

    // Ingest events into logs without duplicating
    if (task.events && task.events.length > 0) {
      task.events.forEach((evt) => {
        if (!loggedEventIdsRef.current.has(evt.id)) {
          loggedEventIdsRef.current.add(evt.id);
          const level: LogLevel = evt.type.includes('failed') || evt.type.includes('blocked')
            ? 'error'
            : evt.type.includes('completed') || evt.type.includes('created') || evt.type.includes('approved')
            ? 'success'
            : evt.source.includes('AGENT')
            ? 'agent'
            : 'info';

          const stepKey: StepKey | undefined =
            evt.source === 'REVIEWER_AGENT'
              ? 'review'
              : evt.source === 'TESTER_AGENT'
              ? 'validate'
              : evt.source === 'CODER_AGENT'
              ? 'edit'
              : evt.source === 'SCOPE_AGENT'
              ? 'scope'
              : evt.source === 'PLANNER_AGENT'
              ? 'plan'
              : undefined;

          addLog(`[${evt.source}] ${evt.message}`, level, evt.source, stepKey);
        }
      });
    }

    // Optional notification on state change
    if (options?.showNotification) {
      if (task.status === 'reviewed' && task.reviewer?.verdict === 'approved') {
        showToast(`Tüm pipeline adımları başarıyla tamamlandı ve onaylandı! (${task.id})`, 'success');
      } else if (task.status === 'blocked' || task.reviewer?.verdict === 'blocked') {
        showToast(`Görev güvenlik/izolasyon engeli nedeniyle durduruldu (${task.id})`, 'warning');
      } else if (task.status === 'unsupported' || task.coder?.status === 'unsupported') {
        showToast(`Desteklenmeyen görev şablonu (${task.id})`, 'warning');
      } else if (task.status === 'changes_requested' || task.reviewer?.verdict === 'changes_requested') {
        showToast(`İnceleme aşamasında değişiklik talep edildi (${task.id})`, 'warning');
      } else if (task.status === 'delivery_failed') {
        showToast(`Git teslimatı başarısız oldu (${task.id}). Akış baştan başlatılmadı.`, 'warning');
      } else if (task.status === 'failed') {
        showToast(`Görev iş akışı başarısız oldu (${task.id})`, 'warning');
      }
    }
  }, [addLog, showToast]);

  // Fetch tasks from FastAPI Backend (GET /tasks)
  const fetchBackendTasks = useCallback(async () => {
    setIsLoadingBackend(true);
    setBackendError(null);
    try {
      const data = await getBackendTasks();
      setBackendTasks(data);
      setIsBackendConnected(true);
      if (data.length > 0 && !activeBackendTask) {
        const topTask = data[0];
        syncTaskIntoState(topTask);
      }
    } catch (err: unknown) {
      setIsBackendConnected(false);
      const errMsg = err instanceof ApiError ? err.message : 'Backend ile bağlantı kurulamadı.';
      setBackendError(errMsg);
    } finally {
      setIsLoadingBackend(false);
    }
  }, [activeBackendTask, syncTaskIntoState]);

  // Initial load: Check health, LLM info & fetch backend tasks
  useEffect(() => {
    let isMounted = true;
    const initBackend = async () => {
      try {
        const health = await getHealth();
        if (isMounted) setIsBackendConnected(true);
        addLog(
          `[BACKEND API CONNECTED] FastAPI servisi aktif (${API_BASE_URL}) — ${health.message}`,
          'success',
          'API_CLIENT'
        );

        try {
          const info = await getLLMInfo();
          if (isMounted) setLlmInfo(info);
          if (info.provider === 'mock') {
            addLog(
              `[LLM PROVIDER] Mock LLM modu aktif (${info.model}). Tüm ajanlar güvenli deterministik şablonlarla çalışmaktadır.`,
              'info',
              'LLM_ENGINE'
            );
          } else {
            addLog(
              `[LLM PROVIDER] Aktif Sağlayıcı: ${info.provider} (${info.model})`,
              'info',
              'LLM_ENGINE'
            );
          }
        } catch {
          // LLM info fallback
        }
      } catch (err: unknown) {
        if (isMounted) setIsBackendConnected(false);
        const msg = err instanceof ApiError ? err.message : 'FastAPI bağlantı hatası';
        addLog(`[BACKEND API OFFLINE] ${msg}`, 'warn', 'API_CLIENT');
      }

      await fetchBackendTasks();
    };

    initBackend();
    return () => {
      isMounted = false;
    };
  }, [addLog, fetchBackendTasks]);

  // Polling Effect: Track active task until terminal state is reached
  useEffect(() => {
    if (!activeBackendTask?.id) return;
    if (isTerminalStatus(activeBackendTask.status)) return;

    const currentTaskId = activeBackendTask.id;
    const intervalId = setInterval(async () => {
      if (isPollingBusyRef.current) return;
      isPollingBusyRef.current = true;

      try {
        const updated = await getBackendTaskById(currentTaskId);
        syncTaskIntoState(updated, { showNotification: isTerminalStatus(updated.status) });
      } catch {
        // Silent poll error handling
      } finally {
        isPollingBusyRef.current = false;
      }
    }, 1200);

    return () => {
      clearInterval(intervalId);
    };
  }, [activeBackendTask?.id, activeBackendTask?.status, syncTaskIntoState]);

  const handleSelectStep = (stepKey: StepKey) => {
    setSelectedStepKey(stepKey);
    const step = steps.find((s) => s.key === stepKey);
    if (step) {
      addLog(
        `Seçili adım inceleniyor: [${step.name}] — Durum: ${step.status.toUpperCase()} (${step.assignedAgent})`,
        'info',
        'UI',
        stepKey
      );
    }
  };

  const handleSelectAgent = (agent: Agent) => {
    setSelectedAgentForModal(agent);
  };

  // Advance demo pipeline (Manuel demo ilerletme)
  const handleAdvanceDemoStep = () => {
    const currentIndex = steps.findIndex((s) => s.status === 'running');

    if (currentIndex === -1) {
      const firstPending = steps.findIndex((s) => s.status === 'pending');
      if (firstPending !== -1) {
        const nextSteps = [...steps];
        nextSteps[firstPending] = {
          ...nextSteps[firstPending],
          status: 'running',
          duration: '3.2s (devam ediyor)',
          progress: 30
        };
        setSteps(nextSteps);
        setSelectedStepKey(nextSteps[firstPending].key);
        addLog(
          `[DEMO SIMULATION] ${nextSteps[firstPending].name} aşaması başlatıldı (${nextSteps[firstPending].assignedAgent})`,
          'agent',
          'ORCHESTRATOR'
        );
        showToast(`${nextSteps[firstPending].name} aşaması simülasyonu başlatıldı`, 'info');
      } else {
        showToast('Tüm adımlar tamamlandı. "Reset Demo" ile sıfırlayabilirsiniz.', 'success');
      }
      return;
    }

    const nextSteps = [...steps];
    const completedStep = {
      ...nextSteps[currentIndex],
      status: 'completed' as const,
      duration: '12.4s',
      progress: 100
    };
    nextSteps[currentIndex] = completedStep;

    addLog(
      `[DEMO SIMULATION] Adım ${completedStep.stepNumber} [${completedStep.name}] başarıyla tamamlandı.`,
      'success',
      'PIPELINE'
    );

    if (currentIndex + 1 < nextSteps.length) {
      const nextStep = {
        ...nextSteps[currentIndex + 1],
        status: 'running' as const,
        duration: '1.8s (devam ediyor)',
        progress: 25
      };
      nextSteps[currentIndex + 1] = nextStep;
      setSelectedStepKey(nextStep.key);

      addLog(
        `[DEMO SIMULATION] Sonraki aşama başlatıldı: [${nextStep.name}] -> Sorumlu: ${nextStep.assignedAgent}`,
        'agent',
        'ORCHESTRATOR'
      );
      showToast(`Pipeline ${nextStep.name} aşamasına ilerletildi`, 'info');
    } else {
      addLog(
        `[DEMO SIMULATION] Tüm pipeline aşamaları başarıyla tamamlandı!`,
        'success',
        'SYSTEM'
      );
      showToast('Tüm pipeline adımları tamamlandı! PR taslağı hazırlandı.', 'success');
    }

    setSteps(nextSteps);
  };

  const handleResetDemo = () => {
    setSteps(INITIAL_STEPS);
    setSelectedStepKey('plan');
    setAgents(INITIAL_AGENTS);
    setLogs(INITIAL_LOGS);
    setActiveBackendTask(null);
    addLog('Pipeline durumu başlangıç değerlerine sıfırlandı.', 'system', 'SYSTEM');
    showToast('Demo durumu başarıyla sıfırlandı', 'info');
  };

  // Called when a real backend task is created & processed via NewTaskModal
  const handleTaskCreated = (
    backendTask: BackendTask,
    extraInfo?: {
      title: string;
      priority: 'low' | 'medium' | 'high' | 'critical';
      branch: string;
      selectedAgents: string[];
    }
  ) => {
    // Add to demoTasks for runs list display
    const taskItem: TaskItem = {
      id: backendTask.id,
      title: extraInfo?.title || backendTask.description.slice(0, 50),
      description: backendTask.description,
      priority: extraInfo?.priority || 'high',
      status: backendTask.status === 'queued' ? 'queued' : 'in_progress',
      createdAt: 'Az önce',
      branch: extraInfo?.branch || 'main',
      assignedAgents: extraInfo?.selectedAgents || ['Architect', 'Scope Lead', 'Coder', 'QA Tester', 'Reviewer'],
      currentStep: backendTask.reviewer ? 'review' : (backendTask.tester ? 'validate' : (backendTask.coder ? 'edit' : (backendTask.scope ? 'scope' : 'plan'))),
      source: 'backend',
      rawBackendData: backendTask
    };
    setDemoTasks((prev) => [taskItem, ...prev]);

    // Synchronize to full state & activate orchestration tab
    syncTaskIntoState(backendTask);
    setActiveTab('orchestration');

    addLog(`[POST /tasks HTTP 201] Gerçek Backend Görevi Kaydedildi: [${backendTask.id}]`, 'success', 'API_GATEWAY');

    showToast(
      backendTask.status === 'reviewed'
        ? `Tüm adımlar (Planner, Scope, Coder, Tester, Reviewer) tamamlandı! (${backendTask.id})`
        : backendTask.status === 'tested'
        ? `Planner, Scope, Coder & Tester tamamlandı! (${backendTask.id})`
        : backendTask.status === 'coded'
        ? `Planner, Scope & Coder tamamlandı! (${backendTask.id})`
        : backendTask.status === 'blocked'
        ? `Görev güvenlik kısıtı nedeniyle bloklandı (${backendTask.id})`
        : backendTask.status === 'unsupported'
        ? `Desteklenmeyen görev şablonu (${backendTask.id})`
        : `Backend Görevi Başlatıldı (${backendTask.id})`,
      backendTask.status === 'reviewed' || backendTask.status === 'tested' || backendTask.status === 'coded' ? 'success' : 'info'
    );
  };

  const handleUpdateBackendTask = (updatedTask: BackendTask) => {
    syncTaskIntoState(updatedTask, { showNotification: true });
  };

  const handlePingAgent = (agent: Agent) => {
    addLog(
      `[AGENT PING] ${agent.name} (${agent.model}) sağlık kontrolü başarılı. Gecikme: ${agent.latencyMs}ms`,
      'agent',
      agent.name ? agent.name.toUpperCase().split(' ')[0] : 'AGENT'
    );
    showToast(`${agent.name} yanıt verdi (${agent.latencyMs}ms)`, 'success');
  };

  const handleClearLogs = () => {
    const timeStr = new Date().toLocaleTimeString('tr-TR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
    setLogs([
      {
        id: `log-${Date.now()}`,
        timestamp: timeStr,
        level: 'system',
        source: 'SYSTEM',
        message: 'Log akışı temizlendi. [Backend API Stream Active]'
      }
    ]);
  };

  return (
    <div className="app-layout-root">
      {/* Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
      />

      {/* Main Workspace Column */}
      <div className="app-main-column">
        {/* Top Navigation Bar */}
        <TopBar
          onOpenMobileMenu={() => setIsSidebarOpen(true)}
          onOpenNewTaskModal={() => setIsNewTaskModalOpen(true)}
          onAdvanceDemoStep={handleAdvanceDemoStep}
          onResetDemo={handleResetDemo}
          llmInfo={llmInfo}
          isBackendConnected={isBackendConnected}
        />

        {/* Global Status Banner */}
        <div className="global-demo-alert-bar">
          <div className="alert-bar-content">
            <Info size={14} className="alert-bar-icon" />
            <span className="alert-bar-text">
              <strong>FastAPI + LangGraph:</strong> Backend: <code>{API_BASE_URL}</code>
              {isBackendConnected === true && (
                <span style={{ marginLeft: '8px', color: '#10b981', fontWeight: 600 }}>
                  ● Bağlantı Aktif ({backendTasks.length} kayıtlı görev)
                </span>
              )}
              {llmInfo?.provider === 'mock' && (
                <span style={{ marginLeft: '8px', color: '#facc15', fontWeight: 600, background: 'rgba(234, 179, 8, 0.15)', padding: '2px 6px', borderRadius: '4px' }}>
                  ★ Mock LLM (Güvenli Yerel Mod)
                </span>
              )}
              {isBackendConnected === false && (
                <span style={{ marginLeft: '8px', color: '#ef4444', fontWeight: 600 }}>
                  ● Backend Çevrimdışı ({backendError || 'Sunucuya ulaşılamıyor'})
                </span>
              )}
            </span>
          </div>
          <button
            className="alert-sim-step-link"
            onClick={fetchBackendTasks}
            title="Backend görevlerini yeniden sorgula"
          >
            Yenile &rarr;
          </button>
        </div>

        {/* Dynamic View Area based on activeTab */}
        <main className="app-content-scrollable">
          {activeTab === 'orchestration' && (
            <div className="dashboard-grid-layout">
              {/* Center Panel: Autonomous Pipeline */}
              <section className="dashboard-pipeline-panel" aria-label="Autonomous Pipeline">
                <Timeline
                  steps={steps}
                  selectedStepKey={selectedStepKey}
                  onSelectStep={handleSelectStep}
                  activeBackendTask={activeBackendTask}
                  onOpenPlanModal={(task) => setSelectedTaskForPlanModal(task)}
                />
              </section>

              {/* Right Panel: Agent Activity */}
              <section className="dashboard-agents-panel" aria-label="Agent Activity">
                <AgentCards
                  agents={agents}
                  onSelectAgent={handleSelectAgent}
                  selectedAgentId={selectedAgentForModal?.id}
                />
              </section>

              {/* Bottom Panel: Output / Terminal */}
              <section className="dashboard-terminal-panel" aria-label="Output Logs">
                <OutputLogs
                  logs={logs}
                  onClearLogs={handleClearLogs}
                />
              </section>
            </div>
          )}

          {activeTab === 'agents' && (
            <AgentsView
              agents={agents}
              onSelectAgent={handleSelectAgent}
            />
          )}

          {activeTab === 'runs' && (
            <RunsView
              tasks={demoTasks}
              onSelectRun={(id) => {
                showToast(`Run #${id} ayrıntıları inceleniyor`, 'info');
                setActiveTab('orchestration');
              }}
            />
          )}

          {activeTab === 'tasks' && (
            <TasksView
              demoTasks={demoTasks}
              backendTasks={backendTasks}
              isLoadingBackend={isLoadingBackend}
              backendError={backendError}
              onRefreshBackend={fetchBackendTasks}
              onOpenNewTaskModal={() => setIsNewTaskModalOpen(true)}
              onUpdateBackendTask={handleUpdateBackendTask}
            />
          )}

          {activeTab === 'files' && <FilesView />}

          {activeTab === 'settings' && <SettingsView />}
        </main>
      </div>

      {/* Floating Toast Notification */}
      {toastMessage && (
        <div className={`app-toast toast-${toastMessage.type}`}>
          {toastMessage.type === 'success' ? (
            <CheckCircle2 size={16} className="toast-icon" />
          ) : toastMessage.type === 'warning' ? (
            <AlertCircle size={16} className="toast-icon" />
          ) : (
            <Info size={16} className="toast-icon" />
          )}
          <span className="toast-text">{toastMessage.text}</span>
        </div>
      )}

      {/* New Task Modal */}
      <NewTaskModal
        isOpen={isNewTaskModalOpen}
        onClose={() => setIsNewTaskModalOpen(false)}
        onTaskCreated={handleTaskCreated}
      />

      {/* Agent Detail Modal */}
      <AgentDetailModal
        agent={selectedAgentForModal}
        onClose={() => setSelectedAgentForModal(null)}
        onPingAgent={handlePingAgent}
      />

      {/* Task Plan & Scope Details Modal */}
      <TaskPlanModal
        isOpen={!!selectedTaskForPlanModal}
        onClose={() => setSelectedTaskForPlanModal(null)}
        task={selectedTaskForPlanModal}
        onTaskUpdated={handleUpdateBackendTask}
      />
    </div>
  );
}

export default App;

