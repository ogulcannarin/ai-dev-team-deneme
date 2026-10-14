# AI Dev Team - Backend API & LangGraph Agent Workflow

Bu servis, AI Dev Team platformu için FastAPI ve **LangGraph** kullanılarak geliştirilmiş RESTful API ve multi-agent iş akışı katmanıdır.

## Özellikler

- **FastAPI & Pydantic**: Tip güvenli şemalar ve otomatik Swagger/OpenAPI dokümantasyonu.
- **Esnek ve Güvenli LLM Provider Katmanı**:
  - OpenAI ve OpenAI uyumlu tüm sağlayıcıları (Azure OpenAI, Groq, Ollama, LocalAI, vLLM vb.) destekleyen genişletilebilir arayüz (`BaseLLMProvider`, `OpenAICompatibleProvider`, `MockLLMProvider`).
  - **Sıfır Sızıntı Garantisi (Zero Leakage Guarantee)**: API anahtarları asla frontend'e gönderilmez, veritabanına (`tasks`, `workflow_runs`) yazılmaz ve loglara düşmez.
  - **Kontrollü Timeout & Hata Yönetimi**: 15.0s varsayılan zaman aşımı (`LLM_TIMEOUT`), maksimum 2 kontrollü deneme (`LLM_MAX_RETRIES`), 401/429/500 HTTP hata sınıflandırması ve sonsuz döngü / kontrolsüz maliyet engelleme.
  - **Güvenilmeyen Girdi Doğrulaması**: LLM yanıtları güvenilmeyen veri kabul edilir; `TaskPlan` Pydantic şeması ile sıkı tip ve içerik denetiminden geçirilir.
  - **Prompt Injection Koruması**: Kullanıcı girdi metinleri sistem talimatlarını ezemeyecek şekilde sınırlandırılır.
  - **Otomatik ve Güvenli Fallback**: API anahtarı tanımlı değilse veya model çağrısı başarısız olursa sistem deterministik Planner motoruna geçerek süreci kesintisiz ve izlenebilir tamamlar (`planner_fallback` olayı).
- **Deterministik & LLM Destekli Planner Agent**:
  - `deterministic` modu: %100 yerel ve kural tabanlı plan üretimi (`goal`, `subtasks`, `acceptance_criteria`, `risks`).
  - `llm` modu: Seçilen LLM modeli üzerinden yapısal plan oluşturma ve Pydantic ile doğrulama.
  - Çalışma modu, kullanılan sağlayıcı ve model bilgisi (API anahtarı hariç) workflow geçmişinde ve agent metriklerinde izlenebilir.
- **Güvenli Scope Agent**: Proje kök dizinini güvenle tarayan, path traversal koruması bulunan ve hassas dosyaları (`.env`, `.git`, `.venv`, `workspaces`, `node_modules`) dışlayarak dosya kapsamını (`summary`, `existing_files`, `proposed_new_files`, `out_of_scope`, `risks`) çıkaran analiz motoru.
- **İzole Coder Agent**:
  - Üretilen kodları ana uygulamanın kaynak dizinlerine ASLA doğrudan yazmaz; her görev için ayrı `backend/workspaces/{task_id}/` izole dizini oluşturur.
  - Task ID doğrulaması (`^[a-zA-Z0-9_-]{1,64}$`) ve path traversal koruması ile kök dizin dışına çıkışı kesinlikle engeller.
  - Sadece beyaz listedeki izin verilen dosya adlarına yazar (`ALLOWED_CODER_FILENAMES`: `main.py`, `api_feature.py`, `models.py`, `middleware.py`, `rate_limiter.py`, `auth.py`, `schemas.py`, `test_feature.py`, `README.md`).
  - Var olan dosyaları sessizce ezmez; dosya çakışması durumunda işlemi güvenli biçimde durdurur.
  - İlk sürümde güvenli Python REST API / FastAPI / Pydantic CRUD ve middleware şablonlarını destekler.
  - Şablon dışındaki istekler için sahte kod üretmez, `unsupported` durumu ile nedenlerini raporlar.
  - Deterministik kural tabanlı motorla çalışır, dış LLM API anahtarı istemez.
