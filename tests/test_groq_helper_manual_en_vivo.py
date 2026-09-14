"""14 sep 2026: existía un archivo generado EN BUILD (MANUAL_CAMPO_AGENTE.md)
que concatenaba TECNICO_OPERACION.md + SOPORTE_TECNICO.md una sola vez, al
construir la imagen. Como el deploy normal (fleet_sync.sh) solo reinicia el
contenedor y nunca reconstruye la imagen, ese archivo horneado quedó
congelado desde el 20 de junio -- verificado en Ópera, el bot seguía
respondiendo con contenido de junio pese a ediciones posteriores reales
(incluidas las de esta sesión). Se retiró el paso de build; ahora se lee
siempre en vivo. Esta prueba existe para que ese patrón (un artefacto
horneado que nadie reconstruye) no vuelva a colarse sin que se note."""
import importlib

import pytest


@pytest.fixture()
def gh(tmp_path, monkeypatch):
    from core import groq_helper as _gh

    importlib.reload(_gh)
    monkeypatch.setattr(_gh, "DOC_CAMPO_TECNICO", str(tmp_path / "tecnico.md"))
    monkeypatch.setattr(_gh, "DOC_CAMPO_SOPORTE", str(tmp_path / "soporte.md"))
    _gh._DOC_CACHE.clear()
    yield _gh


def test_no_existe_ningun_manual_unico_generado_en_build(gh):
    """Regresión directa: si alguien reintroduce un DOC_CAMPO_UNICO o similar
    apuntando a un archivo horneado en la imagen, esta prueba debe fallar."""
    assert not hasattr(gh, "DOC_CAMPO_UNICO")


def test_manual_search_content_refleja_una_edicion_reciente_sin_reiniciar_nada(gh, tmp_path):
    """El caso real que falló: se edita TECNICO_OPERACION.md y ese cambio
    debe verse reflejado de inmediato (mismo proceso, sin rebuild, sin
    reiniciar) porque se lee del disco -- no de una copia vieja horneada."""
    (tmp_path / "tecnico.md").write_text("Monitores automáticos (41 tareas)", encoding="utf-8")
    (tmp_path / "soporte.md").write_text("Procedimiento de soporte", encoding="utf-8")

    contenido = gh.manual_search_content("monitores")
    assert "41 tareas" in contenido

    # Edición posterior, sin tocar nada más del proceso -- debe verse apenas
    # se le gane al cache de 30 min (acá lo limpiamos a mano para simular
    # el paso del tiempo, igual que pasaría en producción).
    (tmp_path / "tecnico.md").write_text("Monitores automáticos (50 tareas)", encoding="utf-8")
    gh._DOC_CACHE.clear()
    contenido2 = gh.manual_search_content("monitores")
    assert "50 tareas" in contenido2
    assert "41 tareas" not in contenido2


def test_sin_ninguno_de_los_dos_archivos_no_revienta(gh):
    """Si faltan ambos (imagen incompleta, montaje caído), debe caer al
    corpus mínimo embebido, no lanzar una excepción."""
    contenido = gh.manual_search_content("cualquier cosa")
    assert contenido  # el fallback mínimo, no vacío ni excepción


def test_manual_search_content_combina_los_dos_archivos(gh, tmp_path):
    (tmp_path / "tecnico.md").write_text(
        "## Operación\nGuardian reinicia APs caídos.", encoding="utf-8"
    )
    (tmp_path / "soporte.md").write_text(
        "## Instalación\nConectar el Shomer a la red del hotel.", encoding="utf-8"
    )
    corpus = gh._corpus_campo()
    assert "Guardian reinicia" in corpus
    assert "Conectar el Shomer" in corpus
