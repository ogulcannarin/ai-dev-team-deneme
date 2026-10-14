import type { ApiHealthResponse, BackendTask, LLMProviderInfo, WorkflowRun, WorkflowRunListResponse } from '../types';

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

export class ApiError extends Error {
  status?: number;
  details?: unknown;

  constructor(message: string, status?: number, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

/**
 * Backend sağlık durumunu sorgular (GET /health)
 */
export async function getHealth(): Promise<ApiHealthResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new ApiError(
        `Sağlık kontrolü başarısız oldu (${response.status} ${response.statusText})`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Lütfen Python FastAPI sunucusunun çalıştığından emin olun.`,
      0,
      err
    );
  }
}

/**
 * Backend LLM sağlayıcı yapılandırmasını sorgular (GET /system/llm-info)
 */
export async function getLLMInfo(): Promise<LLMProviderInfo> {
  try {
    const response = await fetch(`${API_BASE_URL}/system/llm-info`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new ApiError(
        `LLM sağlayıcı bilgisi alınamadı (${response.status} ${response.statusText})`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). LLM bilgisi sorgulanamadı.`,
      0,
      err
    );
  }
}

/**
 * Yeni bir görev kaydı oluşturur (POST /tasks)
 * Format: { "description": "...", "planner_mode": "...", "coder_mode": "..." }
 */
export async function createBackendTask(
  description: string,
  plannerMode?: string,
  coderMode?: string,
  requireHumanApproval?: boolean
): Promise<BackendTask> {
  const trimmed = description.trim();
  if (!trimmed) {
    throw new ApiError('Görev açıklaması boş bırakılamaz.', 400);
  }

  try {
    const payload: {
      description: string;
      planner_mode?: string;
      coder_mode?: string;
      require_human_approval?: boolean;
    } = {
      description: trimmed,
    };
    if (plannerMode) {
      payload.planner_mode = plannerMode;
    }
    if (coderMode) {
      payload.coder_mode = coderMode;
    }
    if (typeof requireHumanApproval === 'boolean') {
      payload.require_human_approval = requireHumanApproval;
    }

    const response = await fetch(`${API_BASE_URL}/tasks`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let errorDetail = `${response.status} ${response.statusText}`;
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorDetail = typeof errorJson.detail === 'string'
            ? errorJson.detail
            : JSON.stringify(errorJson.detail);
        }
      } catch {
        // use status text fallback
      }
      throw new ApiError(
        `Görev oluşturulamadı: ${errorDetail}`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine erişilemedi (${API_BASE_URL}). Lütfen sunucunun açık olduğundan emin olun.`,
      0,
      err
    );
  }
}

/**
 * Tüm görev listesini getirir (GET /tasks)
 */
export async function getBackendTasks(): Promise<BackendTask[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      throw new ApiError(
        `Görevler alınamadı (${response.status} ${response.statusText})`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Görev listesi yüklenemedi.`,
      0,
      err
    );
  }
}

/**
 * Belirli bir görevin detayını getirir (GET /tasks/{task_id})
 */
