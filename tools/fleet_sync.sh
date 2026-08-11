#!/usr/bin/env bash
# fleet_sync.sh — propaga el código de shomer-agent desde Ópera (maestro,
# ya commiteado y pusheado a GitHub) a todos los servidores de la flota,
# reinicia el bot, verifica que arrancó bien y revierte solo si no.
#
# Uso:
#   ./tools/fleet_sync.sh                # todos los hosts de tools/fleet_hosts.txt
#   ./tools/fleet_sync.sh shomer245       # solo ese host
#   ./tools/fleet_sync.sh host1 host2     # varios
#
# Por qué rsync y no `git pull` en el remoto: algunos labs (Tailscale
# aislado, ej. .245/.243) no tienen salida directa a GitHub. Ópera sí llega
# a ambos lados (GitHub y, por SSH/Tailscale, a cada servidor), así que
# empuja el árbol de trabajo completo — incluido .git, para que el remoto
# quede con el mismo historial que Ópera sin necesitar red propia hacia
# GitHub, y para que el rollback (más abajo) pueda usar `git reset --hard`.
#
# Seguridad:
#   - No usa --delete (mismo criterio que la sync de /opt/network_monitor
#     documentada en CLAUDE.md) — nunca borra algo que Ópera no tenga.
#   - Si el remoto tiene cambios sin commitear, se guardan con `git stash`
#     ANTES de sobrescribir — recuperables con `git stash list` /
#     `git stash pop` en ese servidor. Nunca se descartan en silencio.
#   - Tras reiniciar, se observa el contenedor ~15s: si el proceso entra en
#     crash-loop (RestartCount sube o deja de estar "running"), se revierte
#     solo con `git reset --hard` al commit que tenía antes + restart, y se
#     reporta ROLLBACK en vez de dejarlo caído.
#   - .env, data/ (devices.json, knowledge.db, conversations.db, etc.),
#     logs y __pycache__ quedan siempre excluidos — son específicos de
#     cada sitio, jamás se sobrescriben entre servidores.
#   - Cada corrida queda registrada en tools/fleet_sync.log (versión
#     anterior -> nueva por host, resultado) para saber de un vistazo qué
#     versión tiene cada sitio y cuándo se actualizó.
set -uo pipefail

REPO_DIR="/storage/shomer-agent"
SERVICE="shomer-agent.service"
CONTAINER="shomer-agent"
HOSTS_FILE="$REPO_DIR/tools/fleet_hosts.txt"
LOG_FILE="$REPO_DIR/tools/fleet_sync.log"

if [ "$#" -gt 0 ]; then
  hosts=("$@")
else
  mapfile -t hosts < <(grep -vE '^\s*(#|$)' "$HOSTS_FILE" 2>/dev/null)
fi

if [ "${#hosts[@]}" -eq 0 ]; then
  echo "Sin hosts que sincronizar (revisar $HOSTS_FILE)." >&2
  exit 1
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
local_version=$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo "?")
run_ts=$(date '+%Y-%m-%d %H:%M:%S %Z')
echo "== fleet_sync — $run_ts — maestro v$local_version ($local_head) =="
printf '%-12s | %-24s | %-10s | %-10s | %s\n' "HOST" "STASH" "RSYNC" "SALUD" "VERSION"
printf '%s\n' "--------------------------------------------------------------------------------"

for h in "${hosts[@]}"; do
  # 0) Versión/commit que tenía este host ANTES de tocar nada (para rollback y log).
  prev_head=$(ssh -o ConnectTimeout=10 -o BatchMode=yes "$h" \
    "cd '$REPO_DIR' 2>/dev/null && git rev-parse HEAD" 2>/dev/null)
  if [ -z "$prev_head" ]; then
    printf '%-12s | %-24s | %-10s | %-10s | %s\n' "$h" "SIN_CONEXION" "-" "-" "-"
    echo "$run_ts | $h | SIN_CONEXION" >> "$LOG_FILE"
    continue
  fi
  prev_short=${prev_head:0:7}

  # 1) Si hay cambios sin commitear en el remoto, guardarlos primero.
  stash_v=$(ssh -o ConnectTimeout=10 "$h" "
    cd '$REPO_DIR'
    if [ -n \"\$(git status --porcelain)\" ]; then
      ts=\$(date +%Y%m%d_%H%M%S)
      git stash push -u -m \"fleet_sync auto-stash \$ts\" >/dev/null 2>&1 \
        && echo \"guardado:\$ts\" || echo FALLO_STASH
    else
      echo ninguno
    fi
  " 2>/dev/null)
  stash_v="${stash_v:-ninguno}"

  # 2) Empujar el árbol de trabajo (incluye .git) por SSH.
  if rsync -az "${RSYNC_EXCLUDES[@]}" -e "ssh -o ConnectTimeout=15" \
      "$REPO_DIR/" "$h:$REPO_DIR/" >/tmp/fleet_rsync_"$h".log 2>&1; then
    rsync_v="ok"
  else
    rsync_v="FALLO"
    printf '%-12s | %-24s | %-10s | %-10s | %s\n' "$h" "$stash_v" "$rsync_v" "-" "-"
    echo "$run_ts | $h | $prev_short -> RSYNC_FALLO" >> "$LOG_FILE"
    continue
  fi

  # 3) Reiniciar y observar salud (~15s) antes de dar por buena la sync.
  ssh -o ConnectTimeout=10 "$h" "sudo systemctl restart '$SERVICE'" >/dev/null 2>&1
  sleep 5
  restarts_before=$(ssh -o ConnectTimeout=10 "$h" \
    "sudo docker inspect -f '{{.RestartCount}}' '$CONTAINER' 2>/dev/null" || echo 0)
  sleep 10
  check_out=$(ssh -o ConnectTimeout=10 "$h" "
    sudo docker inspect -f '{{.RestartCount}} {{.State.Status}}' '$CONTAINER' 2>/dev/null
    cd '$REPO_DIR' && git rev-parse --short HEAD
  " 2>/dev/null)
  restarts_after=$(awk 'NR==1{print $1}' <<<"$check_out")
  status_after=$(awk 'NR==1{print $2}' <<<"$check_out")
  new_head=$(awk 'NR==2{print $1}' <<<"$check_out")
  restarts_before=${restarts_before:-0}
  restarts_after=${restarts_after:-0}

  if [ "$status_after" = "running" ] && [ "${restarts_after:-0}" -le "${restarts_before:-0}" ]; then
    salud="ok"
    version_v="$new_head"
  else
    salud="ROLLBACK"
    ssh -o ConnectTimeout=10 "$h" "
      cd '$REPO_DIR' && git reset --hard '$prev_head' >/dev/null 2>&1
      sudo systemctl restart '$SERVICE' >/dev/null 2>&1
    " >/dev/null 2>&1
    sleep 5
    version_v="revertido:$prev_short"
  fi

  printf '%-12s | %-24s | %-10s | %-10s | %s\n' "$h" "$stash_v" "$rsync_v" "$salud" "$version_v"
  echo "$run_ts | $h | $prev_short -> $version_v | stash=$stash_v | salud=$salud" >> "$LOG_FILE"
done

echo ""
echo "Log completo: $LOG_FILE"
echo "Si algún host quedó con STASH=guardado:*, revisar con:"
echo "  ssh <host> 'cd $REPO_DIR && git stash list'"
echo "Si algún host quedó en ROLLBACK, revisar manualmente antes de reintentar:"
echo "  ssh <host> 'sudo docker logs $CONTAINER --tail 50'"