- **Gerçek & Güvenlik Denetimli Tester Agent**:
  - Tipli `TesterResult` (`status`, `passed`, `failed`, `test_results`, `summary`, `error`) ve `TestCaseResult` modelleriyle çalışır.
  - Testleri **YALNIZCA** görev için oluşturulan izole çalışma alanında (`backend/workspaces/{task_id}/`) çalıştırır.
  - **Statik AST Güvenlik Taraması**: Python Abstract Syntax Tree (AST) ayrıştırması ile test öncesi tüm dosyalarda `socket`, `requests`, `urllib`, `subprocess`, `ctypes`, `os.system`, `eval`, `exec`, `open('../...')` gibi yetkisiz ağ, sistem çağrısı ve dosya kaçış girişimlerini çalıştırılmadan tespit eder ve engeller (`status: "blocked"`).
  - **Sembolik Bağlantı ve Dizin Bütünlüğü**: Symlink/junction oluşturma girişimleri, yetkisiz alt dizinler, 500 KB dosya boyutu sınırı, 15 dosya ve 1 MB toplam çalışma alanı limiti denetlenir.
  - **Süreç Ağacı Yönetimi ve Zaman Aşımı**: 5.0 saniye katı zaman aşımı devrededir; zaman aşımı durumunda ana ve tüm alt/çocuk süreçler (`taskkill /F /T /PID` veya `os.killpg`) zorla sonlandırılır.
  - **Ortam Değişkeni İzolasyonu**: Ana uygulamanın `.env`, veritabanı veya gizli API anahtarları alt sürece asla aktarılmaz.
  - Güvenli izolasyon şartları sağlanamazsa kod çalıştırılmaz; `status: "blocked"` kaydedilir.
  - Coder aşaması `coded` ile sonuçlanmadığında (ör. `unsupported` veya `failed`), Tester ve Reviewer adımları atlanır.
- **Salt Okunur (Read-Only) Reviewer Agent**:
  - Tipli `ReviewerResult` (`status`, `verdict`, `findings`, `summary`, `reviewed_files`, `error`) ve `ReviewFinding` modelleriyle çalışır.
  - **Deterministik & Kural Tabanlı**: LLM API anahtarı gerektirmez; dosya bütünlüğü, AST sözdizimi, hata yönetimi, tip güvenliği ve dokümantasyon kontrollerini kural tabanlı yürütür.
  - **Kesinlikle Salt Okunur**: Dosyaları değiştirmez, kod çalıştırmaz, komut yürütmez ve ağ çağrısı yapmaz.
  - **Karar Mantığı (Verdict Logic)**:
    - `approved`: Kritik/yüksek önem dereceli bulgu yoksa ve Tester Agent testleri başarıyla geçmişse (`passed > 0`, `failed == 0`).
    - `changes_requested`: Kodda düzeltilmesi gereken sorunlar (sözdizimi hataları, bare `except:`, eksik dosyalar) veya başarısız testler varsa.
    - `blocked`: Path traversal, geçersiz task_id, sembolik bağlantı veya Tester Agent güvenlik blokajı tespit edilmişse.
    - `failed`: İnceleme motorunda beklenmeyen bir sistem hatası oluşmuşsa.
  - **PR Aşamasından Bağımsızlık**: Reviewer ve PR oluşturma adımları ayrıdır; PR aşaması güvenle `pending` durumunda bekletilir.
- **SQLite Kalıcı Veri Katmanı**:
  - Geliştirme ortamında veriler `backend/ai_dev_team.db` SQLite veritabanında kalıcı olarak saklanır.
  - Veritabanı bağlantısı (`database.py`), Pydantic şemaları (`schemas.py`) ve veri erişim katmanı (`repository.py`) birbirinden modüler olarak ayrılmıştır.
  - `PRAGMA foreign_keys = ON;`, `PRAGMA journal_mode = WAL;`, `PRAGMA busy_timeout = 5000;` ayarlarıyla yüksek performans, veri bütünlüğü ve eşzamanlı kilitlenme koruması sağlanır.
  - Uygulama veya sunucu yeniden başlatıldığında görevler, agent sonuçları ve çalıştırma geçmişi kaybolmaz.
