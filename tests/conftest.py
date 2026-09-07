"""Fixtures compartidas -- cada test corre contra su propia knowledge.db
temporal, nunca contra /app/data/knowledge.db real."""
import os
import sys
import tempfile

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture()
def temp_db_path(tmp_path):
    """Ruta a una knowledge.db vacía y temporal, aislada por test."""
    db = tmp_path / "knowledge_test.db"
    os.environ["KNOWLEDGE_DB_PATH"] = str(db)
    yield str(db)


@pytest.fixture()
def cg(temp_db_path):
    """Módulo conocimiento_general recargado contra la DB temporal del test."""
    import importlib

    from core import conocimiento_general as _cg

    importlib.reload(_cg)
    _cg.init_db()
    _cg.init_db_teoria()
    yield _cg


@pytest.fixture()
def ct(temp_db_path):
    """Módulo chronic_tickets recargado contra la DB temporal del test."""
    import importlib

    from core import chronic_tickets as _ct

    importlib.reload(_ct)
    yield _ct
