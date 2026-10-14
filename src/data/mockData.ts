import type { PipelineStep, Agent, LogEntry, TaskItem, SystemStats } from '../types';

export const INITIAL_STEPS: PipelineStep[] = [
  {
    id: 'step-1',
    key: 'plan',
    stepNumber: 1,
    name: 'Plan',
    shortDesc: 'Gereksinimler analiz ediliyor.',
    detailedDesc: 'Görev istekleri analiz ediliyor, teknik gereksinimler, bağımlılıklar ve mimari uygulama planı RFC formatında çıkarılıyor.',
    status: 'completed',
    duration: '14.2s',
    assignedAgent: 'Architect Agent',
    agentRole: 'Planlama ve mimari',
    artifacts: [
      {
        name: 'spec_rfc_084.md',
        type: 'markdown',
        size: '4.8 KB',
        description: 'Gereksinim analizi ve mimari planlama dokümanı'
      },
      {
        name: 'architecture_diagram.json',
        type: 'json',
        size: '1.2 KB',
        description: 'Modüler bileşen akış şeması ve sınır durumları'
      }
    ],
    progress: 100,
    inputs: ['Kullanıcı görev tanımı', 'Repo config / tsconfig.json', 'README.md'],
    outputs: ['Teknik mimari spesifikasyonu', 'Risk ve edge-case analiz raporu']
  },
  {
    id: 'step-2',
    key: 'scope',
    stepNumber: 2,
    name: 'Scope',
    shortDesc: 'Değişecek dosyalar belirleniyor.',
    detailedDesc: 'Depo indekslenerek kod bağımlılık ağacı taranıyor; etkilenecek ve yeni oluşturulacak kaynak dosyalar tespit ediliyor.',
    status: 'completed',
    duration: '8.7s',
    assignedAgent: 'Architect Agent',
    agentRole: 'Planlama ve mimari',
    artifacts: [
      {
        name: 'target_files_manifest.json',
        type: 'json',
        size: '2.1 KB',
        description: 'Değişiklik yapılacak dosya listesi ve bağımlılık haritası'
      }
    ],
    progress: 100,
    inputs: ['spec_rfc_084.md', 'AST Dependency Graph'],
    outputs: ['4 hedef dosya tespit edildi', 'Import/Export bağımlılıkları doğrulandı']
  },
  {
    id: 'step-3',
    key: 'edit',
    stepNumber: 3,
    name: 'Edit',
    shortDesc: 'Kod oluşturuluyor veya düzenleniyor.',
    detailedDesc: 'Coder Agent, mimari plana ve kapsam listesine göre TypeScript tiplerini, servisleri ve hata yönetim mekanizmalarını yazıyor.',
    status: 'pending',
    duration: '—',
    assignedAgent: 'Coder Agent',
    agentRole: 'Kod üretimi',
    artifacts: [],
    progress: 0,
    inputs: ['target_files_manifest.json', 'spec_rfc_084.md'],
    outputs: ['Bileşen kodları', 'Tip arayüz tanımları', 'Diff yamaları']
  },
  {
    id: 'step-4',
    key: 'validate',
    stepNumber: 4,
    name: 'Validate',
    shortDesc: 'Testler ve kalite kontrolleri çalışıyor.',
    detailedDesc: 'Birim testleri, lint kuralları, TypeScript derleme kontrolü ve güvenlik açığı (SAST) taramaları sırayla icra edilecek.',
    status: 'pending',
    duration: '—',
    assignedAgent: 'Test & Security Agent',
    agentRole: 'Test ve Güvenlik',
    artifacts: [],
    progress: 0,
    inputs: ['Üretilen kod yamaları', 'Test senaryoları', 'OWASP güvenlik kuralları'],
    outputs: ['Birim test raporu', 'Linter/Tip denetimi', 'Güvenlik tarama özeti']
  },
  {
    id: 'step-5',
    key: 'review',
    stepNumber: 5,
    name: 'Review',
    shortDesc: 'Salt okunur kod incelemesi ve kalite kontrolü.',
    detailedDesc: 'Reviewer Agent, oluşturulan dosyaların AST sözdizimini, mimari uyumunu, hata yönetimini ve test bulgularını inceleyerek onay veya değişiklik kararı üretir.',
    status: 'pending',
    duration: '—',
    assignedAgent: 'Reviewer Agent',
    agentRole: 'Kod İnceleme & Kalite',
    artifacts: [],
    progress: 0,
    inputs: ['İzole workspace dosyaları', 'Tester sonuç raporu', 'AST sözdizim ağacı'],
    outputs: ['İnceleme bulguları', 'Nihai karar (Approved / Changes Requested / Blocked)']
  },
  {
    id: 'step-6',
    key: 'pr',
    stepNumber: 6,
    name: 'PR',
    shortDesc: 'Sonuç raporu hazırlanıyor.',
    detailedDesc: 'Tüm aşamaların çıktıları birleştirilerek açıklayıcı Pull Request özeti, değişiklik günlüğü (Changelog) ve metrikler hazırlanacak.',
    status: 'pending',
    duration: '—',
    assignedAgent: 'Docs Agent',
    agentRole: 'Dokümantasyon',
    artifacts: [],
    progress: 0,
    inputs: ['Test raporları', 'Reviewer onay raporu', 'Görev referansı'],
    outputs: ['Pull Request taslağı', 'Sürüm notları (Release notes)']
  }
];

