"""core/learning.py -- el pegamento entre lo que confirma el técnico y las
TASK-* del catálogo. Si record_human_confirmation() se rompe en silencio,
el sistema simplemente deja de sugerir promociones learning→approved -- se
ve tranquilo, pero en realidad dejó de progresar.
"""
import importlib

import pytest


@pytest.fixture()
def lrn(temp_db_path):
    # agente_skills fija KNOWLEDGE_DB como constante de módulo al importarse --
    # sin recargarlo acá, on_task_completed() escribiría en la BD temporal de
    # un test anterior en vez de en la de este test.
    from core import agente_skills as _sk
    from core import auto_tasks as _at
    from core import learning as _lrn

    importlib.reload(_sk)
    importlib.reload(_at)
    importlib.reload(_lrn)
    yield _lrn


class TestInferTaskFromText:
    def test_reconoce_disco_lleno_como_task_001(self, lrn):
        assert lrn.infer_task_from_text("disco lleno, sin espacio", "limpieza journal") == "TASK-001"

    def test_reconoce_guardian_caido_como_task_002(self, lrn):
        assert lrn.infer_task_from_text("guardian caído", "restart panel 8000") == "TASK-002"

    def test_texto_ambiguo_no_inventa_tarea(self, lrn):
        assert lrn.infer_task_from_text("el internet del hotel está lento", "revisar router") is None

    def test_una_sola_palabra_clave_no_alcanza(self, lrn):
        # "puerto" solo aparece en TASK-008 keywords, un solo match -- score 1, no llega a 2
        assert lrn.infer_task_from_text("revisar puerto", "nada especial") is None


class TestConfirmacionHumana:
    def test_no_hace_nada_si_supervised_esta_apagado(self, lrn, monkeypatch):
        monkeypatch.delenv("BOT_LEARN_SUPERVISED", raising=False)
        lrn.record_human_confirmation("TASK-001")

        from core import auto_tasks as at
        assert at.get_task_stats("TASK-001")["human_confirmations"] == 0

    def test_suma_confirmacion_cuando_supervised_esta_prendido(self, lrn, monkeypatch):
        monkeypatch.setenv("BOT_LEARN_SUPERVISED", "1")
        lrn.record_human_confirmation("TASK-001")
        lrn.record_human_confirmation("TASK-001")

        from core import auto_tasks as at
        assert at.get_task_stats("TASK-001")["human_confirmations"] == 2

    def test_sin_task_id_no_hace_nada(self, lrn, monkeypatch):
        monkeypatch.setenv("BOT_LEARN_SUPERVISED", "1")
        lrn.record_human_confirmation("")  # no debe reventar ni insertar nada


class TestOnKnowledgeSaved:
    def test_detecta_task_y_confirma_cuando_supervised(self, lrn, monkeypatch):
        monkeypatch.setenv("BOT_LEARN_SUPERVISED", "1")
        result = lrn.on_knowledge_saved(
            "guardian caído, panel sin responder", "restart 8000",
            device_ip="192.168.0.10", saved_by="tecnico1",
        )
        assert result["task_id"] == "TASK-002"
        assert result["skill_id"] is not None

        from core import auto_tasks as at
        assert at.get_task_stats("TASK-002")["human_confirmations"] == 1

    def test_sin_supervised_no_crea_skill_pero_igual_confirma_si_hay_task(self, lrn, monkeypatch):
        monkeypatch.delenv("BOT_LEARN_SUPERVISED", raising=False)
        result = lrn.on_knowledge_saved("disco lleno espacio", "limpieza journal")
        assert result["task_id"] == "TASK-001"
        assert result["skill_id"] is None