export async function getBackendTaskById(taskId: string): Promise<BackendTask> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (response.status === 404) {
      throw new ApiError(`'${taskId}' kimlikli görev bulunamadı.`, 404);
    }

    if (!response.ok) {
      let errorDetail = `${response.status} ${response.statusText}`;
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorDetail = typeof errorJson.detail === 'string'
            ? errorJson.detail
            : JSON.stringify(errorJson.detail);
        }
      } catch {}
      throw new ApiError(
        `Görev detayı alınamadı: ${errorDetail}`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Görev detayı sorgulanamadı.`,
      0,
      err
    );
  }
}

/**
 * Görevin LangGraph agent iş akışını tetikler (POST /tasks/{task_id}/run)
 * Planner + Scope + Coder + Tester + Reviewer zincirini çalıştırır.
 */
export async function runBackendTask(
  taskId: string,
  plannerMode?: string,
  coderMode?: string,
  requireHumanApproval?: boolean
): Promise<BackendTask> {
  try {
    const params = new URLSearchParams();
    if (plannerMode) params.set('planner_mode', plannerMode);
    if (coderMode) params.set('coder_mode', coderMode);
    if (typeof requireHumanApproval === 'boolean') {
      params.set('require_human_approval', requireHumanApproval ? 'true' : 'false');
    }
    const queryString = params.toString() ? `?${params.toString()}` : '';

    const url = `${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/run${queryString}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (response.status === 404) {
      throw new ApiError(`'${taskId}' kimlikli görev bulunamadı.`, 404);
    }

    if (response.status === 409) {
      throw new ApiError(`'${taskId}' kimlikli görev için bir iş akışı şu anda zaten çalışıyor.`, 409);
    }

    if (!response.ok) {
      let errorDetail = `${response.status} ${response.statusText}`;
      try {
        const errorJson = await response.json();
        if (errorJson.detail) {
          errorDetail = typeof errorJson.detail === 'string'
            ? errorJson.detail
            : JSON.stringify(errorJson.detail);
        }
      } catch {}
      throw new ApiError(
        `Agent iş akışı çalıştırılamadı: ${errorDetail}`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Agent iş akışı tetiklenemedi.`,
      0,
      err
    );
  }
}

/**
 * Belirli bir görevin geçmiş iş akışı çalıştırmalarını listeler (GET /tasks/{task_id}/runs)
 */
export async function getTaskRuns(taskId: string): Promise<WorkflowRunListResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/runs`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (response.status === 404) {
      throw new ApiError(`'${taskId}' kimlikli görev bulunamadı.`, 404);
    }

    if (!response.ok) {
      throw new ApiError(
        `Çalıştırma geçmişi alınamadı (${response.status} ${response.statusText})`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Çalıştırma geçmişi yüklenemedi.`,
      0,
      err
    );
  }
}

/**
 * Belirli bir görevin tekil bir iş akışı çalıştırma detayını getirir (GET /tasks/{task_id}/runs/{run_id})
 */
export async function getTaskRunById(taskId: string, runId: string): Promise<WorkflowRun> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/runs/${encodeURIComponent(runId)}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (response.status === 404) {
      throw new ApiError(`'${taskId}' görevine ait '${runId}' kimlikli çalıştırma bulunamadı.`, 404);
    }

    if (!response.ok) {
      throw new ApiError(
        `Çalıştırma detayı alınamadı (${response.status} ${response.statusText})`,
        response.status
      );
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Backend servisine bağlanılamadı (${API_BASE_URL}). Çalıştırma detayı yüklenemedi.`,
      0,
      err
    );
  }
}

/**
 * Görevi insan onayı ile onaylar (POST /tasks/{task_id}/approve)
 */
export async function approveBackendTask(taskId: string, comment?: string, approvedBy?: string): Promise<BackendTask> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/approve`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        comment: comment || 'İnsan onayı verildi.',
        approved_by: approvedBy || 'reviewer_human',
      }),
    });

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const errJson = await response.json();
        if (errJson.detail) detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } catch {}
      throw new ApiError(`Görev onaylanamadı: ${detail}`, response.status);
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Backend servisine bağlanılamadı (${API_BASE_URL}). Görev onaylanamadı.`, 0, err);
  }
}

/**
 * Git teslimatını Planner ve Coder çalıştırmadan yeniden dener (POST /tasks/{task_id}/deliver)
 */
export async function redeliverBackendTask(taskId: string): Promise<BackendTask> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/deliver`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const errJson = await response.json();
        if (errJson.detail) detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } catch {}
      throw new ApiError(`Teslimat yeniden denenemedi: ${detail}`, response.status);
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Backend servisine bağlanılamadı (${API_BASE_URL}). Teslimat yeniden denenemedi.`, 0, err);
  }
}

/**
 * Görevi insan incelemesinde reddeder / değişiklik talep eder (POST /tasks/{task_id}/reject)
 */
export async function rejectBackendTask(taskId: string, reason: string, rejectedBy?: string): Promise<BackendTask> {
  const trimmed = reason.trim();
  if (!trimmed) {
    throw new ApiError('Red gerekçesi boş bırakılamaz.', 400);
  }

  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/reject`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        reason: trimmed,
        rejected_by: rejectedBy || 'reviewer_human',
      }),
    });

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const errJson = await response.json();
        if (errJson.detail) detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } catch {}
      throw new ApiError(`Görev reddedilemedi: ${detail}`, response.status);
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Backend servisine bağlanılamadı (${API_BASE_URL}). Görev reddedilemedi.`, 0, err);
  }
}

/**
 * Görevi iptal eder (POST /tasks/{task_id}/cancel)
 */
export async function cancelBackendTask(taskId: string): Promise<BackendTask> {
  try {
    const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const errJson = await response.json();
        if (errJson.detail) detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } catch {}
      throw new ApiError(`Görev iptal edilemedi: ${detail}`, response.status);
    }

    return await response.json();
  } catch (err: unknown) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Backend servisine bağlanılamadı (${API_BASE_URL}). Görev iptal edilemedi.`, 0, err);
  }
}

export { API_BASE_URL };

