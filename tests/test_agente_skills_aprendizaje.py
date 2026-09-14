"""core/agente_skills.py -- lo que queda guardado cuando el técnico enseña
(botones 👍/👎, /guardar) o cuando una TASK automática confirma Green State.

Si record_from_human() se rompe, el técnico sigue viendo el botón, lo sigue
tocando, cree que está enseñando algo -- y no se guarda nada. Nadie se entera
hasta meses después, cuando alguien pregunta por qué el cerebro nunca aprendió
nada de tal equipo. Estas pruebas existen para que ese silencio se note acá.
"""
import importlib

import pytest


@pytest.fixture()
def sk(temp_db_path, monkeypatch):
    monkeypatch.setenv("SITE_NAME", "hotelopera")
    from core import agente_skills as _sk

    importlib.reload(_sk)
    yield _sk


def test_record_from_human_crea_skill_nueva(sk):
    sid = sk.record_from_human(
        "AP de recepción cae seguido",
        "Reinicio remoto",
        device_ip="192.168.0.121",
        device_name="AP Recepción",
        saved_by="tecnico1",
    )
    assert sid is not None

    skills = sk.list_skills(device_ip="192.168.0.121")
    assert len(skills) == 1
    assert skills[0]["source"] == "human"
    assert skills[0]["success_count"] == 1
    assert skills[0]["device_name"] == "AP Recepción"


def test_ensenar_lo_mismo_dos_veces_acumula_no_duplica(sk):
    """El mismo problema+acción enseñado dos veces debe sumar confianza
    (success_count=2), no crear dos filas sueltas."""
    sk.record_from_human("Disco lleno", "Limpieza journal", device_ip="10.0.0.5")
    sk.record_from_human("Disco lleno", "Limpieza journal", device_ip="10.0.0.5")

    skills = sk.list_skills(device_ip="10.0.0.5")
    assert len(skills) == 1
    assert skills[0]["success_count"] == 2


def test_record_from_task_auto_ok_incrementa_success(sk):
    sid = sk.record_from_task(
        "TASK-002",
        trigger_label="Restart Guardian — TCP :8000 down",
        action_label="systemctl restart shomer-guardian",
        green_ok=True,
    )
    assert sid is not None
    skills = sk.list_skills(task_id="TASK-002")
    assert skills[0]["source"] == "auto"
    assert skills[0]["success_count"] == 1
    assert skills[0]["fail_count"] == 0


def test_record_from_task_fallido_incrementa_fail_no_success(sk):
    sk.record_from_task(
        "TASK-009", trigger_label="Restart Suricata", action_label="restart", green_ok=False,
    )
    skills = sk.list_skills(task_id="TASK-009")
    assert skills[0]["success_count"] == 0
    assert skills[0]["fail_count"] == 1


def test_feedback_humano_negativo_no_se_pierde_en_un_auto_previo(sk):
    """Si la TASK corrió sola (source=auto) y LUEGO el técnico dice explícitamente
    que no ayudó, esa señal humana debe quedar guardada -- es la única
    confirmación real que existe para esa tarea. record_task_feedback usa un
    action_key distinto ('feedback:TASK-X') al de la ejecución automática
    ('auto:TASK-X'), así que quedan como dos filas separadas -- ninguna de
    las dos debe desaparecer."""
    sk.record_from_task(
        "TASK-001", trigger_label="Limpieza disco", action_label="journal vacuum", green_ok=True,
    )
    sk.record_task_feedback("TASK-001", worked=False, notes="volvió a llenarse en 2 días")

    skills = sk.list_skills(task_id="TASK-001")
    assert len(skills) == 2

    auto = next(s for s in skills if s["source"] == "auto")
    feedback = next(s for s in skills if s["source"] == "human")
    assert auto["success_count"] == 1
    assert feedback["fail_count"] == 1
    assert feedback["notes"] == "volvió a llenarse en 2 días"


def test_list_skills_filtra_por_device_ip(sk):
    sk.record_from_human("Problema A", "Acción A", device_ip="1.1.1.1")
    sk.record_from_human("Problema B", "Acción B", device_ip="2.2.2.2")

    assert len(sk.list_skills(device_ip="1.1.1.1")) == 1
    assert len(sk.list_skills(device_ip="9.9.9.9")) == 0


def test_get_context_block_vacio_sin_skills(sk):
    assert sk.get_context_block(device_ip="192.168.0.1") == ""


def test_get_context_block_incluye_lo_aprendido(sk):
    sk.record_from_human("Impresora sin papel", "Reponer papel", device_ip="192.168.0.50")
    block = sk.get_context_block(device_ip="192.168.0.50")
    assert "Reponer papel" in block
    assert "OK:1" in block


def test_skills_de_un_sitio_no_se_mezclan_con_otro(sk, monkeypatch):
    sk.record_from_human("Problema en Ópera", "Acción", device_ip="1.1.1.1")

    monkeypatch.setenv("SITE_NAME", "otro-hotel")
    importlib.reload(sk)
    assert sk.list_skills(device_ip="1.1.1.1") == []