export const INITIAL_AGENTS: Agent[] = [
  {
    id: 'agent-architect',
    name: 'Architect Agent (Planner & Scope)',
    role: 'Planlama ve mimari kapsam',
    description: 'Proje gereksinimlerini analiz eder, sistem mimarisini ve dosya kapsamını tasarlar.',
    status: 'idle',
    model: 'Deterministik LangGraph Motoru',
    lastActivity: 'Gereksinim analizi ve dosya kapsamı tespiti',
    lastActivityTime: 'Hazır',
    totalTokens: 'Yerel Motor',
    latencyMs: 120,
    successRate: '100%',
    avatarColor: '#3b82f6',
    accentColor: 'blue',
    capabilities: ['Gereksinim Analizi', 'Sistem Mimarisi', 'Güvenli Dosya Kapsam Tespiti', 'RFC Dokümantasyonu'],
    systemPromptSummary: 'Sen sistem mimarisi ve kapsam uzmanısın. Kod tabanını güvenle analiz ederek modüler planlar üretirsin.'
  },
  {
    id: 'agent-coder',
    name: 'Coder Agent',
    role: 'Kod üretimi',
    description: 'Mimari plana ve dosya kapsamına uygun olarak temiz ve tip güvenli kod üretir.',
    status: 'idle',
    model: 'Deterministik Şablon Motoru',
    lastActivity: 'İzole workspace kod üretimi',
    lastActivityTime: 'Hazır',
    totalTokens: 'Yerel Motor',
    latencyMs: 150,
    successRate: '100%',
    avatarColor: '#10b981',
    accentColor: 'emerald',
    capabilities: ['FastAPI REST API', 'Pydantic Modelleri', 'CRUD Endpointleri', 'İzole Workspace'],
    systemPromptSummary: 'Sen tip güvenli ve modüler kod üreten Coder Agent\'sın. Yalnızca izole çalışma alanına yazarsın.'
  },
  {
    id: 'agent-tester',
    name: 'Tester Agent',
    role: 'Test & İzolasyon Güvenliği',
    description: 'İzole çalışma alanında gerçek testleri çalıştırır ve AST güvenlik kontrollerini yürütür.',
    status: 'idle',
    model: 'İzole Test Koşum Motoru',
    lastActivity: 'Birim testleri ve AST güvenlik denetimi',
    lastActivityTime: 'Hazır',
    totalTokens: 'Yerel Test',
    latencyMs: 350,
    successRate: '100%',
    avatarColor: '#f59e0b',
    accentColor: 'amber',
    capabilities: ['İzole Unittest', 'AST Güvenlik Taraması', 'Ağ/Sistem Çağrısı Engelleme', 'Süreç Ağacı Yönetimi'],
    systemPromptSummary: 'Sen test ve izolasyon güvenliği uzmanısın. Yalnızca izole workspace içinde test koşarsın.'
  },
  {
    id: 'agent-reviewer',
    name: 'Reviewer Agent',
    role: 'Kod İnceleme & Kalite',
    description: 'Üretilen kodları ve test sonuçlarını salt okunur olarak inceler, bulgular ve onay kararı üretir.',
    status: 'idle',
    model: 'Deterministik AST Kod İnceleme',
    lastActivity: 'Salt okunur kod denetimi ve bulgu analizi',
    lastActivityTime: 'Hazır',
    totalTokens: 'Yerel Analiz',
    latencyMs: 80,
    successRate: '100%',
    avatarColor: '#8b5cf6',
    accentColor: 'purple',
    capabilities: ['AST Sözdizimi Denetimi', 'Hata Yönetimi Analizi', 'Tip Güvenliği Kontrolü', 'Test Sonucu Doğrulama'],
    systemPromptSummary: 'Sen kıdemli kod inceleme uzmanısın. Salt okunur inceleme ile somut bulgular ve kararlar üretirsin.'
  },
  {
    id: 'agent-docs',
    name: 'Docs & PR Agent',
    role: 'Dokümantasyon & PR',
    description: 'Tüm aşamaları birleştirerek Pull Request taslağı ve sürüm notları oluşturur.',
    status: 'standby',
    model: 'Gelecek Aşama (Entegre Edilecek)',
    lastActivity: 'Reviewer onayını bekliyor',
    lastActivityTime: 'Beklemede',
    totalTokens: '—',
    latencyMs: 0,
    successRate: '—',
    avatarColor: '#60a5fa',
    accentColor: 'cyan',
    capabilities: ['Pull Request Hazırlama', 'Changelog Üretimi', 'Sürüm Notları'],
    systemPromptSummary: 'Sen teknik dokümantasyon ve PR uzmanısın.'
  }
];

