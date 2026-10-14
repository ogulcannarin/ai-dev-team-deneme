"""
backend/tests/test_reviewer_semantic_verification.py
AI Dev Team — Reviewer Semantic Verification Layer Test Suite

7 Temel Senaryo:
S1 — Tarih farkı / hesap makinesi uyuşmazlığı: date_diff talep edilmişken calculator üretildiğinde testler geçse bile CHANGES_REQUESTED.
S2 — Doğru işlev: İstenen fonksiyon ve kriterler karşılandığında ve testler geçtiğinde APPROVED.
S3 — Kısmi gereksinim karşılanması: Karşılanmayan kriterler tespit edildiğinde CHANGES_REQUESTED.
S4 — Belirsiz görev ("Sistemi hızlandır..."): Somut kanıt olmadan onay verilmeyip 'uncertain' ve CHANGES_REQUESTED.
S5 — Teknik test hatası: Semantik uyumlu kodda bile test başarısızsa asla onay verilmemesi.
S6 — Güvenlik regresyonu: Path traversal, symlink ve izin verilmeyen dosyalarda BLOCKED kararı.
S7 — Hata durumları (Fail-Safe): Semantik katman beklenmeyen hata verse bile asla sessizce APPROVED üretilmemesi.
"""

import os
import tempfile
import uuid
import pytest

from schemas import (
    CriterionStatus,
    FindingSeverity,
    ReviewerVerdict,
)
from agent_workflow import (
    _execute_reviewer_in_workspace,
    _perform_semantic_verification,
)