- **İzlenebilir Workflow Çalıştırma Geçmişi (Workflow Runs)**:
  - Her workflow tetiklemesi için `workflow_runs` tablosuna benzersiz `id`, `task_id`, `run_number` (1, 2, 3...), başlangıç, bitiş, `duration_ms`, nihai durum, hata ve `agent_metrics` (PLANNER, SCOPE, CODER, TESTER, REVIEWER süreleri ve durumları) kaydedilir.
  - Aynı görevin tekrar çalıştırılması durumunda önceki sonuçlar ezilmez; yeni bir run kaydı oluşturulur.
  - Eşzamanlı çalıştırmaları önlemek için görev bazlı `asyncio.Lock` mekanizması kullanılır.
  - `.gitignore` dosyası SQLite dosyalarını (`*.db`, `*.sqlite*`, `ai_dev_team.db`) otomatik dışlar.
- **CORS Desteği**: `http://localhost:5173`, `http://localhost:3000` ve Vite preview portlarına tam uyumlu.
- **Kapsamlı Testler**: Pytest ile uçtan uca doğrulanmış güvenlik, AST tarama, ağ engelleme, path traversal, symlink engelleme, dosya dışlama, çakışma önleme, Coder, Tester izolasyonu, Reviewer karar mantığı, SQLite kalıcılık, restart simülasyonu, LLM Provider, JSON parsing, prompt injection koruması, fallback mekanizmaları, sıfır API anahtarı sızıntısı ve API testleri (59 test, %100 başarı).

---

## LLM Sağlayıcı Yapılandırması (Environment Variables)

Projeyi gerçek bir LLM sağlayıcısı (OpenAI, Azure, Groq, Ollama vb.) ile çalıştırmak için backend dizininde bir `.env` dosyası oluşturabilirsiniz:

```ini
# LLM Sağlayıcı Türü (openai, openai_compatible, mock, groq, ollama)
LLM_PROVIDER=openai

# API Anahtarı (Gizlidir, gitignore ile korunur)
OPENAI_API_KEY=your-actual-api-key-here

# API Kök Adresi (Yerel modeller veya uyumlu servisler için değiştirilebilir)
OPENAI_BASE_URL=https://api.openai.com/v1

# Kullanılacak Model
LLM_MODEL=gpt-4o-mini

# Örnekleme Parametreleri
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048
LLM_TIMEOUT=15.0
LLM_MAX_RETRIES=2

# Anahtar yoksa veya hata durumunda deterministik motora geçiş
LLM_FALLBACK_TO_DETERMINISTIC=true

# Varsayılan Planner Çalışma Modu (deterministic veya llm)
DEFAULT_PLANNER_MODE=deterministic
```

> **Güvenlik Notu**: `.env` dosyaları `.gitignore` ile korunmaktadır. API anahtarı frontend'e, loglara veya SQLite veritabanına asla yazılmaz. API anahtarı yapılandırılmadığında sistem sessizce hata vermek yerine güvenli fallback modunda deterministik plan üretir.

---

## GitHub Pull Request Teslimatı

Yerel teslimat `backend/workspaces/.delivery/{task_id}.git` altında `task/{task_id}` dalına commit yazar. Bu davranış GitHub ayarı olmasa da aynı kalır.

GitHub entegrasyonu isteğe bağlıdır. `GITHUB_TOKEN` ile birlikte `GITHUB_OWNER` ve `GITHUB_REPO` ya da `GITHUB_REPOSITORY=owner/repo` tanımlıysa, yerel commit başarılı olduktan sonra nesneler `git push --no-force` ile yalnızca `refs/heads/task/{task_id}` hedefine aktarılır. Böylece GitHub’daki commit SHA’sı yerel SHA ile aynı kalır. Uzak dal zaten bu SHA’daysa push yapılmaz. Hızlı ileri alınamayan uzak commit’te force push yapılmaz. Branch sorgusu ve pull request oluşturma GitHub REST API ile yapılır. `GITHUB_BASE_BRANCH` (varsayılan `main`) yalnızca pull request hedefidir. `main` dalına push veya merge yapılmaz. Aynı SHA ve aynı açık pull request tekrar oluşturulmaz. Token remote URL’sine ve Git argümanlarına yazılmaz; yalnızca bu sürecin HTTP başlığı ortam değişkeninde tutulur.