export const INITIAL_LOGS: LogEntry[] = [
  {
    id: 'log-1',
    timestamp: '11:04:02',
    level: 'system',
    source: 'SYSTEM',
    message: 'Pipeline initialized with orchestration profile "full-cycle-dev" (Demo Mode Enabled)'
  },
  {
    id: 'log-2',
    timestamp: '11:04:03',
    level: 'info',
    source: 'ORCHESTRATOR',
    message: 'Active Task: #TASK-104 - "Refactor API error handling & auth middleware"'
  },
  {
    id: 'log-3',
    timestamp: '11:04:05',
    level: 'agent',
    source: 'ARCHITECT',
    message: 'Plan step started: Analyzing specifications and system architecture...',
    stepKey: 'plan'
  },
  {
    id: 'log-4',
    timestamp: '11:04:14',
    level: 'agent',
    source: 'ARCHITECT',
    message: 'Generated architecture blueprint -> artifacts/spec_rfc_084.md (4.8 KB)',
    stepKey: 'plan'
  },
  {
    id: 'log-5',
    timestamp: '11:04:19',
    level: 'success',
    source: 'PIPELINE',
    message: 'Step 1 [Plan] successfully completed in 14.2s. Transitioning to Step 2 [Scope].',
    stepKey: 'plan'
  },
  {
    id: 'log-6',
    timestamp: '11:04:20',
    level: 'agent',
    source: 'ARCHITECT',
    message: 'Scope step started: Scanning codebase dependency graph for affected files...',
    stepKey: 'scope'
  },
  {
    id: 'log-7',
    timestamp: '11:04:27',
    level: 'agent',
    source: 'ARCHITECT',
    message: 'Resolved 4 affected files: src/auth.ts, src/middleware.ts, tests/auth.test.ts, docs/api.md',
    stepKey: 'scope'
  },
  {
    id: 'log-8',
    timestamp: '11:04:29',
    level: 'success',
    source: 'PIPELINE',
    message: 'Step 2 [Scope] completed in 8.7s. Handing off context to Coder Agent.',
    stepKey: 'scope'
  },
  {
    id: 'log-9',
    timestamp: '11:04:30',
    level: 'agent',
    source: 'CODER',
    message: 'Edit step started: Coder Agent (Gemini 3.7 Flash Thinking) initialized.',
    stepKey: 'edit'
  },
  {
    id: 'log-10',
    timestamp: '11:04:36',
    level: 'agent',
    source: 'CODER',
    message: 'Writing type-safe error boundaries and JWT token validation logic...',
    stepKey: 'edit'
  },
  {
    id: 'log-11',
    timestamp: '11:04:52',
    level: 'agent',
    source: 'CODER',
    message: 'Created module src/middleware/auth_middleware.ts (3.4 KB, +124 lines)',
    stepKey: 'edit'
  },
  {
    id: 'log-12',
    timestamp: '11:05:01',
    level: 'info',
    source: 'SYSTEM',
    message: 'Demo mode active: All pipeline streams and agent telemetry are simulated client-side.'
  }
];