def _setup_workspace(tmp_root: str, task_id: str, files: dict) -> str:
    """Geçici izole çalışma alanı ve dosyalarını hazırlar."""
    ws_dir = os.path.join(tmp_root, task_id)
    os.makedirs(ws_dir, exist_ok=True)
    for fname, content in files.items():
        with open(os.path.join(ws_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    return ws_dir


# =====================================================================
# SENARYO S1: Tarih Farkı / Hesap Makinesi Uyuşmazlığı
# =====================================================================

def test_semantic_s1_date_diff_calculator_mismatch():
    """
    S1: Kullanıcı 'date_diff(d1, d2)' tarih fonksiyonu isterken,
    Coder 'calculator.py' (add, subtract) üretmiş ve Tester 4 testi geçirmiştir.
    
    Beklenen Davranış:
    - Reviewer testler başarılı olsa bile iş gereksinimi ile kod arasındaki semantik
      uyuşmazlığı tespit etmelidir.
    - verdict == CHANGES_REQUESTED olmalıdır.
    - 'semantic_alignment' kategorisinde HIGH bulgu bulunmalıdır.
    - İlgili kabul kriteri 'not_met' olarak işaretlenmelidir.
    """
    task_id = f"task_sem_s1_{uuid.uuid4().hex[:6]}"
    desc = "İki tarih arasındaki gün farkını hesaplayan 'date_diff(d1: str, d2: str) -> int' fonksiyonunu yaz."

    calc_code = '''"""Hesaplama Modulu"""
def add(a: int, b: int) -> int:
    """Iki sayiyi toplar."""
    return a + b

def subtract(a: int, b: int) -> int:
    """Iki sayiyi cikarir."""
    return a - b
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "calculator.py": calc_code,
            "README.md": "# Calculator Module\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 4,
            "failed": 0,
            "summary": "Ran 4 tests in 0.01s. OK.",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        # Karar ve Durum Doğrulaması
        assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert result.status == "reviewed"

        # Semantik bulgu doğrulaması
        sem_findings = [f for f in result.findings if f.category == "semantic_alignment"]
        assert len(sem_findings) >= 1
        assert sem_findings[0].severity == FindingSeverity.HIGH
        assert "tarih" in sem_findings[0].description.lower() or "date_diff" in sem_findings[0].description.lower()

        # Kriter değerlendirmesi
        not_met_evals = [e for e in result.semantic_evaluations if e.status == CriterionStatus.NOT_MET]
        assert len(not_met_evals) >= 1
        assert "date_diff" in not_met_evals[0].evidence.lower() or "tarih" in not_met_evals[0].evidence.lower()


# =====================================================================
# SENARYO S2: Doğru İşlev (Happy Path Semantik Onay)
# =====================================================================

def test_semantic_s2_correct_functionality_approved():
    """
    S2: Kullanıcı toplama ve çıkarma fonksiyonlarını talep etmiştir.
    Coder doğru şekilde 'calculator.py' üretmiş, testler geçmiş ve kriterler karşılanmıştır.
    
    Beklenen Davranış:
    - Reviewer semantik uyumu, fonksiyon varlığını ve test başarısını onaylamalıdır.
    - verdict == APPROVED olmalıdır.
    - Kriterlerin tamamı 'met' olmalıdır.
    """
    task_id = f"task_sem_s2_{uuid.uuid4().hex[:6]}"
    desc = "Python ile iki sayıyı toplayan add ve çıkaran subtract fonksiyonlarını içeren bir hesaplama modülü yaz."

    calc_code = '''"""Hesaplama Modulu"""
def add(a: int, b: int) -> int:
    """Iki sayiyi toplar."""
    return a + b

def subtract(a: int, b: int) -> int:
    """Iki sayiyi cikarir."""
    return a - b
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "calculator.py": calc_code,
            "README.md": "# Calculator Module\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 4,
            "failed": 0,
            "summary": "Ran 4 tests. OK.",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        assert result.verdict == ReviewerVerdict.APPROVED
        assert result.status == "reviewed"
        assert len(result.semantic_evaluations) > 0
        assert all(e.status == CriterionStatus.MET for e in result.semantic_evaluations)


# =====================================================================
# SENARYO S3: Kısmi Gereksinim Karşılanması
# =====================================================================

def test_semantic_s3_partial_requirements_changes_requested():
    """
    S3: Kullanıcı 'filter_emails' fonksiyonunu talep etmiştir ancak üretilen kod
    yalnızca standart REST API router içermektedir (email filtresi eksiktir).
    
    Beklenen Davranış:
    - Eksik işlev 'not_met' olarak işaretlenmeli.
    - Reviewer CHANGES_REQUESTED vermelidir.
    """
    task_id = f"task_sem_s3_{uuid.uuid4().hex[:6]}"
    desc = "Verilen e-posta listesini regex ile filtreleyen 'filter_emails' fonksiyonunu yaz."

    api_code = '''"""Item API Feature"""
from fastapi import APIRouter
router = APIRouter()

def get_status() -> str:
    """Durum dondurur."""
    return "ok"
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "api_feature.py": api_code,
            "README.md": "# API Feature\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/api_feature.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 2,
            "failed": 0,
            "summary": "Ran 2 tests. OK.",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert any(e.status == CriterionStatus.NOT_MET for e in result.semantic_evaluations)
        assert any(f.category == "semantic_alignment" for f in result.findings)


# =====================================================================
# SENARYO S4: Belirsiz Görev ("Sistemi hızlandır...")
# =====================================================================

def test_semantic_s4_ambiguous_task_uncertain_not_approved():
    """
    S4: Görev açıklaması belirsizdir: 'Sistemi hızlandır ve verileri kaydet.'
    Somut bir API veya fonksiyon sözleşmesi tanımlanmamıştır.
    
    Beklenen Davranış:
    - Kriter durumu 'uncertain' olmalı.
    - Kanıtsız onay verilmemeli (CHANGES_REQUESTED).
    """
    task_id = f"task_sem_s4_{uuid.uuid4().hex[:6]}"
    desc = "Sistemi hızlandır ve verileri kaydet."

    api_code = '''"""Item API Feature"""
def placeholder_service() -> str:
    """Servis"""
    return "done"
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "api_feature.py": api_code,
            "README.md": "# API Feature\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/api_feature.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 1,
            "failed": 0,
            "summary": "Ran 1 test. OK.",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert any(e.status == CriterionStatus.UNCERTAIN for e in result.semantic_evaluations)
        assert any(f.category == "semantic_alignment" for f in result.findings)


# =====================================================================
# SENARYO S5: Teknik Test Hatası
# =====================================================================

def test_semantic_s5_technical_test_failure_not_approved():
    """
    S5: Kod semantik olarak toplama fonksiyonu içeriyor olsa bile,
    birim testleri başarısız olduysa (failed > 0) Reviewer ASLA onay vermemelidir.
    """
    task_id = f"task_sem_s5_{uuid.uuid4().hex[:6]}"
    desc = "İki sayıyı toplayan add fonksiyonu yaz."

    calc_code = '''"""Hesaplama"""
def add(a: int, b: int) -> int:
    """Toplar"""
    return a + b + 999  # Hatali kod
'''

    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "calculator.py": calc_code,
            "README.md": "# Calculator\n"
        })

        coder_data = {
            "status": "coded",
            "created_files": [f"workspaces/{task_id}/calculator.py", f"workspaces/{task_id}/README.md"]
        }
        tester_data = {
            "status": "tested",
            "passed": 1,
            "failed": 2,
            "summary": "Ran 3 tests. 2 failed.",
            "is_isolated": True
        }

        result = _execute_reviewer_in_workspace(
            task_id=task_id,
            description=desc,
            coder_data=coder_data,
            tester_data=tester_data,
            workspaces_root=tmp_workspaces
        )

        assert result.verdict == ReviewerVerdict.CHANGES_REQUESTED
        assert any(f.category == "testing" for f in result.findings)


