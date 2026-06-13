"""Helper Groq — prompts por nivel + manual único en /app/docs/campo/MANUAL_CAMPO_AGENTE.md.

Generado en build desde TECNICO_OPERACION + SOPORTE_TECNICO; BEHAVIOR aparte si aplica.
Documentación developer (CLAUDE, SISTEMA): solo si AGENT_TECHNICIAN_ONLY=0 y rutas montadas en
/app/docs/developer/*.md (ver docker-compose comentario).
"""
import os
import re
import time
import logging
from groq import Groq, RateLimitError, APIConnectionError, APITimeoutError, APIStatusError

log = logging.getLogger("groq-helper")
_client = None

_CAMPO_DIR = "/app/docs/campo"
_DEV_DIR = "/app/docs/developer"

DOC_CAMPO_UNICO = os.path.join(_CAMPO_DIR, "MANUAL_CAMPO_AGENTE.md")
# Opcionales para regenerar MANUAL_CAMPO_AGENTE en build (no lectura runtime salvo fallback)
DOC_CAMPO_TECNICO = os.path.join(_CAMPO_DIR, "TECNICO_OPERACION.md")
DOC_CAMPO_SOPORTE = os.path.join(_CAMPO_DIR, "SOPORTE_TECNICO.md")
DOC_CAMPO_BEHAVIOR = os.path.join(_CAMPO_DIR, "BEHAVIOR.md")
DOC_DEV_CLAUDE = os.path.join(_DEV_DIR, "CLAUDE.md")
DOC_DEV_SISTEMA = os.path.join(_DEV_DIR, "SISTEMA_SHOMER.md")

_DOC_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 1800

_DOC_MAX_TECHNICO = 14_000
_DOC_MAX_DEVELOPER = 18_000
_MANUAL_SEARCH_DEFAULT = 12_000

# Fallback si falta disco / imagen incompleta
_CORPUS_TECNICO_MIN = """# Shomer — guía corta\nPanel: https://IP:8443\nComandos: /salud /salud /verificar /instalar\nSin acceso al manual extendido empaquetado; contactá soporte USB."""

_DEVELOPER_APPENDIX_FALLBACK = """
Referencia rápida (sin CLAUDE.md montado): Core :8000, Tools :8001, nginx HTTPS,
Hunter bloqueo vía iptables Linux/OpenWrt SSH, BD system_state network_monitor.db.
"""