Kimlik bilgisi yoksa veya geçersizse yalnızca yerel teslimat çalışır. Kimlik bilgisi varken GitHub kimlik doğrulaması, ağ veya API hatası `delivery_failed` olur; yerel commit SHA'sı korunur. Token loglara, Git komutlarına, URL'lere, olaylara ve API yanıtlarına yazılmaz.

Fine-grained personal access token için yalnızca hedef depoya şu izinler yeterlidir:

- **Contents**: Read and write. Görev dalını ve git nesnelerini yazmak için gerekir.
- **Pull requests**: Read and write. Açık pull request'i bulmak ve oluşturmak için gerekir.
- **Metadata**: Read. GitHub bu izni fine-grained token ile birlikte zorunlu tutar.

`Administration`, `Workflows`, depo silme veya klasik `repo` kapsamı gerekmez. Token'ı `.env` içinde tutun ve commit etmeyin.

---

## Kurulum ve Çalıştırma

### 1. Sanal Ortamı (Virtual Environment) Aktifleştirme

PowerShell üzerinde `backend` klasöründeyken:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
```

*(Gerekli bağımlılıkları yüklemek için: `pip install -r requirements.txt`)*

### 2. Geliştirme Sunucusunu Başlatma

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- API Adresi: `http://127.0.0.1:8000`
- Swagger UI (Etkileşimli Dokümantasyon): `http://127.0.0.1:8000/docs`
- ReDoc Dokümantasyonu: `http://127.0.0.1:8000/redoc`

### 3. Testleri Çalıştırma

```powershell
pytest -v
```

---

## API Uç Noktaları (Endpoints)

### 1. `GET /health`
Servisin çalıştığını ve erişilebilir olduğunu doğrular.

---

### 2. `POST /tasks`
Yeni bir görev oluşturur ve `queued` durumunda kaydeder.

**İstek Gövdesi:**
```json
{
  "description": "FastAPI REST API router for user management and items CRUD"
}
```

---

### 3. `POST /tasks/{task_id}/run`
Görevi LangGraph StateGraph iş akışına sokar (`START -> init -> planner -> scope -> coder -> tester -> reviewer -> END`).

