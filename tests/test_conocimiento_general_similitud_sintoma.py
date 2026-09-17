"""16 sep 2026: _matching_domains solo reconoce nombres de marca/equipo
("switch", "bixolon", "ingenico") en el texto -- una pregunta de síntoma sin
marca, como "toda la red se puso lenta y no hay nada caído en el panel", no
matcheaba ningún dominio, aunque existe una regla casi idéntica en
'switching' ("Toda la red se pone lenta de golpe sin ningún equipo
reportado como caído" -> loop de red). Verificado en producción: esa
pregunta exacta hizo que el chat real ignorara esa regla y culpara a un AP
caído sin relación, contradiciendo la propia premisa de la pregunta.

Estas pruebas cubren el complemento de matching por síntoma
(_reglas_por_similitud_texto) agregado a find_relevant/format_for_prompt.
"""


class TestSimilitudPorSintomaSinMarca:
    def test_pregunta_de_sintoma_sin_marca_encuentra_la_regla_de_loop(self, cg):
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")

        pregunta = (
            "toda la red se puso lenta de un momento a otro y no hay nada "
            "caido en el panel, que reviso?"
        )
        texto = cg.format_for_prompt([pregunta], strict=True)
        assert "loop" in texto.lower() or "bucle" in texto.lower()

    def test_sin_match_de_dominio_ni_sintoma_strict_devuelve_vacio(self, cg):
        """strict=True no debe forzar 'metodologia' -- un saludo no debe
        gastar tokens en conocimiento que no aplica (comportamiento previo,
        no debe romperse con el nuevo matching por síntoma)."""
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        texto = cg.format_for_prompt(["hola, buenos días"], strict=True)
        assert texto == ""

    def test_similitud_no_reemplaza_match_de_dominio_ya_encontrado(self, cg):
        """Si el dominio por marca ya llena el cupo de reglas, no hace falta
        ni se debe diluir con matches de síntoma menos precisos."""
        cg.seed_if_empty(aprobado_por="test")
        cg.seed_teoria_if_empty(aprobado_por="test")
        reglas, _ = cg.find_relevant(["Bixolon-Bar02"], max_reglas=2, strict=True)
        assert len(reglas) <= 2
        assert all(r["dominio"] == "impresoras_termicas_pos" for r in reglas)

    def test_similitud_requiere_al_menos_dos_palabras_significativas_en_comun(self, cg):
        """Evita ruido: una sola palabra común (ej. 'red') no debe alcanzar
        para inyectar una regla de dominio no relacionado."""
        cg.seed_if_empty(aprobado_por="test")
        import sqlite3
        con = sqlite3.connect(cg.KNOWLEDGE_DB)
        con.row_factory = sqlite3.Row
        try:
            resultado = cg._reglas_por_similitud_texto("la red", con, set(), 5)
        finally:
            con.close()
        assert resultado == []
