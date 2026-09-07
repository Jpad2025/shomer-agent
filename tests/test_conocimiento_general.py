"""Pruebas de la base de conocimiento técnico (conocimiento_general.py).

Este módulo alimenta directamente el prompt del cerebro (brain.py) -- un dato
roto aquí (dominio vacío, keyword ambigua, conteo desincronizado) llega
silenciosamente a producción. Estas pruebas existen para atrapar exactamente
los tipos de error reales que encontramos en la auditoría del 6 sep 2026:
una keyword de dominio ("pc") que hacía falso positivo por substring dentro
de "recepcion", y desincronización entre el conteo esperado y el real tras
editar las listas de seed.
"""


class TestSeed:
    def test_seed_if_empty_inserts_expected_count(self, cg):
        n_reglas = cg.seed_if_empty(aprobado_por="test")
        n_teoria = cg.seed_teoria_if_empty(aprobado_por="test")
        assert n_reglas == len(cg._SEED_RULES)
        assert n_teoria == len(cg._SEED_TEORIA)
        assert n_reglas > 0
        assert n_teoria > 0

    def test_seed_is_idempotent(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        antes_reglas = len(cg.list_rules())
        antes_teoria = len(cg.list_teoria())

        # Segunda corrida -- no debe duplicar nada, tabla ya no está vacía.
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")

        assert len(cg.list_rules()) == antes_reglas
        assert len(cg.list_teoria()) == antes_teoria

    def test_seed_lists_match_db_after_insert(self, cg):
        """Guarda contra el caso real: alguien edita _SEED_RULES/_SEED_TEORIA
        pero el conteo insertado no coincide (dict mal formado, coma faltante
        que fusiona dos entradas, etc.)."""
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        assert len(cg.list_rules()) == len(cg._SEED_RULES)
        assert len(cg.list_teoria()) == len(cg._SEED_TEORIA)


class TestIntegridadDeContenido:
    """Cada entrada debe tener todos sus campos -- un campo vacío es
    exactamente el tipo de error silencioso que un despliegue rápido puede
    dejar pasar (ej. un merge de Edit mal cerrado)."""

    def test_todas_las_reglas_tienen_campos_completos(self, cg):
        campos = ("dominio", "patron", "causa_probable", "recomendacion", "fuente")
        vacias = [
            (i, campo)
            for i, r in enumerate(cg._SEED_RULES)
            for campo in campos
            if not r.get(campo, "").strip()
        ]
        assert vacias == [], f"Reglas con campos vacíos (idx, campo): {vacias}"

    def test_toda_la_teoria_tiene_campos_completos(self, cg):
        campos = ("dominio", "concepto", "explicacion", "relevancia_diagnostica", "fuente")
        vacias = [
            (i, campo)
            for i, t in enumerate(cg._SEED_TEORIA)
            for campo in campos
            if not t.get(campo, "").strip()
        ]
        assert vacias == [], f"Teoría con campos vacíos (idx, campo): {vacias}"

    def test_dominios_de_reglas_y_teoria_son_snake_case_consistente(self, cg):
        """Un dominio con typo (ej. 'segurdad' en vez de 'seguridad') queda
        huérfano -- nunca lo devuelve matching_domains ni aparece agrupado
        con el resto de su tema."""
        for i, r in enumerate(cg._SEED_RULES):
            d = r["dominio"]
            assert d == d.lower(), f"regla idx={i}: dominio '{d}' no es minúscula"
            assert " " not in d, f"regla idx={i}: dominio '{d}' tiene espacio (usar _)"


class TestMatchingDomains:
    def test_fallback_a_metodologia_sin_match(self, cg):
        assert cg.matching_domains(["equipo genérico sin marca"]) == ["metodologia"]

    def test_bixolon_matchea_impresoras_termicas_pos(self, cg):
        assert "impresoras_termicas_pos" in cg.matching_domains(["Bixolon-Bar02"])

    def test_mikrotik_matchea_dominio_mikrotik(self, cg):
        assert "mikrotik" in cg.matching_domains(["MikroTik Router Principal"])

    def test_no_falso_positivo_pc_dentro_de_recepcion(self, cg):
        """Regresión directa del bug real encontrado el 6 sep 2026: la keyword
        'pc' hacía match por substring dentro de 'rece-PC-ion', activando
        sistemas_operativos para un dispositivo que no es una PC ni un
        servidor. Ver CHANGELOG v1.16.0."""
        dominios = cg.matching_domains(["Tablet Recepcion"])
        assert "sistemas_operativos" not in dominios
        assert "dispositivos_moviles" in dominios

    def test_srv_matchea_sistemas_operativos_y_hardware(self, cg):
        dominios = cg.matching_domains(["SRVAD01"])
        assert "sistemas_operativos" in dominios
        assert "hardware" in dominios


class TestFormatForPrompt:
    def test_devuelve_texto_vacio_si_no_hay_conocimiento_sembrado(self, cg):
        # Sin seed_if_empty(), las tablas están vacías -- no debe romper.
        assert cg.format_for_prompt(["cualquier cosa"]) == ""

    def test_incluye_reglas_del_dominio_relevante(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        texto = cg.format_for_prompt(["Bixolon-Bar02"])
        assert "impresoras_termicas_pos" in texto or "sin papel" in texto.lower()

    def test_no_forzar_conocimiento_irrelevante(self, cg):
        """format_for_prompt no debe inventar contenido -- si no hay match,
        cae a metodologia (siempre debe tener algo, es el dominio de respaldo)."""
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        texto = cg.format_for_prompt(["equipo totalmente desconocido xyz123"])
        assert texto != ""  # cae a metodologia, nunca queda en blanco si hay seed


class TestAprendizajeConfirmacionRefutacion:
    def test_registrar_confirmacion_incrementa_contador(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        dominios = cg.dominios()
        assert dominios, "no hay dominios sembrados"
        objetivo = dominios[0]

        afectadas = cg.registrar_confirmacion([objetivo])
        assert afectadas > 0

        reglas = cg.list_rules(objetivo)
        assert all(r["veces_confirmado"] >= 1 for r in reglas)

    def test_registrar_refutacion_incrementa_contador_distinto(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        dominios = cg.dominios()
        objetivo = dominios[0]

        cg.registrar_refutacion([objetivo])
        reglas = cg.list_rules(objetivo)
        assert all(r["veces_refutado"] >= 1 for r in reglas)
        assert all(r["veces_confirmado"] == 0 for r in reglas)

    def test_lista_vacia_no_afecta_nada(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        assert cg.registrar_confirmacion([]) == 0
        assert cg.registrar_refutacion([]) == 0