# =====================================================================
# SENARYO S6: Güvenlik Regresyonu
# =====================================================================

def test_semantic_s6_security_regression_path_traversal_and_disallowed_files():
    """
    S6: Güvenlik kontrolleri (path traversal, izin verilmeyen dosya adı)
    semantik katmandan bağımsız olarak derhal BLOCKED vermelidir.
    """
    # 1. Geçersiz task_id (Path traversal)
    bad_task_id = "../../../etc/passwd"
    res1 = _execute_reviewer_in_workspace(task_id=bad_task_id, description="Test")
    assert res1.verdict == ReviewerVerdict.BLOCKED
    assert res1.status == "blocked"

    # 2. İzin verilmeyen dosya adı
    task_id = f"task_sem_s6_{uuid.uuid4().hex[:6]}"
    with tempfile.TemporaryDirectory() as tmp_workspaces:
        _setup_workspace(tmp_workspaces, task_id, {
            "unauthorized_script.sh": "#!/bin/bash\necho hack\n"
        })

        res2 = _execute_reviewer_in_workspace(
            task_id=task_id,
            description="Script görevi",
            coder_data={"status": "coded", "created_files": [f"workspaces/{task_id}/unauthorized_script.sh"]},
            workspaces_root=tmp_workspaces
        )
        assert res2.verdict == ReviewerVerdict.BLOCKED
        assert any(f.severity == FindingSeverity.CRITICAL for f in res2.findings)


# =====================================================================
# SENARYO S7: Hata Durumları (Fail-Safe Güvenlik)
# =====================================================================

def test_semantic_s7_semantic_layer_exception_failsafe():
    """
    S7: Semantik doğrulama fonksiyonuna geçersiz/bozuk parametreler verildiğinde veya
    içeride beklenmeyen bir exception fırlatıldığında, sistem çökmeyip fail-safe
    olarak HIGH bulgu üretmeli ve ASLA sessizce APPROVED vermemelidir.
    """
    task_id = f"task_sem_s7_{uuid.uuid4().hex[:6]}"

    # Bozuk/hatalı yapılarla doğrudan _perform_semantic_verification çağrısı
    evals, findings = _perform_semantic_verification(
        task_id=task_id,
        description=None,  # type: ignore (Hata tetikleme)
        target_workspace="/invalid/nonexistent/path",
        plan_data={"acceptance_criteria": [12345]},  # type: ignore
        coder_data=None,
        tester_data=None,
        py_ast_map=None,
        py_contents=None
    )

    # Fail-safe doğrulamaları:
    # 1. Hata fırlatılmamış, güvenle yakalanmıştır
    assert len(findings) >= 1
    assert any(f.category == "semantic_alignment" for f in findings)
    assert any(f.severity == FindingSeverity.HIGH for f in findings)
    assert any(e.status == CriterionStatus.UNCERTAIN for e in evals)