def technician_only_mode() -> bool:
    """Mismo criterio que core.access."""
    return os.environ.get("AGENT_TECHNICIAN_ONLY", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ── Prompts sistema ───────────────────────────────────────────────────────────

_SYSTEM_BASE = (
    "Eres Shomer, agente de soporte IT embebido en el appliance de red del cliente. "
    "Hablas con un técnico de campo, no con un usuario final. "
    "Responde SIEMPRE en español técnico directo. "
    "FORMATO — aplica SOLO cuando hay un problema o pregunta técnica:\n"
    "1. DIAGNÓSTICO (1 línea): qué está pasando\n"
    "2. CAUSA (1 línea): por qué\n"
    "3. ACCIÓN (1-2 líneas): qué hacer ahora\n"
    "Si el mensaje es un saludo, agradecimiento o cierre — responde brevemente sin el formato. "
    "Sin relleno, sin disculpas, sin repetir la pregunta. "
    "CONTEXTO: tienes un snapshot del sistema inyectado en tu contexto (nodos Guardian, WAN, CPU/RAM/disco, IPs bloqueadas, backups fallidos). Para preguntas de estado general, RESPONDE directo desde el snapshot — NO llames tools, ya tienes el dato. Llama UNA tool solo si necesitas detalle que el snapshot no trae: ping puntual, latencia/cortes WAN, backup por equipo, particiones de disco, alertas Hunter, logs o manual — o para ejecutar una acción. Nunca encadenes más de 2 tools. Nunca inventes datos fuera del snapshot, las tools o el contexto. IPs y estados en `código`, alertas en negrita. "
    "Usa nombres operativos: APs, routers, nodos de red, Guardian y sus nodos — nunca 'guardianes' como término vago. "
    "No inventes rutas, módulos ni datos que no estén en el contexto o en las tools."
    "\nEJEMPLO — pregunta de estado, se responde desde el snapshot, sin llamar tools:\n"
    "Técnico: ¿por qué hay pérdida de servicio?\n"
    "Shomer:\n"
    "DIAGNÓSTICO: WAN caída, el servidor no alcanza internet.\n"
    "CAUSA: chequeos DNS `8.8.8.8` y `208.67.222.222` en FAIL; 2 backups fallaron por falta de red.\n"
    "ACCIÓN: revisa el uplink del router `.206`. Cuando vuelva la WAN, Protector reintenta solo."
)

_SYSTEM_TECNICO = (
    _SYSTEM_BASE + " "
    "Nivel técnico de campo: respuesta máxima 4 líneas operativas. "
    "No expongas rutas Python, módulos internos, nombres de BD ni credenciales. "
    "Si la causa es de código o arquitectura: 'Escalar a soporte USB.' "
    "Usa pasos numerados solo cuando sean acciones secuenciales."
)

_SYSTEM_DEVELOPER = (
    _SYSTEM_BASE + " "
    "Nivel desarrollador USB: respuesta máxima 10 líneas técnicas. "
    "Puedes citar rutas, módulos, tablas BD y fragmentos de código del contexto. "
    "Si no está en el contexto, dilo — no inventes."
)


_RULES_EMBEDDED_FALLBACK = """
IDENTIDAD: Shomer Sentinel, precisión sin inventar.
SNAPSHOT primero — si el estado está en el contexto inyectado, respóndelo directamente sin llamar tools. Tools solo para detalle extra. Si realmente no hay datos, di lo que sí ves en el snapshot.
Técnico: sin exponer internals. Critical → escalar USB.
"""


def _load_doc(path: str) -> str:
    now = time.time()
    cached = _DOC_CACHE.get(path)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        _DOC_CACHE[path] = (content, now)
        log.debug("Doc cargado: %s (%d chars)", path, len(content))
        return content
    except FileNotFoundError:
        log.warning("Doc no encontrado: %s", path)
        return ""


def _behavior_rules_text() -> str:
    txt = _load_doc(DOC_CAMPO_BEHAVIOR)
    return txt.strip() if txt.strip() else _RULES_EMBEDDED_FALLBACK


def _is_boilerplate_section(section: str) -> bool:
    """Prolog del .md antes del primer ## — mismo bloque aparecía siempre."""
    low = section.lower()
    short = len(section) < 1800
    if short and ("este documento es para el técnico" in low or "no contiene información de código" in low):
        return True
    if short and ("manual único para agente" in low or "no editar este archivo a mano" in low):
        return True
    return False


def _adjust_section_score(section: str, base_score: int, query_nonempty: bool) -> int:
    s = base_score
    if query_nonempty and _is_boilerplate_section(section):
        s -= 200
    if len(section.strip()) < 120 and base_score == 0:
        s -= 50
    return s


def _extract_relevant_sections(
    content: str,
    query: str,
    max_chars: int,
    *,
    allow_boilerplate: bool = False,
) -> str:
    if not content.strip():
        return ""
    if len(content) <= max_chars:
        return content

    qraw = (query or "").strip()
    query_words = {w for w in re.sub(r"[^\w\s]", "", query.lower()).split() if len(w) > 1}
    query_nonempty = bool(query_words)

    sections = re.split(r"\n(?=#{1,3} )", content)

    scored: list[tuple[int, str]] = []
    for section in sections:
        if not section.strip():
            continue
        first_line = section.splitlines()[0].lower() if section.strip() else ""
        body_lower = section.lower()
        base = sum(1 for w in query_words if w in body_lower)
        base += sum(5 for w in query_words if w in first_line)  # más peso al título
        adj = _adjust_section_score(section, base, query_nonempty)
        scored.append((adj, section))

    scored.sort(key=lambda x: x[0], reverse=True)

    chosen: list[str] = []
    total = 0
    seen: set[int] = set()

    skip_boiler_in_loop = query_nonempty and not allow_boilerplate

    # 1ª pasada: secciones con match > 0
    positive_done = False
    for adj, section in scored:
        if adj <= 0:
            continue
        if skip_boiler_in_loop and _is_boilerplate_section(section):
            continue
        sid = hash(section[:220])
        if sid in seen:
            continue
        positive_done = True
        room = max_chars - total - 80
        if room < 220:
            break
        frag = section if len(section) <= room else section[: room].rstrip() + "\n…"
        chosen.append(frag)
        seen.add(sid)
        total += len(frag) + 2
        if total >= max_chars:
            break

    # Si no hubo ningún match útil (>0 después de filtros), relleno sustantivo
    if not positive_done:
        fallback_ordered = sorted(scored, key=lambda x: (x[0], len(x[1])), reverse=True)
        seen_fb: set[int] = set()
        for _, section in fallback_ordered[:60]:
            if skip_boiler_in_loop and _is_boilerplate_section(section):
                continue
            sid = hash(section[:220])
            if sid in seen_fb:
                continue
            seen_fb.add(sid)
            room = max_chars - total - 80
            if room < 220:
                break
            frag = section if len(section) <= room else section[: room].rstrip() + "\n…"
            chosen.append(frag)
            total += len(frag) + 2
            if total >= max_chars:
                break
        if chosen:
            positive_done = True

    # Último recurso sólo texto inicial (sin repetir segundo bloque idéntico)
    if not chosen:
        trimmed = content[:max_chars].rstrip()
        return trimmed[:max_chars]

    out = "\n\n".join(chosen).strip()
    # Quitar párrafos duplicados consecutivos (copia-paste entre corpus)
    out = _collapse_duplicate_paragraphs(out)
    return out[:max_chars]


def _collapse_duplicate_paragraphs(text: str) -> str:
    blocks = text.split("\n\n")
    out_b: list[str] = []
    prev_norm = ""
    for raw in blocks:
        t = raw.strip()
        if not t:
            continue
        norm = re.sub(r"\s+", " ", t)[:380]
        if norm and norm == prev_norm:
            continue
        if norm:
            prev_norm = norm
        out_b.append(t)
    return "\n\n".join(out_b)


def _corpus_campo_fallback() -> str:
    """Si falta el manual unificado, concatena los dos legados."""
    t = _load_doc(DOC_CAMPO_TECNICO).strip()
    s = _load_doc(DOC_CAMPO_SOPORTE).strip()
    if not t and not s:
        return ""
    return (t + "\n\n---\n\n" + s).strip()


def manual_search_content(query: str, max_chars: int | None = None) -> str:
    """Búsqueda sobre un solo manual de campo (operación + soporte/instalación unificados)."""
    mc = max_chars or _MANUAL_SEARCH_DEFAULT
    corp = _load_doc(DOC_CAMPO_UNICO).strip()
    if not corp:
        corp = _corpus_campo_fallback()

    if not corp:
        return _CORPUS_TECNICO_MIN[:mc]

    q = (query or "").strip()

    if not q:
        intro = _collapse_duplicate_paragraphs(corp[: mc + 1].strip())
        return intro[:mc]

    chunk = _extract_relevant_sections(corp, q, mc)
    if not chunk.strip():
        chunk = _extract_relevant_sections(
            corp,
            "",
            min(mc + 800, len(corp)),
            allow_boilerplate=True,
        )
    return _collapse_duplicate_paragraphs(chunk.strip())[:mc]


def get_doc_context_tecnico(query: str = "", max_total: int | None = None) -> str:
    """Extractos del manual único de campo hasta max_total caracteres."""
    mt = max_total or _DOC_MAX_TECHNICO
    return manual_search_content(query or "", max_chars=mt)


def get_doc_context_developer(query: str = "") -> str:
    """
    Solo con AGENT_TECHNICIAN_ONLY=0 y ficheros montados en /app/docs/developer/.
    """
    if technician_only_mode():
        return ""

    budget = max(4000, _DOC_MAX_DEVELOPER // 2)
    parts: list[str] = []

    c1 = _load_doc(DOC_DEV_CLAUDE)
    if c1:
        parts.append(
            "## CLAUDE.md — extracto\n\n"
            + _extract_relevant_sections(c1, query, budget),
        )

    c2 = _load_doc(DOC_DEV_SISTEMA)
    if c2:
        parts.append(
            "## SISTEMA_SHOMER.md — extracto\n\n"
            + _extract_relevant_sections(c2, query, budget),
        )

    if not parts:
        return _DEVELOPER_APPENDIX_FALLBACK.strip()

    return "\n\n---\n\n".join(parts)[: _DOC_MAX_DEVELOPER]


def _appendix_for_explain(level: str, prompt: str, include_doc: bool) -> str:
    if level == "developer":
        if technician_only_mode():
            return ""
        return get_doc_context_developer(prompt)

    if not include_doc:
        return ""
    return get_doc_context_tecnico(prompt, max_total=_DOC_MAX_TECHNICO)


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(
            api_key=os.environ["GROQ_API_KEY"],
            max_retries=4,
            timeout=20.0,
        )
    return _client


def _register_usage(resp, endpoint: str = "chat") -> None:
    """Registra tokens consumidos si la respuesta los reporta."""
    try:
        usage = getattr(resp, "usage", None)
        if usage:
            tokens = getattr(usage, "total_tokens", 0) or 0
            if tokens > 0:
                from core.memory import record_tokens
                model = getattr(
                    getattr(resp, "model", None) or "llama-3.3-70b-versatile", "__str__", str
                )()
                record_tokens(tokens, model=model, endpoint=endpoint)
    except Exception:
        pass


def _check_budget_before_call() -> str | None:
    """
    Si el presupuesto diario está excedido retorna un mensaje de aviso
    y activa modo mantenimiento. Si solo está en warn, solo avisa en log.
    Retorna None si todo está OK.
    """
    try:
        from core.memory import check_token_budget, get_tokens_today
        status = check_token_budget()
        if status == "exceeded":
            used = get_tokens_today()
            log.warning("Presupuesto diario excedido: %d tokens — activando modo mantenimiento", used)
            from core import maintenance as _mnt
            _mnt.pause(secs=1800)  # 30 min de pausa
            return (
                f"⏳ El asistente IA alcanzó el límite diario de tokens ({used:,} usados). "
                "Retomará en ~30 min. Usa comandos directos: /salud · /alertas"
            )
        if status == "warn":
            from core.memory import get_tokens_today
            used = get_tokens_today()
            log.info("Tokens hoy: %d — acercándose al límite", used)
    except Exception:
        pass
    return None


def _call_groq(messages: list[dict], max_tokens: int) -> str:
    budget_msg = _check_budget_before_call()
    if budget_msg:
        return budget_msg
    try:
        resp = _get_client().chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        _register_usage(resp, endpoint="explain")
        return (resp.choices[0].message.content or "").strip()

    except RateLimitError:
        log.warning("Groq rate-limit — reintentando en 4s")
        time.sleep(4)
        try:
            resp = _get_client().chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.1,
            )
            return (resp.choices[0].message.content or "").strip()
        except RateLimitError:
            from core import maintenance as _mnt

            _mnt.pause()
            return (
                "⏳ Cuota Groq agotada — el asistente entrará en pausa breve (~90s). "
                "Usa comandos directos: /salud · /alertas"
            )

    except APIConnectionError:
        return (
            "❌ Sin conexión al asistente IA. "
            "Verifica internet del servidor o usa comandos directos: /salud"
        )

    except APITimeoutError:
        return (
            "⏱ La consulta tardó demasiado. "
            "Intenta de nuevo o simplifica la pregunta."
        )

    except APIStatusError as e:
        if e.status_code in (503, 529):
            log.warning("Groq sobrecargado (%s) — reintentando en 6s", e.status_code)
            time.sleep(6)
            try:
                resp = _get_client().chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
                _register_usage(resp, endpoint="explain")
                return (resp.choices[0].message.content or "").strip()
            except Exception:
                pass
        log.warning("Groq APIStatusError %s: %s", e.status_code, e.message)
        return (
            f"⚠️ Error del asistente ({e.status_code}). "
            "Intenta de nuevo en unos segundos."
        )

    except Exception as e:
        log.warning("Groq error inesperado: %s — %s", type(e).__name__, e)
        return (
            "⚠️ No pude procesar la consulta. "
            "Usa /ayuda para ver los comandos disponibles."
        )


def explain(
    prompt: str,
    context: str = "",
    include_doc: bool = False,
    level: str = "tecnico",
) -> str:
    effective_dev = (
        level == "developer"
        and not technician_only_mode()
    )
    system = _SYSTEM_DEVELOPER if effective_dev else _SYSTEM_TECNICO
    max_tokens = 600 if effective_dev else 400

    messages: list[dict] = [{"role": "system", "content": system}]
    messages.append({"role": "system", "content": "Reglas de comportamiento:\n" + _behavior_rules_text()})

    appendix = _appendix_for_explain(level, prompt, include_doc)
    if appendix:
        if effective_dev:
            label = "Documentación desarrollador (CLAUDE/SISTEMA cuando estén montados)"
        else:
            label = "Manual de campo (operación / instalación / soporte)"
        messages.append({"role": "system", "content": f"{label}:\n{appendix}"})

    if context:
        messages.append({
            "role": "system",
            "content": f"Estado actual del sistema (datos reales):\n{context}",
        })

    messages.append({"role": "user", "content": prompt})

    out = _call_groq(messages, max_tokens)
    if not out:
        return (
            "No pude generar texto. Usa `/salud` o `/salud` para datos verificados del servidor."
        )
    return out


def chat(history: list[dict], level: str = "tecnico") -> str:
    import json
    from core import tools as _tools

    effective_dev = level == "developer" and not technician_only_mode()

    system = _SYSTEM_DEVELOPER if effective_dev else _SYSTEM_TECNICO
    max_tokens = 700 if effective_dev else 550

    messages: list[dict] = [{"role": "system", "content": system}]
    messages.append({"role": "system", "content": "Reglas de comportamiento:\n" + _behavior_rules_text()})

    if effective_dev:
        dq = ""
        try:
            for m in reversed(history):
                if m.get("role") == "user" and (m.get("content") or "").strip():
                    dq = str(m["content"]).strip()
                    break
        except Exception:
            dq = ""
        dev_ctx = get_doc_context_developer(dq)
        if dev_ctx:
            messages.append({
                "role": "system",
                "content": "Contexto documentación desarrollador:\n" + dev_ctx,
            })
        elif not technician_only_mode():
            messages.append({
                "role": "system",
                "content": "Contexto mínimo:\n" + _DEVELOPER_APPENDIX_FALLBACK,
            })

    messages.extend(history)

    def _do_create(msgs, use_tools: bool):
        kwargs: dict = dict(
            model="llama-3.3-70b-versatile",
            messages=msgs,
            max_tokens=max_tokens,
            temperature=0.1,
        )
        if use_tools:
            kwargs["tools"] = _tools.TOOLS
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
        return _get_client().chat.completions.create(**kwargs)

    def _fallback_explain(user_msg: str) -> str:
        return explain(user_msg, include_doc=True, level=level)

    budget_msg = _check_budget_before_call()
    if budget_msg:
        return budget_msg

    try:
        resp = _do_create(messages, use_tools=True)
    except RateLimitError:
        log.warning("Groq rate-limit en chat() — reintentando")
        time.sleep(4)
        try:
            resp = _do_create(messages, use_tools=True)
        except RateLimitError:
            from core import maintenance as _mnt

            _mnt.pause()
            return (
                "⏳ Cuota Groq agotada — el asistente entrará en pausa breve (~90s). "
                "Usa comandos directos: /salud · /alertas"
            )
        except Exception as e:
            log.warning("chat() error tras retry: %s", e)
            return "⚠️ No pude procesar la consulta. Usa /ayuda para ver comandos."
    except APIConnectionError:
        return "❌ Sin conexión al asistente IA. Usa comandos directos: /salud"
    except APITimeoutError:
        return "⏱ La consulta tardó demasiado. Intenta de nuevo o simplifica la pregunta."
    except APIStatusError as e:
        if e.status_code == 400 and "tool_use_failed" in str(getattr(e, "body", "") or ""):
            log.warning("tool_use_failed — fallback a explain()")
            user_msg = history[-1]["content"] if history else ""
            return _fallback_explain(user_msg)
        if e.status_code in (503, 529):
            log.warning("Groq sobrecargado (%s) en chat() — reintentando en 6s", e.status_code)
            time.sleep(6)
            try:
                resp = _do_create(messages, use_tools=True)
                _register_usage(resp, endpoint="chat")
                choice = resp.choices[0]
                if choice.finish_reason != "tool_calls":
                    return (choice.message.content or "").strip()
            except Exception:
                pass
        log.warning("chat() APIStatusError %s: %s", e.status_code, e.message)
        return f"⚠️ Error del asistente ({e.status_code}). Intenta de nuevo."
    except Exception as e:
        log.warning("chat() error inesperado: %s — %s", type(e).__name__, e)
        return "⚠️ No pude procesar la consulta. Usa /ayuda para ver comandos."

    _register_usage(resp, endpoint="chat")
    choice = resp.choices[0]

    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
        msg = choice.message

        assistant_msg: dict = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        }
        messages.append(assistant_msg)

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}") or {}
            except Exception:
                args = {}
            result = _tools.execute(tc.function.name, args)
            log.debug("tool %s → %s", tc.function.name, str(result)[:120])
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        try:
            resp2 = _do_create(messages, use_tools=False)
            _register_usage(resp2, endpoint="chat_tools")
            out = (resp2.choices[0].message.content or "").strip()
            if not out:
                return (
                    "Obtuve datos del sistema pero no pude redactar la respuesta. "
                    "Probá `/salud` o `/salud`."
                )
            return out
        except Exception as e:
            log.warning("chat() segunda llamada error: %s", e)
            return "⚠️ Obtuve los datos pero no pude formatear la respuesta. Intenta de nuevo."

    out = (choice.message.content or "").strip()
    if not out:
        return (
            "Sin respuesta del modelo. Usa `/salud`, `/salud` o reformulá la pregunta "
            "(una frase concreta)."
        )
    return out


def invalidate_cache() -> None:
    """Tras actualizar `.md` en disco (reload build)."""
    _DOC_CACHE.clear()
    log.info("Caché de documentación invalidada")
