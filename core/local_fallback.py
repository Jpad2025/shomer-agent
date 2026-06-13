"""Degradación local sin IA.

build_local_digest responde desde el snapshot (Redis + psutil + SQLite)
cuando OpenAI y Groq no están disponibles.

Formato del snapshot = dict de llm_router._local_context_struct():
  online         list[str]   IPs de nodos Guardian online
  offline        list[str]   IPs de nodos Guardian offline/no-internet
  wan            str|None    "online"/"offline"/"up"/"down"/None
  maintenance    bool
  cpu            float|None
  ram            float|None
  disk           float|None
  blocked_ips    int
  failed_backups list[str]   nombres de equipos con last_status='failed'
"""
from __future__ import annotations


def build_local_digest(snapshot: dict, question: str = "") -> str:
    """Responde en HTML (parse_mode=HTML) sin llamar ninguna API cloud."""
    q = (question or "").lower()

    online         = snapshot.get("online", [])
    offline        = snapshot.get("offline", [])
    wan            = snapshot.get("wan")
    cpu            = snapshot.get("cpu")
    ram            = snapshot.get("ram")
    disk           = snapshot.get("disk")
    blocked_ips    = snapshot.get("blocked_ips", 0)
    failed_backups = snapshot.get("failed_backups", [])
    maintenance    = snapshot.get("maintenance", False)

    wan_ok = (not wan) or wan.lower() in ("online", "up", "ok")

    bullets: list[str] = []
    bullets.append(f"WAN: {'`ok`' if wan_ok else '`caída`'}")
    if offline:
        nodes_str = " · ".join(f"`{n}`" for n in offline)
        bullets.append(f"Nodos offline ({len(offline)}): {nodes_str}")
    else:
        bullets.append(f"Nodos online: {len(online)}")
    if disk is not None:
        bullets.append(f"Disco: `{disk:.0f}%`")
    if cpu is not None and ram is not None:
        bullets.append(f"CPU `{cpu:.0f}%` / RAM `{ram:.0f}%`")
    bullets.append(f"IPs bloqueadas: {blocked_ips}")
    if failed_backups:
        bullets.append(f"Backups fallidos: {len(failed_backups)} ({', '.join(failed_backups)})")
    if maintenance:
        bullets.append("⚠️ Modo mantenimiento ACTIVO")

    if any(k in q for k in ("servici", "internet", "caíd", "caid", "conexi", "red", "wan")):
        if not wan_ok:
            head = f"DIAGNÓSTICO: WAN caída, {len(offline)} nodo(s) offline."
        elif offline:
            head = f"DIAGNÓSTICO: WAN ok pero {len(offline)} nodo(s) offline."
        else:
            head = "DIAGNÓSTICO: WAN ok, todos los nodos online."
    elif any(k in q for k in ("backup", "respaldo", "protector")):
        head = (f"DIAGNÓSTICO: {len(failed_backups)} backup(s) fallido(s)."
                if failed_backups else "DIAGNÓSTICO: sin fallos de backup.")
    elif any(k in q for k in ("ataque", "segur", "bloque", "hunter", "intrus", "ip")):
        head = f"DIAGNÓSTICO: Hunter tiene {blocked_ips} IP(s) contenida(s) — red protegida."
    elif any(k in q for k in ("disco", "disk", "espacio")):
        head = f"DIAGNÓSTICO: Disco al {f'{disk:.0f}%' if disk is not None else '?'}."
    elif any(k in q for k in ("cpu", "ram", "memoria", "recurso", "carga")):
        head = (f"DIAGNÓSTICO: CPU {f'{cpu:.0f}%' if cpu is not None else '?'}, "
                f"RAM {f'{ram:.0f}%' if ram is not None else '?'}.")
    else:
        head = "Estado actual del sistema."

    body = "\n".join(f"• {b}" for b in bullets)
    return (
        f"⚠️ *Modo local* — IA sin conexión a internet.\n\n"
        f"*{head}*\n{body}\n\n"
        "_Comandos: /salud · /alertas · /equipos · /diagnostico <ip>_"
    )