class TestOnTaskCompleted:
    class _FakeResult:
        def __init__(self, task_id, action="accion", green_ok=True, context=None):
            self.task_id = task_id
            self.action = action
            self.green_ok = green_ok
            self.green_detail = "detalle"
            self.context = context or {}

    def test_no_hace_nada_si_autonomous_apagado(self, lrn, monkeypatch):
        monkeypatch.delenv("BOT_LEARN_AUTONOMOUS", raising=False)
        lrn.on_task_completed(self._FakeResult("TASK-002"), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        assert sk.list_skills(task_id="TASK-002") == []

    def test_registra_skill_para_task_t1_con_autonomous_prendido(self, lrn, monkeypatch):
        monkeypatch.setenv("BOT_LEARN_AUTONOMOUS", "1")
        monkeypatch.setenv("BOT_AUTO_SAFE_ONLY", "1")
        lrn.on_task_completed(self._FakeResult("TASK-002"), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        assert len(sk.list_skills(task_id="TASK-002")) == 1

    def test_nunca_registra_skill_para_task_010(self, lrn, monkeypatch):
        """TASK-010 (reboot AP) está prohibida del catálogo -- ni siquiera
        debería llegar acá, pero si llega, no debe aprender nada de ella."""
        monkeypatch.setenv("BOT_LEARN_AUTONOMOUS", "1")
        lrn.on_task_completed(self._FakeResult("TASK-010"), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        assert sk.list_skills(task_id="TASK-010") == []

    def test_auto_safe_only_bloquea_tasks_fuera_de_t1(self, lrn, monkeypatch):
        """TASK-007 (alerta de backup) no está en el set T1 -- con
        BOT_AUTO_SAFE_ONLY=1 (default en Ópera) no debe aprender de ella
        automáticamente, aunque hoy corra en modo approved."""
        monkeypatch.setenv("BOT_LEARN_AUTONOMOUS", "1")
        monkeypatch.setenv("BOT_AUTO_SAFE_ONLY", "1")
        lrn.on_task_completed(self._FakeResult("TASK-007"), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        assert sk.list_skills(task_id="TASK-007") == []

    def test_auto_safe_only_en_0_si_permite_tasks_fuera_de_t1(self, lrn, monkeypatch):
        monkeypatch.setenv("BOT_LEARN_AUTONOMOUS", "1")
        monkeypatch.setenv("BOT_AUTO_SAFE_ONLY", "0")
        lrn.on_task_completed(self._FakeResult("TASK-007"), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        assert len(sk.list_skills(task_id="TASK-007")) == 1

    def test_varios_equipos_muestreados_van_al_detalle_no_a_un_solo_ip(self, lrn, monkeypatch):
        """TASK-006 (auditoría muestral) toca varios equipos a la vez --
        etiquetar la skill con un solo device_ip inventaría un dato."""
        monkeypatch.setenv("BOT_LEARN_AUTONOMOUS", "1")
        monkeypatch.setenv("BOT_AUTO_SAFE_ONLY", "1")
        ctx = {"sample_devices": [
            {"ip": "1.1.1.1", "name": "PC-1"}, {"ip": "2.2.2.2", "name": "PC-2"},
        ]}
        lrn.on_task_completed(self._FakeResult("TASK-006", context=ctx), "approved")

        from core import agente_skills as sk
        importlib.reload(sk)
        skills = sk.list_skills(task_id="TASK-006")
        assert len(skills) == 1
        assert skills[0]["device_ip"] == ""
        assert "PC-1" in skills[0]["notes"] and "PC-2" in skills[0]["notes"]


class TestFeedbackSuffixYMarkup:
    def test_feedback_suffix_vacio_sin_meta(self, lrn):
        assert lrn.feedback_suffix(None) == ""

    def test_feedback_suffix_incluye_task_correlacionado(self, lrn):
        suffix = lrn.feedback_suffix({"task_id": "TASK-001", "skill_id": None})
        assert "TASK-001" in suffix

    def test_task_feedback_markup_tiene_los_4_botones_esperados(self, lrn):
        markup = lrn.task_feedback_markup("task-001")
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert callbacks == [
            "save_task:y:TASK-001", "save_task:n:TASK-001",
            "save_task:o:TASK-001", "save_task:x:0",
        ]
