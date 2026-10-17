from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PLANNING = "planning"
    PLANNED = "planned"
    SCOPING = "scoping"
    SCOPED = "scoped"
    CODING = "coding"
    CODED = "coded"
    TESTING = "testing"
    TESTED = "tested"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"
    CHANGES_REQUESTED = "changes_requested"
    AWAITING_APPROVAL = "awaiting_approval"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DELIVERY_FAILED = "delivery_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskApprovalRequest(BaseModel):
    """İnsan onayı talebi için model."""
    comment: Optional[str] = Field(None, description="Onay açıklaması veya notu")
    approved_by: Optional[str] = Field(default="reviewer_human", description="Onaylayan kullanıcı/rol")


class TaskRejectRequest(BaseModel):
    """İnsan reddi talebi için model."""
    reason: str = Field(..., min_length=1, description="Red gerekçesi")
    rejected_by: Optional[str] = Field(default="reviewer_human", description="Reddeden kullanıcı/rol")


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ReviewerVerdict(str, Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"


class CriterionStatus(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNCERTAIN = "uncertain"


class CriterionEvaluation(BaseModel):
    """
    Kabul kriteri veya işlevsel gereksinimin semantik doğrulama değerlendirmesi.
    """
    criterion: str = Field(..., description="Kabul kriteri veya iş gereksinimi metni")
    status: CriterionStatus = Field(..., description="Karşılanma durumu ('met', 'not_met', 'uncertain')")
    evidence: str = Field(..., description="Kriterin neden bu durumda olduğunu açıklayan somut kod veya test kanıtı")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Semantik doğrulama güven skoru (0.0 - 1.0)")


class ReviewFinding(BaseModel):
    """
    Reviewer Agent tarafından tespit edilen tekil bir inceleme bulgusu.
    """
    id: str = Field(..., description="Benzersiz bulgu ID'si (Örn: finding_1)")
    severity: FindingSeverity = Field(..., description="Bulgu önem derecesi (critical, high, medium, low, info)")
    category: str = Field(..., description="Bulgu kategorisi (Örn: syntax, security, code_quality, testing, architecture, semantic_alignment)")
    title: str = Field(..., description="Kısa bulgu başlığı")
    description: str = Field(..., description="Ayrıntılı bulgu açıklaması")
    file_path: Optional[str] = Field(None, description="Bulgunun ait olduğu dosya yolu (varsa)")
    recommendation: str = Field(..., description="Sorunun giderilmesi için somut öneri")
    evidence: str = Field(..., description="Bulguyu destekleyen somut kod satırı veya test kanıtı")


class ReviewerResult(BaseModel):
    """
    Reviewer Agent tarafından gerçekleştirilen salt okunur kod inceleme sonucu.
    """
    status: str = Field(..., description="İnceleme durumu ('reviewed', 'failed', 'blocked')")
    verdict: ReviewerVerdict = Field(..., description="Nihai inceleme kararı ('approved', 'changes_requested', 'blocked')")
    findings: List[ReviewFinding] = Field(default_factory=list, description="Tespit edilen inceleme bulguları")
    semantic_evaluations: List[CriterionEvaluation] = Field(default_factory=list, description="Kabul kriterleri ve iş mantığı semantik doğrulama sonuçları")
    summary: str = Field(..., description="İnceleme özeti ve gerekçesi")
    reviewed_files: List[str] = Field(default_factory=list, description="İncelenen dosya listesi")
    error: Optional[str] = Field(None, description="İnceleme sırasında oluşan hata mesajı (varsa)")


class HealthResponse(BaseModel):
    status: str = Field(default="ok", description="Servis sağlık durumu")
    message: str = Field(default="Service is healthy and running", description="Durum mesajı")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Sunucu zaman damgası (UTC)"
    )


class TaskCreateRequest(BaseModel):
    description: str = Field(
        ...,
        min_length=1,
        description="Görev açıklaması. Boş bırakılamaz."
    )
    planner_mode: Optional[str] = Field(
        default=None,
        description="Planner çalışma modu ('deterministic', 'llm', 'auto'). Boş bırakılırsa DEFAULT_PLANNER_MODE kullanılır."
    )
    coder_mode: Optional[str] = Field(
        default=None,
        description="Coder çalışma modu ('deterministic', 'llm'). Boş bırakılırsa DEFAULT_CODER_MODE kullanılır."
    )
    require_human_approval: Optional[bool] = Field(
        default=None,
        description="Reviewer approved sonrası insan onayı beklenip beklenmeyeceği. Boş veya false ise mevcut otomatik reviewed sonlanması korunur."
    )

    @field_validator("description")
    @classmethod
    def validate_description_not_whitespace(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Açıklama alanı boş veya yalnızca boşluklardan oluşamaz.")
        return trimmed


class TaskPlan(BaseModel):
    """
    Planner Agent tarafından üretilen yapısal plan modeli.
    Deterministik kural tabanlı analiz çıktısıdır (LLM gerektirmez).
    """
    goal: str = Field(..., description="Görevin ana hedefi ve kapsam özeti")
    subtasks: List[str] = Field(..., description="Uygulanacak alt adımlar ve görevler")
    acceptance_criteria: List[str] = Field(..., description="Kabul kriterleri ve başarı şartları")
    risks: List[str] = Field(default_factory=list, description="Potansiyel teknik riskler ve dikkat edilecek hususlar")


class TaskScope(BaseModel):
    """
    Scope Agent tarafından üretilen dosya kapsamı ve etki analiz modeli.
    Deterministik ve güvenli dosya sistemi analizi çıktısıdır.
    """
    summary: str = Field(..., description="Kapsam ve dosya etki analiz özeti")
    existing_files: List[str] = Field(default_factory=list, description="Görevle ilişkili mevcut kaynak dosyalar")
    proposed_new_files: List[str] = Field(default_factory=list, description="Oluşturulması önerilen yeni dosyalar")
    out_of_scope: List[str] = Field(default_factory=list, description="Kapsam dışı bırakılan veya dokunulmayacak dosyalar")
    risks: List[str] = Field(default_factory=list, description="Kapsam ve dosya etkileşimiyle ilgili teknik riskler")


class CoderResult(BaseModel):
    """
    Coder Agent tarafından izole çalışma alanında (backend/workspaces/{task_id}/)
    üretilen kod dosyalarının ve durumunun sonuç modeli.
    """
    status: str = Field(..., description="Kod üretim durumu (coded, unsupported, failed)")
    created_files: List[str] = Field(default_factory=list, description="İzole çalışma alanında oluşturulan dosyaların yolları")
    summary: str = Field(..., description="Kod üretim özeti ve mimari açıklaması")
    limitations: List[str] = Field(default_factory=list, description="Desteklenen kapsam kısıtları veya nedenler")
    error: Optional[str] = Field(None, description="Varsa kod üretim hata detayı")


class LLMGeneratedFile(BaseModel):
    """
    LLM Coder tarafından üretilen tekil kaynak kod dosyası.
    """
    filename: str = Field(..., description="Dosya adı (örn: email_filter.py, main.py, README.md)")
    content: str = Field(..., description="Dosya içeriği (Python kaynak kodu veya Markdown)")


class LLMCoderResponse(BaseModel):
    """
    LLM Coder tarafından üretilen yapısal yanıt modeli.
    """
    summary: str = Field(..., description="Üretilen kodun mimari ve işlevsel özeti")
    files: List[LLMGeneratedFile] = Field(..., description="Üretilen kaynak kod dosyaları listesi")


class TestCaseResult(BaseModel):
    """
    Tekil bir test senaryosunun yürütme sonucu.
    """
    name: str = Field(..., description="Test senaryosunun adı")
    status: str = Field(..., description="Test sonucu ('passed' veya 'failed')")
    duration_ms: float = Field(default=0.0, description="Testin çalışma süresi (milisaniye)")
    error: Optional[str] = Field(None, description="Varsa test başarısızlık detayı veya assertion hatası")


class TesterResult(BaseModel):
    """
    Tester Agent tarafından izole çalışma alanında (backend/workspaces/{task_id}/)
    koşulan gerçek testlerin sonuç modeli.
    """
    status: str = Field(..., description="Test süreci durumu ('tested', 'failed', 'blocked', 'unsupported')")
    passed: int = Field(default=0, description="Başarılı geçen test sayısı")
    failed: int = Field(default=0, description="Başarısız olan test sayısı")
    test_results: List[TestCaseResult] = Field(default_factory=list, description="Koşulan her bir test senaryosunun ayrıntılı sonucu")
    summary: str = Field(..., description="Test koşumu özeti ve izolasyon raporu")
    isolation_type: Optional[str] = Field(None, description="Kullanılan izolasyon motoru türü ('docker', 'mock', 'none', 'subprocess_unsafe')")
    error: Optional[str] = Field(None, description="Test sürecinde oluşan genel hata veya izolasyon bloklama nedeni")


class TaskEvent(BaseModel):
    """
    İş akışı sırasında gerçekleşen izlenebilir olay kaydı.
    """
    id: str = Field(..., description="Benzersiz olay ID'si")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Olayın gerçekleştiği zaman damgası (UTC)"
    )
    source: str = Field(..., description="Olayı üreten bileşen/agent (Örn: ORCHESTRATOR, PLANNER_AGENT, SCOPE_AGENT, CODER_AGENT, TESTER_AGENT, REVIEWER_AGENT)")
    type: str = Field(..., description="Olay tipi (Örn: task_started, planning_started, plan_created, scope_started, scope_completed, coder_started, coder_completed, coder_unsupported, coder_failed, tester_started, tester_completed, tester_failed, tester_blocked, reviewer_started, reviewer_completed, reviewer_failed, reviewer_blocked, task_failed)")
    message: str = Field(..., description="Olay açıklaması")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Ek meta veri veya detaylar")


class TaskResponse(BaseModel):
    id: str = Field(..., description="Benzersiz görev kimliği")
    description: str = Field(..., description="Görev açıklaması")
    status: TaskStatus = Field(default=TaskStatus.QUEUED, description="Görevin güncel durumu")
    plan: Optional[TaskPlan] = Field(None, description="Planner Agent tarafından üretilen plan")
    scope: Optional[TaskScope] = Field(None, description="Scope Agent tarafından üretilen dosya kapsamı")
    coder: Optional[CoderResult] = Field(None, description="Coder Agent tarafından üretilen kodlama çıktısı")
    tester: Optional[TesterResult] = Field(None, description="Tester Agent tarafından üretilen test koşum çıktısı")
    reviewer: Optional[ReviewerResult] = Field(None, description="Reviewer Agent tarafından üretilen kod inceleme çıktısı")
    events: List[TaskEvent] = Field(default_factory=list, description="Görevin olay günlüğü")
    retry_count: int = Field(default=0, description="Tamamlanan Coder düzeltme denemesi. İlk üretim sayılmaz.")
    retry_history: List[Dict[str, Any]] = Field(default_factory=list, description="Her düzeltme denemesinin coder, tester ve reviewer kaydı")
    error: Optional[str] = Field(None, description="Varsa hata mesajı")
    created_at: datetime = Field(..., description="Görevin oluşturulma zamanı (UTC)")
    updated_at: Optional[datetime] = Field(None, description="Görevin son güncellenme zamanı (UTC)")


class AgentMetric(BaseModel):
    """
    Her bir agent'ın tekil bir workflow çalıştırmasındaki performans ve durum metriği.
    """
    agent_name: str = Field(..., description="Agent adı (PLANNER, SCOPE, CODER, TESTER, REVIEWER)")
    status: str = Field(..., description="Agent çalışma sonucu ('completed', 'failed', 'blocked', 'unsupported', 'skipped')")
    started_at: Optional[datetime] = Field(None, description="Agent başlangıç zamanı (UTC)")
    completed_at: Optional[datetime] = Field(None, description="Agent bitiş zamanı (UTC)")
    duration_ms: Optional[float] = Field(None, description="Çalışma süresi (milisaniye)")
    error: Optional[str] = Field(None, description="Varsa hata mesajı")
    mode: Optional[str] = Field(None, description="Çalışma modu ('deterministic', 'llm', 'fallback')")
    provider: Optional[str] = Field(None, description="Kullanılan LLM sağlayıcısı (örn: openai, mock)")
    model: Optional[str] = Field(None, description="Kullanılan LLM modeli (örn: gpt-4o-mini)")


class LLMProviderInfo(BaseModel):
    """Sistemde aktif olan LLM sağlayıcı yapılandırması (Gizli anahtarlar ASLA yer almaz)."""
    provider: str = Field(..., description="Sağlayıcı adı")
    model: str = Field(..., description="Varsayılan model")
    base_host: str = Field(..., description="API ana sunucusu")
    is_configured: bool = Field(..., description="API anahtarının tanımlı olup olmadığı")
    fallback_enabled: bool = Field(..., description="Hata durumunda deterministik motora düşme ayarı")
    default_planner_mode: str = Field(default="deterministic", description="Varsayılan Planner modu")
    default_coder_mode: str = Field(default="deterministic", description="Varsayılan Coder modu")


class WorkflowRun(BaseModel):
    """
    Bir görevin belirli bir tarihte gerçekleştirilen izole iş akışı çalıştırma kaydı.
    """
    id: str = Field(..., description="Benzersiz çalıştırma ID'si (Örn: run_a1b2c3d4)")
    task_id: str = Field(..., description="İlişkili görev ID'si")
    run_number: int = Field(default=1, description="Görevin kaçıncı çalıştırması olduğu")
    status: TaskStatus = Field(..., description="Çalıştırmanın nihai durumu")
    started_at: datetime = Field(..., description="Çalıştırma başlangıç zamanı (UTC)")
    completed_at: Optional[datetime] = Field(None, description="Çalıştırma tamamlanma zamanı (UTC)")
    duration_ms: Optional[float] = Field(None, description="Toplam çalışma süresi (ms)")
    error: Optional[str] = Field(None, description="Varsa hata açıklaması")
    plan: Optional[TaskPlan] = Field(None, description="Bu çalıştırmadaki Planner planı")
    scope: Optional[TaskScope] = Field(None, description="Bu çalıştırmadaki Scope çıktısı")
    coder: Optional[CoderResult] = Field(None, description="Bu çalıştırmadaki Coder çıktısı")
    tester: Optional[TesterResult] = Field(None, description="Bu çalıştırmadaki Tester çıktısı")
    reviewer: Optional[ReviewerResult] = Field(None, description="Bu çalıştırmadaki Reviewer çıktısı")
    events: List[TaskEvent] = Field(default_factory=list, description="Bu çalıştırmadaki olaylar")
    retry_count: int = Field(default=0, description="Tamamlanan Coder düzeltme denemesi. İlk üretim sayılmaz.")
    retry_history: List[Dict[str, Any]] = Field(default_factory=list, description="Her düzeltme denemesinin coder, tester ve reviewer kaydı")
    agent_metrics: List[AgentMetric] = Field(default_factory=list, description="Agent bazlı çalışma süreleri ve durumları")


class WorkflowRunListResponse(BaseModel):
    task_id: str = Field(..., description="Görev ID'si")
    total_runs: int = Field(..., description="Toplam çalıştırma sayısı")
    runs: List[WorkflowRun] = Field(default_factory=list, description="Geçmiş çalıştırmalar listesi")