export const INITIAL_TASKS: TaskItem[] = [
  {
    id: 'TASK-104',
    title: 'Refactor API error handling & auth middleware',
    description: 'Tüm REST endpointlerinde standart hata yanıt formatı ve JWT doğrulama ara katmanı entegrasyonu.',
    priority: 'high',
    status: 'in_progress',
    createdAt: 'Bugün, 11:04',
    branch: 'feat/auth-error-handling',
    assignedAgents: ['Architect Agent', 'Coder Agent', 'Test Agent'],
    currentStep: 'edit'
  },
  {
    id: 'TASK-103',
    title: 'Implement dark mode theme persistence and CSS tokens',
    description: 'Kullanıcı tema tercihini localStorage üzerinde saklayıp sistem temasını otomatik algılama.',
    priority: 'medium',
    status: 'completed',
    createdAt: 'Dün, 16:30',
    branch: 'feat/theme-system',
    assignedAgents: ['Coder Agent', 'Test Agent', 'Docs Agent'],
    currentStep: 'pr'
  },
  {
    id: 'TASK-102',
    title: 'Add rate-limiting middleware to external API endpoints',
    description: 'DDoS koruması ve IP bazlı kayan pencere (sliding window) algoritması ile istek sınırlama.',
    priority: 'critical',
    status: 'completed',
    createdAt: '2 gün önce',
    branch: 'fix/rate-limiter',
    assignedAgents: ['Architect Agent', 'Coder Agent', 'Security Agent'],
    currentStep: 'pr'
  },
  {
    id: 'TASK-101',
    title: 'Optimize bundle size with tree-shaking & code splitting',
    description: 'Gereksiz paket importlarını ayıklayarak başlangıç yükleme süresini %40 düşürme.',
    priority: 'low',
    status: 'completed',
    createdAt: '3 gün önce',
    branch: 'perf/tree-shaking',
    assignedAgents: ['Coder Agent', 'Test Agent'],
    currentStep: 'pr'
  }
];

export const SYSTEM_STATS: SystemStats = {
  activeRuns: 1,
  completedTasks: 38,
  avgPipelineTime: '1m 18s',
  agentUptime: '99.98%',
  totalTokensProcessed: '1.42M'
};

export const MOCK_PROJECT_FILES = [
  { name: 'src/types/index.ts', size: '3.2 KB', type: 'ts', modified: '2 dk önce', status: 'modified' },
  { name: 'src/components/Pipeline/Timeline.tsx', size: '5.8 KB', type: 'tsx', modified: '1 dk önce', status: 'added' },
  { name: 'src/components/Agents/AgentCards.tsx', size: '6.4 KB', type: 'tsx', modified: 'Az önce', status: 'added' },
  { name: 'src/components/Terminal/OutputLogs.tsx', size: '4.2 KB', type: 'tsx', modified: 'Az önce', status: 'added' },
  { name: 'src/components/Modals/NewTaskModal.tsx', size: '3.9 KB', type: 'tsx', modified: 'Az önce', status: 'added' },
  { name: 'src/components/Sidebar.tsx', size: '3.5 KB', type: 'tsx', modified: 'Az önce', status: 'added' },
  { name: 'src/components/TopBar.tsx', size: '3.1 KB', type: 'tsx', modified: 'Az önce', status: 'added' },
  { name: 'package.json', size: '0.6 KB', type: 'json', modified: '5 dk önce', status: 'modified' },
  { name: 'tsconfig.json', size: '0.2 KB', type: 'json', modified: '1 saat önce', status: 'unchanged' }
];
