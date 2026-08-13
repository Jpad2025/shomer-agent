# Changelog — Shomer Agent

Formato libre, una entrada por release. La versión activa vive en `VERSION`
(consultable también con `/version` en el bot). Fecha = cuando se desplegó
en Ópera (maestro), no cuando se escribió el código.

## 1.1.1 — 2026-08-13

- **Fix: "Nodo recuperado" repetido en equipos flapeando** (`core/monitor.py`
  `watch_guardian_nodes` + `core/incident_escalation.py`): el aviso de
  recuperación se mandaba en cada blip, sin pasar por la ventana de
  agregación que ya protege el lado de las caídas — un solo AP flapeando
  (OFC-COCINA `.113`) generó 44 de 54 mensajes Telegram en 24h. Nueva
  `incident_escalation.is_flapping(ip)` (true si el incidente ya acumuló
  2+ eventos en la ventana activa); `watch_guardian_nodes` la usa para
  suprimir recuperaciones repetidas — la primera se sigue avisando normal.

## 1.1.0 — 2026-08-10

- **Escalamiento de incidentes recurrentes** (`core/incident_escalation.py`):
  agrupa fallas repetidas del mismo equipo en una ventana de 1h en vez de
  mandar un mensaje por caída. Digest con 2 botones ("lo resuelvo ahora" /
  "próxima visita") + `/silenciar <ip> <duración>` a medida. Escala a
  Telegram del coordinador + correo (SMTP opcional) solo tras 24h sin
  respuesta — plazo largo porque el técnico de campo no vive en el sitio.
- **Resumen 08:00 enriquecido**: suma CPU/RAM/disco/estado de servicios en
  una línea, cerrando el pedido de un solo mensaje matutino.
- **`tools/fleet_sync.sh`**: propagación de código a toda la flota por
  rsync sobre SSH (no depende de que el sitio tenga salida a GitHub).
  Preserva cambios locales sin commitear con `git stash` antes de
  sobrescribir — nunca los descarta en silencio.
- **`tools/fleet_hosts.txt`** + **`/version`** + verificación post-deploy
  con rollback automático — ver README de `tools/`.

## 1.0.0 — línea base

Todo lo documentado en `CLAUDE.md` hasta la Sesión 69 (5 ago 2026): Guardian,
Hunter, Tracker, Protector, bot con 26+ monitores, digest VPN, alertas
compactas para flappers crónicos.
