#!/usr/bin/env bash
# fleet_sync.sh — propaga el código de shomer-agent desde Ópera (maestro,
# ya commiteado y pusheado a GitHub) a todos los servidores de la flota,
# y reinicia el bot en cada uno.
#
# Uso:
#   ./tools/fleet_sync.sh                # todos los hosts por defecto
#   ./tools/fleet_sync.sh shomer245       # solo ese host
#   ./tools/fleet_sync.sh host1 host2     # varios
#
# Por qué rsync y no `git pull` en el remoto: algunos labs (Tailscale
# aislado, ej. .245/.243) no tienen salida directa a GitHub. Ópera sí llega
# a ambos lados (GitHub y, por SSH/Tailscale, a cada servidor), así que
# empuja el árbol de trabajo completo — incluido .git, para que el remoto
# quede con el mismo HEAD que Ópera sin necesitar red propia hacia GitHub.
#
# Seguridad:
#   - No usa --delete (mismo criterio que la sync de /opt/network_monitor
#     documentada en CLAUDE.md) — nunca borra algo que Ópera no tenga.
#   - Si el remoto tiene cambios sin commitear, se guardan con `git stash`
#     ANTES de sobrescribir — recuperables con `git stash list` /
#     `git stash pop` en ese servidor. Nunca se descartan en silencio.
#   - .env, data/ (devices.json, knowledge.db, conversations.db, etc.),
#     logs y __pycache__ quedan siempre excluidos — son específicos de
#     cada sitio, jamás se sobrescriben entre servidores.
set -uo pipefail

REPO_DIR="/storage/shomer-agent"
SERVICE="shomer-agent.service"
DEFAULT_HOSTS=(shomer205 shomer245 shomer243)

if [ "$#" -gt 0 ]; then
  hosts=("$@")
else
  hosts=("${DEFAULT_HOSTS[@]}")
fi

RSYNC_EXCLUDES=(
  --exclude='.env' --exclude='.env.bak*'
  --exclude='data/'
  --exclude='*.db' --exclude='*.db-*' --exclude='*.sqlite*'
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='*.pyo'
  --exclude='*.log' --exclude='logs/' --exclude='.pytest_cache/'
  --exclude='venv/' --exclude='.venv/'
)

local_head=$(cd "$REPO_DIR" && git rev-parse --short HEAD)
echo "== fleet_sync — $(date '+%Y-%m-%d %H:%M:%S %Z') — maestro HEAD $local_head =="
printf '%-12s | %-24s | %-10s | %-14s | %s\n' "HOST" "STASH" "RSYNC" "HEAD_REMOTO" "SERVICIO"
printf '%s\n' "--------------------------------------------------------------------------------"

for h in "${hosts[@]}"; do
  # 1) Si hay cambios sin commitear en el remoto, guardarlos primero.
  stash_v=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$h" "
    cd '$REPO_DIR' 2>/dev/null || { echo sin_repo; exit 0; }
    if [ -n \"\$(git status --porcelain)\" ]; then
      ts=\$(date +%Y%m%d_%H%M%S)
      git stash push -u -m \"fleet_sync auto-stash \$ts\" >/dev/null 2>&1 \
        && echo \"guardado:\$ts\" || echo FALLO_STASH
    else
      echo ninguno
    fi
  " 2>/dev/null)
  stash_v="${stash_v:-SIN_CONEXION}"

  if [ "$stash_v" = "sin_repo" ] || [ "$stash_v" = "SIN_CONEXION" ]; then
    printf '%-12s | %-24s | %-10s | %-14s | %s\n' "$h" "$stash_v" "-" "-" "-"
    continue
  fi

  # 2) Empujar el árbol de trabajo (incluye .git) por SSH.
  if rsync -az "${RSYNC_EXCLUDES[@]}" -e "ssh -o ConnectTimeout=15" \
      "$REPO_DIR/" "$h:$REPO_DIR/" >/tmp/fleet_rsync_"$h".log 2>&1; then
    rsync_v="ok"
  else
    rsync_v="FALLO"
  fi

  # 3) Reiniciar el bot y confirmar HEAD remoto.
  if [ "$rsync_v" = "ok" ]; then
    remote_out=$(ssh -o ConnectTimeout=10 "$h" "
      cd '$REPO_DIR' && git rev-parse --short HEAD
      sudo systemctl restart '$SERVICE' >/dev/null 2>&1
      sleep 3
      sudo systemctl is-active '$SERVICE' 2>/dev/null || echo '?'
    " 2>/dev/null)
    remote_head=$(sed -n '1p' <<<"$remote_out")
    svc_v=$(sed -n '2p' <<<"$remote_out")
  else
    remote_head="-"; svc_v="-"
  fi

  printf '%-12s | %-24s | %-10s | %-14s | %s\n' "$h" "$stash_v" "$rsync_v" "$remote_head" "$svc_v"
done

echo ""
echo "Log de rsync por host en /tmp/fleet_rsync_<host>.log"
echo "Si algún host quedó con STASH=guardado:*, revisar con:"
echo "  ssh <host> 'cd $REPO_DIR && git stash list'"