**Örnek Başarılı Yanıt (200 OK):**
```json
{
  "id": "task_a1b2c3d4e5",
  "description": "FastAPI REST API router for user management and items CRUD",
  "status": "reviewed",
  "plan": {
    "goal": "Gereksinimleri analiz etmek ve hedeflenen çözümü mimari standartlara uygun geliştirmek...",
    "subtasks": [
      "1. Gereksinim Analizi: İlgili iş mantığı ve mimari bileşen sınırlarının belirlenmesi",
      "2. Şema & Tip Tanımları: Gerekli veri modellerinin (Pydantic / TypeScript) hazırlanması",
      "3. Çekirdek Uygulama: İlgili servis, modül veya endpoint mantığının kodlanması",
      "4. Doğrulama & Test: Birim ve entegrasyon testlerinin yazılarak senaryoların doğrulanması",
      "5. İnceleme & Review: Statik kod incelemesi ve kalite kontrolü",
      "6. Dokümantasyon & PR: Yapılan değişikliklerin belgelenmesi ve inceleme için hazırlanması"
    ],
    "acceptance_criteria": [
      "Görev tanımında belirtilen tüm işlevsel gereksinimlerin eksiksiz karşılanması",
      "Tüm veri modelleri ve API uçlarında tam tip güvenliğinin sağlanması"
    ],
    "risks": [
      "Mevcut API sözleşmelerinde beklenmeyen geriye dönük uyumsuzluklar"
    ]
  },
  "scope": {
    "summary": "Kapsam analizi tamamlandı: 4 mevcut dosya ile etkileşim tespit edildi...",
    "existing_files": ["backend/main.py", "backend/schemas.py", "src/types/index.ts"],
    "proposed_new_files": ["backend/workspaces/task_a1b2c3d4e5/api_feature.py", "backend/workspaces/task_a1b2c3d4e5/models.py"],
    "out_of_scope": [".env (Hassas yapılandırma)", ".git (Versiyon kontrol)", "node_modules (Bağımlılıklar)"],
    "risks": ["Yeni eklenen endpointlerin mevcut rotalarla çakışmaması"]
  },
  "coder": {
    "status": "coded",
    "created_files": [
      "workspaces/task_a1b2c3d4e5/models.py",
      "workspaces/task_a1b2c3d4e5/api_feature.py",
      "workspaces/task_a1b2c3d4e5/README.md"
    ],
    "summary": "Coder Agent izole çalışma alanında (backend/workspaces/task_a1b2c3d4e5/) 3 dosya başarıyla oluşturdu.",
    "limitations": [
      "Bu kod deterministik kural tabanlı motor ile üretilmiştir (LLM çağrısı değildir).",
      "Üretilen kod izole alanda saklanmaktadır; otomatik çalıştırılmaz."
    ],
    "error": null
  },
  "tester": {
    "status": "tested",
    "passed": 4,
    "failed": 0,
    "test_results": [
      {
        "name": "test_01_model_validation_valid",
        "status": "passed",
        "duration_ms": 25.4,
        "error": null
      },
      {
        "name": "test_02_model_validation_invalid_missing_title",
        "status": "passed",
        "duration_ms": 12.8,
        "error": null
      }
    ],
    "summary": "Tester Agent izole çalışma alanında (task_a1b2c3d4e5) 4 birim testini 0 hata ile başarıyla tamamladı (98.5ms). Ağ erişimi kapalı ve kaynak izolasyonu sağlandı.",
    "error": null
  },
  "reviewer": {
    "status": "reviewed",
    "verdict": "approved",
    "findings": [],
    "summary": "Reviewer Agent kod incelemesini başarıyla tamamladı ve onayladı (APPROVED). 3 dosya incelendi, engelleyici hata bulunmadı.",
    "reviewed_files": [
      "workspaces/task_a1b2c3d4e5/README.md",
      "workspaces/task_a1b2c3d4e5/api_feature.py",
      "workspaces/task_a1b2c3d4e5/models.py"
    ],
    "error": null
  },
  "events": [
    {
      "id": "evt_1",
      "timestamp": "2026-10-08T15:30:00Z",
      "source": "ORCHESTRATOR",
      "type": "task_started",
      "message": "Görev orkestrasyon iş akışı başlatıldı."
    },
    {
      "id": "evt_2",
      "timestamp": "2026-10-08T15:30:01Z",
      "source": "PLANNER_AGENT",
      "type": "plan_created",
      "message": "Yazılım geliştirme planı başarıyla oluşturuldu."
    },
    {
      "id": "evt_3",
      "timestamp": "2026-10-08T15:30:02Z",
      "source": "SCOPE_AGENT",
      "type": "scope_completed",
      "message": "Dosya kapsamı belirlendi."
    },
    {
      "id": "evt_4",
      "timestamp": "2026-10-08T15:30:03Z",
      "source": "CODER_AGENT",
      "type": "coder_completed",
      "message": "Kod üretimi tamamlandı: 3 dosya izole çalışma alanına yazıldı."
    },
    {
      "id": "evt_5",
      "timestamp": "2026-10-08T15:30:04Z",
      "source": "TESTER_AGENT",
      "type": "tester_completed",
      "message": "Testler tamamlandı: 4 test başarılı, 0 hata."
    },
    {
      "id": "evt_6",
      "timestamp": "2026-10-08T15:30:05Z",
      "source": "REVIEWER_AGENT",
      "type": "reviewer_completed",
      "message": "Statik kod incelemesi tamamlandı (Verdict: APPROVED)."
    }
  ],
  "error": null
}
```

---

### 4. `GET /tasks/{task_id}`
Belirtilen ID'ye sahip görevin durumunu, planını, dosya kapsamını, Coder sonucunu, Tester sonucunu, Reviewer sonucunu ve olay günlüğünü döndürür.

---

### 5. `GET /tasks`
Mevcut tüm kalıcı görevleri oluşturulma tarihine göre azalan sırada listeler.

---

