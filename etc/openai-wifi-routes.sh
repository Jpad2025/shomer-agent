#!/bin/bash
# Lab .205: LAN gateway (.206) no tiene salida a internet.
# Estrategia: WiFi como default internet, enp2s0 solo para subredes LAN monitoreadas.
# Una regla, no listas de IPs cloud que rotan.

GW_WIFI="${OPENAI_WIFI_GW:-10.0.0.1}"
IF_WIFI="${OPENAI_WIFI_IF:-wlp3s0}"
GW_LAN="${LAN_GW:-192.168.1.206}"
IF_LAN="${LAN_IF:-enp2s0}"

if ! ip link show "$IF_WIFI" &>/dev/null; then
  echo "WiFi $IF_WIFI no disponible — sin cambios de ruta" >&2
  exit 0
fi
if ! ip -4 addr show dev "$IF_WIFI" | grep -q 'inet '; then
  echo "WiFi $IF_WIFI sin IP — sin cambios de ruta" >&2
  exit 0
fi

# 1. Quitar default estática de netplan (métrica 0) — bloquea salida WiFi
ip route del default via "$GW_LAN" dev "$IF_LAN" proto static 2>/dev/null || true

# 2. WiFi métrica baja (100) → única ruta default (Telegram, OpenAI, Groq)
ip route replace default via "$GW_WIFI" dev "$IF_WIFI" metric 100 2>/dev/null || true
# NO agregar default por LAN — .206 no tiene internet y rompe Telegram si WiFi parpadea
ip route del default via "$GW_LAN" dev "$IF_LAN" 2>/dev/null || true

# 2. Subredes LAN monitoreadas → siempre por enp2s0 (gestión de equipos)
ip route replace 192.168.1.0/24  via "$GW_LAN" dev "$IF_LAN" metric 100 2>/dev/null || true
ip route replace 192.168.10.0/24 via "$GW_LAN" dev "$IF_LAN" metric 100 2>/dev/null || true

# 3. Limpiar rutas específicas cloud que ya no son necesarias
for net in 149.154.0.0/16 91.108.0.0/16 172.66.0.0/16 104.18.0.0/16 104.16.0.0/13; do
  ip route del "$net" dev "$IF_WIFI" 2>/dev/null || true
done

echo "Rutas aplicadas: WiFi=default(100) LAN=solo subredes locales"