### 6. `GET /tasks/{task_id}/runs`
Belirtilen göreve ait tüm geçmiş iş akışı çalıştırmalarını kronolojik sırada (Run #1, Run #2...) döndürür.

**Örnek Yanıt:**
```json
{
  "task_id": "task_a1b2c3d4e5",
  "total_runs": 2,
  "runs": [
    {
      "id": "run_98765432",
      "task_id": "task_a1b2c3d4e5",
      "run_number": 1,
      "status": "reviewed",
      "started_at": "2026-10-08T15:30:00Z",
      "completed_at": "2026-10-08T15:30:05Z",
      "duration_ms": 5120.4,
      "error": null,
      "agent_metrics": [
        { "agent_name": "PLANNER", "status": "completed", "duration_ms": 120.5 },
        { "agent_name": "SCOPE", "status": "completed", "duration_ms": 85.2 },
        { "agent_name": "CODER", "status": "coded", "duration_ms": 310.8 },
        { "agent_name": "TESTER", "status": "tested", "duration_ms": 2400.1 },
        { "agent_name": "REVIEWER", "status": "reviewed", "duration_ms": 450.3 }
      ]
    }
  ]
}
```

---

### 7. `GET /tasks/{task_id}/runs/{run_id}`
Belirtilen tekil çalıştırma kaydının detaylı sonuçlarını (`plan`, `scope`, `coder`, `tester`, `reviewer`, `events`, `agent_metrics`) döndürür.

---

## Veritabanı Şeması (SQLite)

### `tasks` Tablosu
| Sütun | Tip | Açıklama |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | Görevin benzersiz kimliği (Örn: `task_a1b2c3d4e5`) |
| `description` | `TEXT NOT NULL` | Kullanıcının girdiği görev açıklaması |
| `status` | `TEXT NOT NULL` | Görevin güncel durumu (`queued`, `planned`, `scoped`, `coded`, `tested`, `reviewed`, `blocked`, `unsupported`, `failed`) |
| `created_at` | `TEXT NOT NULL` | Oluşturulma UTC ISO zaman damgası |
| `updated_at` | `TEXT` | Son güncellenme UTC ISO zaman damgası |
| `plan_json` | `TEXT` | Son Planner planı (JSON) |
| `scope_json` | `TEXT` | Son Scope analizi (JSON) |
| `coder_json` | `TEXT` | Son Coder çıktısı (JSON) |
| `tester_json` | `TEXT` | Son Tester çıktısı (JSON) |
| `reviewer_json` | `TEXT` | Son Reviewer inceleme raporu (JSON) |
| `events_json` | `TEXT` | Olay günlüğü kayıtları (JSON listesi) |
| `error` | `TEXT` | Son hata mesajı (varsa) |

### `workflow_runs` Tablosu
| Sütun | Tip | Açıklama |
| :--- | :--- | :--- |
| `id` | `TEXT PRIMARY KEY` | Çalıştırmanın benzersiz kimliği (Örn: `run_a1b2c3d4`) |
| `task_id` | `TEXT NOT NULL` | İlişkili `tasks(id)` dış anahtarı (`ON DELETE CASCADE`) |
| `run_number` | `INTEGER NOT NULL` | Görev için kaçıncı çalıştırma olduğu (1, 2, 3...) |
| `status` | `TEXT NOT NULL` | Bu çalıştırmanın nihai durumu |
| `started_at` | `TEXT NOT NULL` | Başlangıç zamanı |
| `completed_at` | `TEXT` | Bitiş zamanı |
| `duration_ms` | `REAL` | Toplam çalışma süresi (milisaniye) |
| `error` | `TEXT` | Varsa hata mesajı |
| `plan_json` | `TEXT` | Çalıştırmadaki plan çıktısı |
| `scope_json` | `TEXT` | Çalıştırmadaki kapsam çıktısı |
| `coder_json` | `TEXT` | Çalıştırmadaki kod üretim çıktısı |
| `tester_json` | `TEXT` | Çalıştırmadaki test koşum çıktısı |
| `reviewer_json` | `TEXT` | Çalıştırmadaki kod inceleme çıktısı |
| `events_json` | `TEXT` | Çalıştırmadaki olay günlüğü |
| `agent_metrics_json` | `TEXT` | Agent bazlı süreler ve durumlar (JSON listesi) |
