# Shomer Sentinel — Guía del Técnico de Campo

**Para quién es este documento:** Técnico de campo que instala y opera el sistema Shomer Sentinel.
No contiene información interna de código ni arquitectura del producto.
Los valores específicos de cada instalación (IPs, comunidades SNMP, claves, tokens) te los entrega USB Ingeniería antes de cada visita.

**Versión:** mayo 2026

---

## ¿Qué es Shomer?

Un servidor físico (mini PC) que se instala en la red del cliente. Desde el navegador de tu laptop controlas todo.

| Módulo en el panel | Para qué sirve |
|--------------------|----------------|
| **Guardian** | Vigila que los APs y routers estén encendidos y con internet. Los reinicia automáticamente si detecta caída sostenida. |
| **Inframonitor** | Vigila switches, routers, firewalls, servidores y cualquier equipo con IP. Con SNMP activo muestra estado de puertos, tráfico y errores. Solo monitorea — no reinicia. |
| **Tracker** | Inventario de todos los equipos de la red: IP, MAC, tipo, fabricante. |
| **Hunter** | Detecta ataques y tráfico sospechoso. Permite bloquear IPs desde el panel. |
| **Protector** | Backups automáticos de equipos del cliente (Windows, Mac, Linux) a disco local y opcionalmente a la nube. |

El panel se abre desde cualquier laptop en la misma red del cliente:
```
https://IP-DEL-SHOMER
```
Acepta el aviso de certificado del navegador — es normal en redes privadas.

---

# ANTES DE SALIR DE VIAJE — Checklist del técnico

1. Completar **Hoja de datos del sitio** (PARTE 6 de este documento) — imprimir o PDF en tablet.
2. Portátil con: **Winbox**, **Netinstall**, **PuTTY**, **TinyPXE Server** (no Tftpd64).
3. Firmware en carpeta local (confirmar versión con ingeniería):
   - `routeros-mmips-6.49.19.npk`
   - `openwrt-23.05.0-rc3-...-initramfs-kernel.bin` (solo **rc3** netbooteable en hEX S)
   - `openwrt-23.05.5-...-squashfs-sysupgrade.bin`
4. Cableado: crimpar/etiquetar; verificar acceso al switch del cliente.

---

# PARTE 1 — INSTALACIÓN DESDE CERO

## Paso 1 — Verificar hardware antes de encender

El mini PC necesita **mínimo dos tarjetas de red (NICs)**. Conecta teclado + monitor al mini PC y ejecuta:

```bash
ip link show
```

Debes ver al menos dos interfaces además del loopback (`lo`). Ejemplo típico:
- `enp2s0` — NIC de gestión (cable al switch del cliente)
- `enp4s0` — NIC espejo (cable al puerto SPAN del switch)

⚠️ Si ves solo una NIC, detente y avisa a ingeniería antes de continuar.

---

## Paso 2 — Cableado físico

| Cable | Dónde va |
|-------|----------|
| **NIC de gestión** (`enp2s0` o similar) | Puerto normal del switch del cliente — misma red donde está tu laptop |
| **NIC espejo** (`enp4s0` o similar) | Puerto SPAN / mirror del switch — recibe copia del tráfico para Hunter |

**Regla importante sobre la NIC espejo:**
La NIC espejo **no lleva IP**. Solo "escucha" tráfico. No intentes asignarle una dirección — si lo haces puede causar conflictos de red que hacen que Guardian no vea los equipos correctamente.

Si el cliente no tiene puerto SPAN todavía: conecta solo la NIC de gestión y continúa. La NIC espejo se puede agregar después sin reiniciar el proyecto.

---

## Paso 2B — Instalar el firewall MikroTik (OpenWrt)

USB Ingeniería entrega junto al mini PC un **router MikroTik** (modelo hEX S o similar) ya flasheado con OpenWrt. Este equipo hace de firewall perimetral del cliente y es el que Hunter va a controlar para bloquear IPs.

**Viene preconfigurado con:**
- OpenWrt instalado y estable
- Llave SSH del Shomer cargada (Hunter puede conectarse sin contraseña manual)
- Regla TEE activa: copia el tráfico de la LAN hacia la NIC espejo del Shomer (así Suricata ve el tráfico real)
- WireGuard VPN listo para que el técnico acceda remotamente

**Topología completa del sitio instalado:**

```
                    INTERNET
                        │
                  [ISP / Modem]
                        │
             ┌──────────────────────┐
             │   MikroTik (OpenWrt) │
             │   WAN ◄── ISP        │  ← firewall perimetral
             │   LAN ──► switch     │  ← Hunter lo controla por SSH
             └──────────┬───────────┘
                        │
             ┌──────────────────────┐
             │   Switch principal   │
             │   del cliente        │
             └──┬───────┬───────┬───┘
                │       │       │
          [Shomer]   [AP-1]  [AP-2]  [PCs del cliente...]
          mini PC
          ├── NIC gestión (enp2s0)   ← IP fija del Shomer, panel web
          └── NIC espejo (enp4s0)    ← SIN IP, recibe copia del tráfico
                                        para que Suricata lo analice
```

**Diagrama de conexión inicial (antes del wizard):**

```
                    ┌─────────────────────┐
  Tu laptop ────────► NIC gestión Shomer  │
  (misma subred     │   (enp2s0)          │
   que IP fábrica)  └─────────────────────┘

  Navegador → http://IP-DE-FÁBRICA/setup
```

En esta etapa el Shomer NO está en la red del cliente todavía. La conexión es directa o a través de un switch de trabajo temporal.

**Lo que hace el técnico en sitio:**

1. Conecta el cable del ISP (o del router del ISP) al **puerto WAN** del MikroTik.
2. Conecta un cable del **puerto LAN** del MikroTik al switch principal del cliente.
3. Espera 1 minuto — el MikroTik toma IP del ISP por DHCP. Si el ISP requiere IP estática, ingeniería te entrega los datos en la hoja de datos del sitio.
4. Conecta tu laptop al switch del cliente y abre el panel del MikroTik:
   ```
   http://IP-LAN-DEL-MIKROTIK
   ```
   La IP LAN del MikroTik viene en la hoja de datos. Si no la tienes, ingeniería te la confirma.
5. En el panel de OpenWrt → **Status → Overview** → verifica que la sección WAN muestra una IP del ISP activa y que hay conectividad a internet.
6. **Anota la IP LAN del MikroTik** — la necesitas en el Paso 9 para configurar Hunter.

**Si el ISP da IP dinámica (cambia periódicamente):**

1. En OpenWrt → **Services → Dynamic DNS** → habilitar.
2. Ingresar las credenciales del servicio DDNS que entrega USB Ingeniería.
3. Anotar el nombre de dominio DDNS asignado — es la dirección que el técnico usará para conectarse por VPN cuando la IP del ISP cambie.

**Si el MikroTik queda detrás del router del ISP (doble NAT):**

```
Internet → [Router del ISP] → [MikroTik] → switch → LAN
```

En este caso el router del ISP debe reenviar el puerto VPN UDP hacia la IP LAN del MikroTik. Ingeniería indica el número de puerto exacto para ese sitio. Sin este reenvío, la VPN remota no funciona desde internet.

---

## Paso 3 — Primer acceso con IP de fábrica

El mini PC Shomer tiene una **IP de fábrica fija** asignada por USB Ingeniería para la primera configuración. Viene en la hoja de datos del envío.

**Si no tienes la hoja de datos:** conecta un monitor y teclado al mini PC, inicia sesión, y ejecuta:
```bash
ip addr show
```
La IP de fábrica de la NIC de gestión aparece en esa lista.

**Pasos de primer acceso:**

1. Configura tu laptop con una IP en el mismo rango que la IP de fábrica (misma subred).
2. Conecta un cable de red directo entre tu laptop y la **NIC de gestión** del Shomer (o a través del switch de fábrica si ya está conectado).
3. Abre el navegador:
   ```
   http://IP-DE-FÁBRICA/setup
   ```
4. Acepta el aviso de certificado si el navegador lo pide.
5. Login:
   - Usuario: `admin`
   - Contraseña: la que entrega ingeniería (cambia por instalación)

**Paso adicional — NIC espejo (Suricata):**

Después del primer acceso y antes de pasar al Paso 4, ejecuta este comando desde el terminal del Shomer para que la NIC espejo funcione correctamente tras cada reinicio:

```bash
sudo tee /etc/sysctl.d/99-shomer-suricata.conf << 'EOF'
net.ipv4.conf.enp4s0.rp_filter=0
net.ipv4.conf.all.rp_filter=0
EOF
sudo sysctl --system
```

Si el nombre de la NIC espejo es diferente a `enp4s0` (lo verificaste en el Paso 1), reemplaza `enp4s0` por el nombre correcto en ambas líneas.

Ingeniería puede confirmar que este paso ya está hecho en la imagen de fábrica — en ese caso lo omites.

---

## Paso 4 — Wizard de red del cliente

En el panel, ve a **Configuración → Setup** y completa:

| Campo | Qué poner |
|-------|-----------|
| **Nombre del sitio** | Nombre descriptivo del cliente (ej. `Hotel Plaza Bogotá`). Aparece en el panel, en el bot y en los Telegram. Úsalo exactamente como el cliente quiere que se identifique su instalación. |
| **IP del Shomer** | La IP fija que el cliente asigna al Shomer en su LAN |
| **Gateway** | El router/gateway principal de la red del cliente — normalmente la IP LAN del MikroTik |
| **Máscara / Prefijo** | El prefijo de la red del cliente (ej. `/24`) |
| **NIC de gestión** | La interfaz que conectaste al switch (ej. `enp2s0`) |
| **NIC espejo** | La interfaz que conectaste al SPAN — **sin IP, solo nombre** |
| **Zona horaria** | La zona horaria del sitio del cliente. Ejemplos: `America/Bogota`, `America/Lima`, `America/Mexico_City`, `America/New_York`. Elige la correcta para que los backups, alertas y logs muestren la hora local del cliente y no UTC. |

**¿Por qué es importante la zona horaria?**
Si queda en UTC, el scheduler de backups y las alertas de Telegram muestran hora incorrecta. Un backup programado a las 2am puede ejecutarse a las 7am hora del cliente — o al revés. Configurarla bien desde el inicio evita confusión en producción.

**¿Por qué es importante el nombre del sitio?**
Este nombre aparece en todos los mensajes del bot Telegram y en el encabezado del panel. Cuando el técnico gestiona varios clientes desde el mismo chat de Telegram, el nombre permite saber de cuál sitio es cada alerta de un solo vistazo.

Después de guardar, el Shomer se reinicia con la IP definitiva del cliente. Reconecta tu laptop y entra a:
```
https://IP-DEFINITIVA-DEL-SHOMER
```

⚠️ Guarda esta IP — es la dirección permanente de este Shomer en este sitio.

---

## Paso 5 — Verificar que todos los servicios están activos

Entra al panel → **Estado del sistema**.

Esta pantalla es el diagnóstico general del appliance. Lo que vas a ver:

| Sección en la pantalla | Qué significa |
|------------------------|---------------|
| **Servicios** | Tarjetas con el estado de cada motor interno. Verde = activo y funcionando. Rojo = caído. Amarillo = degradado o en advertencia. |
| **CPU / RAM** | Gauges con el uso actual del procesador y la memoria. Normal en reposo: CPU bajo 20%, RAM según los módulos activos. Si CPU está constantemente arriba de 85% sin razón aparente, avisar a ingeniería. |
| **Disco** | Porcentaje de disco usado. A 80% el bot empieza a avisar. A 85% limpia automáticamente. A 92% limpieza agresiva y alerta crítica. |
| **Interfaces de red** | Estado UP/DOWN de cada tarjeta de red. La NIC de gestión debe aparecer UP siempre. La NIC espejo debe aparecer UP si está conectada al SPAN. |
| **WAN del servidor** | Si el Shomer mismo tiene salida a internet. Si está en rojo, Telegram y las actualizaciones no van a funcionar. |
| **Temperatura** | Temperatura del procesador. Normal hasta 70°C. Arriba de 80°C sostenido puede indicar ventilación insuficiente en el rack. |

**¿Qué debe verse activo en una instalación normal?**

```
✅ shomer-guardian    ← motor principal (Guardian + Hunter)
✅ shomer-tools       ← Tracker + Protector
✅ nginx              ← proxy HTTPS del panel web
✅ redis-server       ← memoria de estado Guardian
✅ suricata           ← solo si tiene NIC espejo y Hunter activo
```

Si algún servicio aparece en rojo: anota el nombre exacto y avisa a ingeniería. No intentes reiniciarlo manualmente a menos que ingeniería te lo indique.

El bot de Telegram con `/salud` muestra la misma información más un resumen con IA de qué está bien y qué requiere atención.

---

## Paso 5B — Revisar módulos habilitados

En el panel → **Configuración → Módulos** (o en el wizard de setup).

Aquí puedes ver qué módulos están activos para este cliente. Cada módulo tiene un toggle (interruptor):

| Módulo | Cuándo activarlo |
|--------|-----------------|
| **Guardian** | Siempre — es el núcleo del sistema |
| **Tracker** | Cuando el cliente quiere inventario de red |
| **Hunter** | Solo si hay NIC espejo conectada al SPAN del switch y Suricata está corriendo |
| **Protector** | Solo si el cliente contrata el servicio de backups |

**Un módulo desactivado no aparece en el menú lateral del panel.** Si un módulo no aparece y debería estar, verifica aquí primero antes de reportar un problema.

**¿Quién activa o desactiva los módulos?**
El técnico puede verlos. Cambiar un módulo (activar/desactivar) requiere acceso de administrador en el panel. En campo, coordina con ingeniería antes de deshabilitar un módulo — puede afectar configuraciones existentes del cliente.

---

## Paso 6 — Seguridad básica (OBLIGATORIO antes de entregar)

1. **Cambiar contraseña del admin** en el panel: Configuración → Usuarios → cambiar contraseña.
2. **Rotar el JWT Secret**: el desarrollador lo hace desde acceso SSH — no lo hagas tú solo, avisa que ya terminaste los pasos anteriores para que lo haga.
3. **Verificar el firewall del servidor**: solo deben estar abiertos los puertos de acceso al panel y SSH. Ingeniería lo confirma.

---

## Paso 7 — Configurar Telegram

En el panel → **Guardian → Configuración**:

1. Pega el **token del bot** que te entrega USB Ingeniería para este sitio.
2. Pega el **Chat ID** del grupo o canal donde van las alertas.
3. Pulsa **Enviar mensaje de prueba** — debe llegar en menos de 10 segundos.

Si no llega: verifica conexión a internet del Shomer. Si hay internet y sigue sin llegar, avisa a ingeniería.

---

## Paso 8 — Agregar nodos a Guardian

En el panel → **Guardian → Dispositivos → Agregar**:

Por cada AP o router a monitorear:

| Campo | Qué poner |
|-------|-----------|
| **Nombre** | Nombre descriptivo (ej. `AP-Piso2`, `Router-Gerencia`) |
| **IP** | La IP del equipo en la red del cliente |
| **Método de reboot** | `ssh` para la mayoría; `snmp` para APs TP-Link EAP |
| **Usuario SSH** | El usuario del equipo (normalmente `root`) |
| **Contraseña SSH** | La contraseña SSH del equipo |

Después de agregar, pulsa **Verificar conexión** — debe aparecer verde.

### Si el equipo es un AP TP-Link EAP (EAP225, EAP610, etc.)

Estos APs usan **SNMP** para el reboot en lugar de SSH. Antes de agregarlos en Guardian, configura SNMP en el panel web del AP:

1. Entra al panel web del EAP (o al Omada Controller si lo tienen).
2. Ve a **Management → SNMP**.
3. Activa SNMP v2c.
4. Configura:
   - **Comunidad de lectura (GET):** la que te entrega USB Ingeniería para este sitio
   - **Comunidad de escritura (SET):** la que te entrega USB Ingeniería para este sitio (es diferente a la de lectura)
   - **IP permitida:** solo la IP del Shomer — nunca dejar abierto a todas las IPs
5. Nunca usar `public` ni `private` en producción.

En Guardian, al agregar el EAP:
- Método de reboot: `snmp`
- Comunidad SET: la misma que configuraste en el AP
- Desactivar: SSH ping WAN, DNS check, HTTP check (el EAP no soporta eso)
- Activar: solo ICMP

### Si el equipo es GL.iNet o OpenWrt

Estos requieren SSH con llave. Pasos adicionales que hace ingeniería antes de entregarte el equipo:
1. Instalar `openssh-server` en el GL.iNet.
2. Cargar la llave pública del Shomer en el equipo.
3. Probar reboot manual desde el panel antes de confiar en el automático.

### Si el equipo es Ubiquiti (UniFi, airMAX)

Misma configuración que GL.iNet pero suele ser más directo — SSH con root funciona sin pasos adicionales.

---

## Paso 9 — Configurar Hunter

En el panel → **Hunter → Configuración de Red**:

| Campo | Qué poner |
|-------|-----------|
| **IP del Firewall** | La IP del OpenWrt/MikroTik que Shomer va a controlar |
| **Usuario SSH** | `root` (o el usuario SSH del router del cliente) |
| **Contraseña SSH** | La contraseña SSH del router |
| **Puerto SSH** | `22` (o el que use el cliente si lo cambiaron) |
| **Timeout SSH** | `10` segundos (subir a 15–20 si la red es lenta) |
| **Subredes internas** | La red del cliente, ej. `10.10.0.0/24` — los equipos de esta subred no se autobloquean |

**Lista de excepciones permanentes** — agregar siempre:
- IP del gateway del cliente
- IP del propio Shomer
- IP de Wazuh (si aplica)

**Primera semana en producción:** deja el auto-bloqueo en modo manual o en solo amenazas Críticas (severidad 1). Después de conocer el ruido del sitio, se puede afinar.

---

## Paso 10 — Verificar Suricata (solo si tiene NIC espejo activa)

En el panel → **Hunter → Estado del pipeline**:

- El pipeline debe aparecer como `Activo`.
- Si aparece `Sin eventos`: revisar que el puerto SPAN del switch está enviando tráfico a la NIC espejo.

**Prueba básica:** haz ping desde tu laptop a cualquier equipo de la red. Deben aparecer alertas de prueba en Hunter en menos de 1 minuto.

---

## Paso 11 — Tracker: primer inventario

En el panel → **Tracker → Inventario → Quick Scan**:

1. Confirma que el rango de red es correcto (ej. `10.10.0.0/24`).
2. Inicia el scan — tarda entre 2 y 5 minutos.
3. Verifica que aparecen los equipos principales: gateway, switches, APs, PCs.
4. Exporta Excel como respaldo inicial: **Exportar → Excel global**.

---

## Paso 12 — Checklist de aprobación antes de cerrar la instalación

Marca cada punto antes de entregar el sitio:

```
☐ Los 4 módulos (Guardian, Tracker, Hunter, Protector) visibles y sin errores en el panel
☐ Al menos un AP en estado verde (online) en Guardian
☐ Telegram recibe alertas de prueba — mensaje de prueba llegó al chat
☐ Hunter muestra alertas del tráfico del sitio (al menos la prueba de ping)
☐ Tracker tiene equipos reales del cliente en la lista
☐ Contraseña admin cambiada desde la contraseña de fábrica
☐ JWT rotado (lo hace ingeniería — confirmar que se hizo)
☐ NIC espejo sin IP configurada (verificar con ip link show — no debe tener dirección)
☐ Los servicios del Shomer siguen activos después de reiniciar el equipo
```

📸 Toma una foto del panel con los 4 módulos activos y envíala al desarrollador.

---

# PARTE 2 — OPERACIÓN DIARIA

## Estados de Guardian

| Color / Estado | Qué significa | Qué hacer |
|----------------|---------------|-----------|
| 🟢 **Online** | El equipo está bien, con internet | Nada |
| 🔴 **Offline** | No responde desde la LAN | Verificar cable, PoE y energía del equipo |
| 🟠 **No-internet** | Equipo responde en LAN pero sin salida a internet | Verificar router/ISP del cliente |
| 🟡 **Degraded** | Calidad de conexión baja, funciona parcial | Monitorear — si pasa a rojo, Guardian actuará |

---

## Cuándo reinicia Guardian automáticamente

Guardian reinicia un AP solo si se cumplen **todas** estas condiciones:
1. El equipo lleva en rojo o sin internet **3 ciclos consecutivos** (aproximadamente 5 minutos)
2. No se reinició en las últimas **6 horas** (cooldown)
3. El servidor Shomer tiene internet en ese momento
4. No está en modo mantenimiento

Si el AP se reinicia solo: es normal, Guardian hizo su trabajo. Llega aviso por Telegram.

**Modo degradado (amarillo):** Guardian **no reinicia** en este estado. Es una señal de advertencia, no de caída. Puede ser interferencia WiFi, cable malo, o muchos clientes conectados.

---

## Modo mantenimiento — SIEMPRE usar cuando trabajas en el sitio

Antes de desconectar cables, hacer cambios en el switch, o cualquier trabajo que vaya a bajar equipos:

**Activar mantenimiento:** `/modo on` o `/mantenimiento` en el bot → botón de activar.  
O en el panel: **Guardian** → botón **🔧 Activar Mantenimiento**.

**Telegram:** aviso al activar y desactivar (`MANTENIMIENTO GLOBAL` + usuario). Desde jun 2026.

Mientras mantenimiento está activo, Guardian no reinicia nada automáticamente.

**Al terminar:** desactivar mantenimiento. Mismo comando o botón.

---

## Problemas frecuentes y qué hacer

### El panel no carga
1. Verificar que el Shomer está encendido (luz indicadora).
2. Verificar que tu laptop está en la misma red que el Shomer.
3. Intentar con IP directa: `https://IP-DEL-SHOMER`.
4. Si sigue sin cargar: reiniciar el Shomer físicamente (botón de encendido).
5. Si después de reiniciar no carga en 3 minutos: escalar a ingeniería.

### Un AP aparece rojo pero físicamente está encendido
1. Verificar el cable de red del AP — que llegue al switch correcto.
2. Verificar que el AP tiene la misma IP que Guardian espera (puede haber cambiado por DHCP).
3. Verificar que el AP tiene energía (PoE del switch activo).
4. Desde Guardian → ese nodo → **Verificar conexión**.
5. Si sigue rojo y el AP claramente está funcionando: revisar si hay cambio de VLAN o subnet en el switch.

### Guardian no puede reiniciar un AP
- Verificar que las credenciales SSH (o SNMP para EAP) están correctas en el panel.
- Para APs OpenWrt/GL.iNet: la llave SSH del Shomer debe estar en el AP — esto lo configura ingeniería.
- Para EAPs TP-Link: verificar que SNMP está activo en el panel web del AP y que la IP del Shomer está en la lista permitida.

### No llegan alertas de Telegram
1. Verificar que el Shomer tiene internet (Guardian → Estado del servidor).
2. Probar desde el panel: Guardian → Configuración → **Enviar mensaje de prueba**.
3. Verificar que el bot no fue bloqueado en el grupo de Telegram.
4. Si nada funciona: el token puede estar caducado — avisar a ingeniería para regenerar.

### Hunter bloqueó una IP que no debería
1. En el panel → Hunter → IPs bloqueadas → buscar la IP.
2. Botón **Desbloquear**.
3. Si fue un error recurrente: agregar esa IP a la lista de excepciones permanentes.
4. Si el bloqueo lo hizo Wazuh: la IP aparece como "bloqueada por Wazuh" — igualmente se desbloquea desde el panel.

### El disco del Shomer está lleno
El bot de Telegram avisa antes de que sea un problema. Si llega una alerta de disco:
1. El bot intenta limpieza automática de archivos temporales.
2. Si no fue suficiente: revisar `/salud` y escalar a ingeniería si persiste.
3. Si el disco sigue lleno: escalar a ingeniería — puede haber logs muy grandes o backups acumulados.

---

## Qué escalar a ingeniería (no intentar solo)

| Situación | Por qué no hacerlo solo |
|-----------|------------------------|
| Cambiar la IP del Shomer en la red | Puede dejar el panel inaccesible si se hace mal |
| Modificar archivos de configuración del servidor | Requiere conocer la arquitectura interna |
| Cambiar el token JWT (llave de sesiones) | Cierra la sesión de todos los usuarios activos |
| Instalar o actualizar módulos del sistema | Puede romper compatibilidades |
| Restaurar backup completo del sistema | Protocolo específico que puede perder datos si se hace en orden incorrecto |
| Cambiar credenciales SSH del propio Shomer | Puede dejar sin acceso a ingeniería |

---

# PARTE 3 — MÓDULOS EN DETALLE

## Guardian — agregar un AP TP-Link EAP paso a paso

1. Entra al panel web del EAP (o al Omada Controller).
2. Activa SNMP v2c con las comunidades que te entrega ingeniería.
3. Pon solo la IP del Shomer como IP permitida para SNMP.
4. En el panel Shomer → Guardian → Dispositivos → Agregar:
   - Nombre descriptivo
   - IP del EAP
   - Método reboot: `snmp`
   - Comunidad SET: la que configuraste
   - Activar solo: ICMP (desactivar SSH, DNS, HTTP)
5. Pulsa Verificar — debe aparecer verde.
6. Prueba reboot manual desde el panel en horario de mantenimiento.

## Usuario de servicio Shomer — crear en TODOS los equipos del cliente

Antes de usar Tracker (inventario) y Protector (backups), necesitas crear un **usuario de servicio** en cada equipo del cliente. Este usuario es el que el Shomer usa para conectarse, recopilar información del equipo y hacer los backups.

**Antes de empezar:** USB Ingeniería te entrega dos datos para esta instalación:

| Dato | Ejemplo (el tuyo puede ser diferente) |
|------|---------------------------------------|
| **NOMBRE_USUARIO** | `shomer_inv` |
| **CONTRASEÑA** | la que entrega ingeniería |

Usa exactamente ese nombre y contraseña en todos los equipos del mismo cliente. Si los cambias en un equipo, luego tienes que actualizar las credenciales en el panel del Shomer también.

---

### ¿Tiene el cliente Active Directory (dominio)?

Pregúntale al responsable de IT del cliente:
- "¿Los equipos están en un dominio de Windows?" → Si dice **sí**: usa la sección **CON Active Directory**
- Si dice **no** o no sabe: usa la sección **SIN Active Directory**

Si el cliente ya tiene un usuario administrador de IT activo y te lo comparte: puedes usarlo directamente, no necesitas crear uno nuevo. Solo cárgalo en el panel del Shomer.

---

### OPCIÓN A — Windows SIN Active Directory (equipos independientes)

Hay que hacer esto **en cada PC Windows** del cliente, uno por uno.

**Cómo abrir PowerShell como Administrador:**
1. Presiona la tecla Windows
2. Escribe `PowerShell`
3. Haz clic derecho sobre el resultado → **Ejecutar como administrador**
4. Si aparece un cuadro de confirmación (Control de cuentas de usuario) → clic en **Sí**

**Comando 1 — Crear el usuario** *(escríbelo exactamente, reemplazando solo NOMBRE_USUARIO y CONTRASEÑA)*:
```
net user NOMBRE_USUARIO CONTRASEÑA /add /passwordchg:no /expires:never
```
Resultado esperado: `Se ha completado el comando correctamente.`

**Comando 2 — Darle permisos de administrador**:
```
net localgroup Administrators NOMBRE_USUARIO /add
```
Resultado esperado: `Se ha completado el comando correctamente.`

**Comando 3 — Permitir acceso remoto** *(para que Tracker pueda leer info del equipo)*:
```
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v LocalAccountTokenFilterPolicy /t REG_DWORD /d 1 /f
```
Resultado esperado: `La operación se completó correctamente.`

**Comando 4 — Abrir el firewall para inventario**:
```
netsh advfirewall firewall set rule group="Windows Management Instrumentation (WMI)" new enable=yes
```
Resultado esperado: `Se actualizaron 3 reglas.` *(el número puede variar)*

**Comando 5 — Verificar que el servicio de inventario está activo**:
```
sc query Winmgmt
```
Resultado esperado: debe aparecer `STATE : 4  RUNNING`
Si dice `STOPPED`: ejecuta `sc start Winmgmt` y espera 10 segundos.

Repite estos 5 comandos en cada PC Windows del cliente.

---

### OPCIÓN B — Windows CON Active Directory (dominio empresarial)

Esto se hace **una sola vez en el Servidor / Controlador de Dominio**, no en cada PC.

**Cómo abrir PowerShell como Administrador de Dominio en el servidor:**
1. Inicia sesión en el Controlador de Dominio con cuenta de Administrador de Dominio
2. Presiona tecla Windows → escribe `PowerShell` → Ejecutar como administrador

**Comando 1 — Crear el usuario en el dominio** *(una sola línea, escríbela completa)*:
```
net user NOMBRE_USUARIO CONTRASEÑA /add /domain /passwordchg:no /expires:never
```
Resultado esperado: `Se ha completado el comando correctamente.`

**Comando 2 — Darle permisos de administrador de dominio** *(hablar antes con el IT del cliente — esta es la opción más simple)*:
```
net group "Domain Admins" NOMBRE_USUARIO /add /domain
```
Resultado esperado: `Se ha completado el comando correctamente.`

Si el cliente no acepta permisos de administrador de dominio (por política de seguridad): avisa a ingeniería para coordinar la configuración vía GPO — no lo hagas por tu cuenta.

**Nota importante:** Si la política del dominio vence las contraseñas cada cierto tiempo, el inventario fallará cuando venza. Pídele al IT del cliente que marque esta cuenta como "la contraseña nunca vence" en Usuarios y Equipos de Active Directory.

---

### Linux — cualquier distribución

Conéctate al equipo por SSH o ve físicamente a él y abre una terminal.

**Comando 1 — Crear el usuario**:
```
sudo adduser NOMBRE_USUARIO
```
El sistema te va a pedir que escribas la contraseña dos veces — escribe la contraseña que te dio ingeniería.
Resultado esperado: `Adding user NOMBRE_USUARIO ...` y luego varias líneas de confirmación.

**Comando 2 — Darle permisos para leer info del sistema**:
```
sudo usermod -aG sudo NOMBRE_USUARIO
```
Resultado esperado: ningún mensaje de error = está bien.

**Verificación — confirmar que el usuario existe**:
```
id NOMBRE_USUARIO
```
Resultado esperado: una línea con `uid=...` que incluye `sudo` entre los grupos.

Si el cliente no acepta permisos sudo: el inventario básico funciona igual pero puede no obtener algunos datos de hardware. Avisa a ingeniería si eso ocurre.

---

### macOS

**Paso 1 — Habilitar acceso remoto por SSH** *(si no está activo)*:
1. Clic en el menú Apple → **Configuración del Sistema**
2. Ir a **General → Compartir**
3. Activar el interruptor de **Inicio de Sesión Remota**
4. En la opción "Permitir acceso a": seleccionar **Todos los usuarios** o agregar el usuario específico

**Paso 2 — Crear el usuario** *(desde la interfaz gráfica, más fácil)*:
1. Clic en el menú Apple → **Configuración del Sistema**
2. Ir a **Usuarios y grupos**
3. Clic en el botón **+** (agregar usuario)
4. Tipo de cuenta: **Estándar**
5. Nombre completo: `Shomer Inventario`
6. Nombre de cuenta: `NOMBRE_USUARIO` *(exactamente como te lo entregó ingeniería)*
7. Contraseña: la que entrega ingeniería
8. Clic en **Crear usuario**

**Verificación:**
Abre una terminal y escribe:
```
id NOMBRE_USUARIO
```
Resultado esperado: una línea con `uid=...` que muestra el usuario.

---

### Después de crear el usuario en cada equipo: registrar en el panel

Haz esto una vez por equipo en el panel del Shomer:

1. Abre el panel → **Tracker → Credenciales**
2. Clic en **Agregar credencial**
3. Completa:
   - **IP del equipo**: la IP del PC o servidor donde creaste el usuario
   - **Usuario**: `NOMBRE_USUARIO` *(el mismo que usaste al crear)*
   - **Contraseña**: la misma contraseña
   - **Tipo**: Windows / Linux / macOS según corresponda
4. Clic en **Guardar**
5. Para verificar que funciona: ir a **Tracker → Inventario → Deep Scan** → el equipo debe aparecer con más datos que antes

Las credenciales se guardan de forma segura en el Shomer. **No las anotes en papel ni en mensajes de texto.**

Para Protector (backups): usa las mismas credenciales — el sistema las comparte automáticamente entre módulos.

---

### Carpeta de backup en Windows — paso adicional para Protector

Si el cliente va a tener backups de un PC Windows, además del usuario necesitas crear una carpeta compartida. Haz esto **en cada PC Windows con backup**, en PowerShell como Administrador:

**Comando 1 — Crear la carpeta de backup**:
```
New-Item -ItemType Directory -Path "C:\backups" -Force
```
Resultado esperado: muestra la ruta `C:\backups` como confirmación.

**Comando 2 — Compartirla en la red con acceso para el usuario**:
```
New-SmbShare -Name "backups" -Path "C:\backups" -FullAccess "NOMBRE_USUARIO"
```
Resultado esperado: una tabla con `Name: backups` y `Path: C:\backups`.

**Comando 3 — Abrir el firewall de Windows para que el Shomer pueda conectarse** *(reemplaza IP-DEL-SHOMER con la IP real del Shomer en ese sitio)*:
```
New-NetFirewallRule -DisplayName "Shomer Backup" -Direction Inbound -Protocol TCP -LocalPort 445 -RemoteAddress IP-DEL-SHOMER -Action Allow
```
Resultado esperado: una tabla que confirma la nueva regla creada.

**Verificación final:** en el panel del Shomer → **Protector → ese equipo → Backup ahora**. Si completa sin error, está listo.

Si el cliente tiene Active Directory con carpetas de red ya configuradas: avisa a ingeniería antes de crear carpetas nuevas — puede que ya existan y solo haya que apuntar al path correcto.

---

## Tracker — cómo hacer inventario

1. **Quick Scan:** encuentra equipos vivos. Dura 2–5 minutos (más si hay muchas subredes). Úsalo al llegar a un sitio.
2. **Deep Scan:** rellena OS, CPU, RAM, disco, **software**, **usuario logueado**, monitores/USB detectados. Requiere credenciales WMI/SSH. ~15–90 s por PC Windows; en redes de **500+ equipos** escanear **por VLAN de noche**, no todo de golpe.
3. **Credenciales:** usuario de dominio AD en Tracker → Credenciales (usuario, contraseña, dominio). Para Active Directory: usuario sin prefijo de dominio en el campo Usuario, dominio en campo Dominio.
4. **Ficha del equipo:** abrir cualquier fila → sección *Monitores (validación física)*:
   - Marcar **Monitor integrado** en portátiles y All-in-One (modelo/serial del panel).
   - Registrar **monitores externos** adicionales (0–3) con modelo y serial de etiqueta.
   - Revisar bloques *detectados en escaneo* (USB, impresoras locales, monitores WMI).
5. **Exportar:** Excel global o etiqueta PDF por equipo.

**Regla de cierre formal de inventario:** si el cliente requiere un "snapshot" oficial (cierre contractual), el sistema lo guarda y la tabla viva puede quedar vacía. **Exporta el Excel el mismo día del cierre.** No mezcles archivos viejos de base de datos con el snapshot nuevo.

**Rescan de un solo PC:** desde servidor, `INVENTORY_SCAN_TARGETS=192.168.X.Y ./venv/bin/python3 -m app.scripts.scanner` (modo deep).

## Hunter — política de bloqueos

**Auto-bloqueo apagado por defecto** — Shomer no bloquea nada solo hasta que el técnico lo enciende.

Cuándo activarlo:
- Primera semana: déjalo en modo manual. Observa qué alertas genera el tráfico del cliente.
- Cuando entiendas el ruido del sitio: activar solo para amenazas Críticas.
- Después de afinar: puedes bajar a severidad Alta si hay pocas falsas alarmas.

La columna **Firewall** en la lista de IPs bloqueadas dice:
- `✔ red` → la regla está activa en el router
- `solo BD` → se registró pero no se aplicó en el router (puede pasar si el router estaba caído)

Si ves muchas entradas `solo BD`: usa el botón **Sincronizar Firewall** para re-aplicarlas.

**Riesgos de Red (auditoría):** Hunter → sección *Riesgos de Red* → botón escanear. Analiza puertos abiertos y **parches pendientes** en PCs Windows del inventario. En redes grandes puede tardar 15–45 min; ejecutar fuera de horario pico.

**Cuando el router se reinicia:** las reglas iptables desaparecen. El panel sigue mostrando las IPs como bloqueadas, pero en la red ya están libres. Usa el botón de sincronización al volver de mantenimiento o cuando el router reinicia.

## Protector — configurar backups

Para cada equipo del cliente que va a tener backup:

1. En el panel → **Protector → Agregar equipo**.
2. Configurar:
   - Nombre descriptivo (ej. `Hotel Plaza — PC Recepción`)
   - IP del equipo
   - Tipo: Windows / Linux / macOS
   - Usuario y contraseña del equipo (usuario `shomer` que creas previamente)
   - Hora de backup (hora local del sitio — el panel ajusta automáticamente)
   - Si va a nube: activar ☁ B2 y configurar la ruta del cliente (slug que entrega ingeniería, ej. `hotel-plaza`)
3. Prueba: **Backup ahora** → debe completar en menos de 5 minutos si es la primera vez (o más si el equipo tiene muchos datos).

⚠️ **Antes de agregar el equipo aquí:** el usuario de servicio ya debe estar creado en ese equipo. Si no lo has hecho todavía, ve a la sección **"Usuario de servicio Shomer"** más arriba en este documento y sigue los pasos según el tipo de equipo (Windows, Linux o macOS). Para backups en Windows también necesitas la carpeta compartida — esos pasos están en la misma sección.

**Convención de nombre de ruta en nube:** cada cliente tiene su propio prefijo en B2. Nunca mezcles clientes en la misma ruta. El slug lo define ingeniería antes de la instalación.

## Múltiples subredes (hoteles / VLANs)

En instalaciones con varias VLANs o segmentos: declarar **todas** las subredes en Guardian, Tracker y Hunter. En el Shomer, `ip route` debe alcanzar cada segmento — agregar rutas estáticas en netplan si el core no conoce la VLAN. El MikroTik/OpenWrt debe tener L3 routing hacia cada segmento. Ver `Anexo_MikroTik_TFTP_OpenWrt.md` Fase G para el detalle.

---

# PARTE 4 — EL BOT DE TELEGRAM (Agente Shomer)

El bot vive en el mismo chat donde llegan las alertas. Lo puedes usar en lenguaje natural o con comandos directos. Las preguntas en texto libre usan **OpenAI** (si está configurado en `.env`) o **Groq** como respaldo — los monitores automáticos siempre usan Groq gratis.

## Comandos más usados

**Sin `/start`** — entrada: `/consultas`, `/ayuda` o texto libre. Lista completa: `/ayuda`.

| Comando | Para qué sirve |
|---------|----------------|
| `/consultas` | Ejemplos de qué preguntar en texto libre |
| `/ayuda` | Todos los comandos y monitores automáticos |
| `/salud` | Estado del servidor (solo texto, sin botones) |
| `/salud monitores` | Estado de cada monitor automático (26 tareas) |
| `/salud resumen` | Reporte del día con IA |
| `/equipos` | APs Guardian y equipos del agente |
| `/diagnostico 10.10.0.10` | Ping, estado, fallos, uptime |
| `/diagnostico 10.10.0.10 reparar` | Diagnóstico + reparación automática |
| `/reboot 10.10.0.10` | Reiniciar AP — pide confirmación (`/reiniciar` igual) |
| `/modo on` / `/modo off` | Mantenimiento — pausa reboots auto (`/mantenimiento` igual) |
| `/alertas` | Alertas Hunter e IPs bloqueadas |
| `/bloquear 1.2.3.4` | Bloquear IP — con confirmación |
| `/desbloquear 1.2.3.4` | Liberar IP bloqueada |
| `/guardar <IP> <texto>` | Guardar qué pasó para futuras alertas |
| `/historial` | Últimos cambios realizados |
| `/instalar` | Guía de instalación paso a paso |
| `/verificar` | Checklist final de instalación |
| `/nuevo` | Limpiar historial de conversación con la IA |

| `/infra` | Lista equipos Infra |
| `/infra <IP>` | Detalle conexión (ping, TCP, SNMP, tóner) |
| `/puertos <IP>` | Puertos SNMP de switch/router/servidor |

## Lo que el bot hace solo (sin que le pidas)

- AP caído: alerta con botón de reinicio; si hubo solución guardada, la muestra en el mensaje
- AP o equipo Infra recuperado: aviso + opción de guardar qué pasó
- Hunter bloquea IP: alerta; al desbloquear podés guardar falso positivo
- Disco ≥85 %: limpieza automática y aviso
- Servicio Shomer caído: aviso
- Infra: caída, tóner bajo, TCP/SNMP caído, flapping cable/PoE
- Cada mañana 7:00: resumen diario automático

## Niveles de usuario en el bot

- **Técnico:** comandos operacionales. La IA usa lenguaje simple y operacional.
- **Developer (Juan Pablo):** acceso completo incluyendo backups, restauración y consultas técnicas internas.

---

# PARTE 5 — ACCESO REMOTO (VPN WireGuard)

## Por qué VPN y no SSH directo a internet

Exponer el Shomer a internet es un riesgo. La solución: **VPN WireGuard** en el router del cliente. El técnico se conecta primero a la VPN y desde ahí entra a la red interna sin que nada esté expuesto.

## Cómo conectarse

1. Instalar WireGuard en tu laptop.
2. Importar el archivo `.conf` que entrega USB Ingeniería para ese sitio.
3. Activar el túnel.
4. Acceder al panel del Shomer y hacer SSH normalmente.

Cada sitio tiene su propio archivo `.conf` con datos diferentes — no los mezcles.

## Para el router del cliente (OpenWrt)

Ingeniería configura el servidor WireGuard en el OpenWrt del cliente durante la instalación. Lo que el técnico necesita saber:

- El router debe tener IP pública (o que el router principal del cliente haga reenvío del puerto UDP)
- Si la IP del cliente es dinámica: ingeniería configura DDNS
- Para agregar un técnico nuevo: avisar a ingeniería — es una operación de 5 minutos
- Para revocar acceso: avisar a ingeniería — se hace inmediatamente

---

# PARTE 6 — HOJA DE DATOS DEL SITIO

Antes de conectar cualquier cable, siéntate con el responsable de IT del cliente y completa esta tabla. Sin estos datos no puedes configurar el Shomer correctamente.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOJA DE DATOS — INSTALACIÓN SHOMER SENTINEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATOS DEL CLIENTE
Nombre del cliente / empresa: ________________
Nombre del sitio (para alertas): ________________
Ciudad / País: ________________
Fecha de instalación: ________________
Técnico responsable: ________________

RED DEL CLIENTE
Subred LAN (ej. 192.168.1.0/24): ________________
Gateway principal: ________________
IP asignada al Shomer: ________________
IP asignada al MikroTik (LAN): ________________
¿El ISP da IP pública fija?: Sí / No
Nombre de dominio DDNS (si aplica): ________________
Zona horaria del sitio: ________________
  Ejemplos: America/Bogota · America/Lima · America/Mexico_City
            America/New_York · America/Santiago · America/Buenos_Aires

FIREWALL (MikroTik/OpenWrt)
IP LAN del firewall: ________________
¿El ISP da IP dinámica?: Sí / No → configurar DDNS
¿Está detrás del router del ISP (doble NAT)?: Sí / No

SEGURIDAD / HUNTER
IP del firewall que Hunter va a controlar: ________________
Usuario SSH del router: ________________
Puerto SSH (normalmente 22): ________________

EQUIPOS AP / ROUTERS A MONITOREAR (Guardian)
Equipo 1: Nombre _____________ IP _____________ Tipo _____________
Equipo 2: Nombre _____________ IP _____________ Tipo _____________
Equipo 3: Nombre _____________ IP _____________ Tipo _____________
Equipo 4: Nombre _____________ IP _____________ Tipo _____________
(agregar filas según necesidad)

EQUIPOS CON BACKUP (Protector)
¿El cliente contrata backups?: Sí / No
Equipo 1: Nombre _____________ IP _____________ OS _____________
Equipo 2: Nombre _____________ IP _____________ OS _____________
Equipo 3: Nombre _____________ IP _____________ OS _____________
¿Tiene almacenamiento en nube B2?: Sí / No
Slug B2 del cliente (entrega ingeniería): ________________

INVENTARIO (Tracker)
¿El cliente tiene Active Directory?: Sí / No
Nombre de dominio Windows (si aplica): ________________
¿Se creará usuario de servicio nuevo?: Sí / No → nombre: ________________
¿El cliente facilita un usuario admin existente?: Sí / No

TELEGRAM Y ACCESO REMOTO
Chat ID de Telegram para alertas: ________________
¿Se configurará VPN WireGuard?: Sí / No
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Reglas sobre esta hoja:**
- No escribas contraseñas aquí — van al panel del Shomer directamente
- No uses papel suelto — tómale foto o pásala a un mensaje seguro
- Envía copia a ingeniería antes de empezar a configurar
- Guarda una versión en el historial del cliente para futuras visitas

---

# PARTE 7 — VERIFICAR LA INSTALACIÓN CON EL BOT

Una vez que terminaste todos los pasos, el bot puede verificar automáticamente que todo quedó bien. Usa el comando:

```
/verificar
```

El bot revisa cada componente y te entrega un reporte así:

```
📋 VERIFICACIÓN — Hotel Plaza Bogotá
━━━━━━━━━━━━━━━━━━━━━
✅ Servicios activos (Guardian, Tools, Redis)
✅ Nombre del sitio configurado
✅ Zona horaria: America/Bogota
✅ Telegram funcionando
✅ Guardian: 3 nodos monitoreados
⚠️ Hunter: sin firewall configurado — completa el Paso 9
✅ Suricata activo y recibiendo tráfico
⚠️ Protector: sin equipos registrados — ¿el cliente tiene backup?
✅ NIC espejo sin IP (correcto)
✅ Internet del servidor: activo

Estado: 8/10 ✅  —  2 pendientes ⚠️
```

Cada ítem en amarillo ⚠️ indica qué falta y a qué paso del documento ir. Cuando todos estén en verde, la instalación está completa.

---

# PARTE 8 — CUÁNDO ESCALAR A INGENIERÍA Y QUÉ INFORMACIÓN DAR

Antes de llamar o escribir a ingeniería, recopila esta información — con esto pueden ayudarte en minutos en lugar de horas:

**Información básica que siempre necesitan:**
```
1. Nombre del cliente / sitio
2. IP del Shomer en ese sitio
3. ¿Qué módulo está fallando? (Guardian / Tracker / Hunter / Protector / Bot)
4. ¿Desde cuándo falla? ¿Funcionaba antes?
5. ¿Qué hiciste justo antes de que fallara?
```

**Capturas de pantalla útiles:**
- La pantalla entera del error (no solo el mensaje)
- El panel de Estado del Sistema
- El resultado de `/salud` en el bot de Telegram

**Si el panel no carga:**
Conecta por VPN y desde el Shomer ejecuta:
```
systemctl status shomer-guardian
```
Copia el texto completo que aparece y envíalo a ingeniería.

**Si el bot no responde:**
Desde el Shomer ejecuta:
```
docker logs shomer-agent --tail 50
```
Copia y envía a ingeniería.

**Problemas que NUNCA debes intentar resolver solo:**
- El Shomer no arranca después de un reinicio
- El panel pide usuario/contraseña y las credenciales correctas no funcionan
- Se perdió acceso SSH al Shomer
- Apareció un mensaje de error sobre la base de datos
- El disco está al 100% y el bot ya no responde

---

# PARTE 9 — CÓMO SE ACTUALIZA EL SISTEMA

Cuando ingeniería libera una actualización, te avisará por Telegram con instrucciones específicas para ese sitio. El proceso general es:

**No hay actualizaciones automáticas** — cada actualización se coordina con ingeniería para no afectar al cliente en horas pico.

**Lo que normalmente hace ingeniería (no el técnico):**
- Validar la actualización en laboratorio antes de enviarla al campo
- Indicar la ventana de tiempo recomendada (normalmente madrugada o fin de semana)
- Enviarte el comando exacto a ejecutar vía canal seguro

**Lo que hace el técnico en sitio:**
1. Activa el **modo mantenimiento** en Guardian antes de empezar
2. Ejecuta el comando exacto que envió ingeniería (copia y pega — no transcribas a mano)
3. Espera la confirmación de que los servicios volvieron activos
4. Verifica con `/verificar` en el bot que todo está bien
5. Desactiva el modo mantenimiento
6. Confirma a ingeniería que el sitio quedó operativo

**Si algo falla durante una actualización:** no intentes revertir solo. Avisa a ingeniería inmediatamente con el error exacto — tienen el procedimiento de rollback listo.

---

# PARTE 11 — REGLAS DE ORO

1. **Bloqueos siempre desde Shomer**, nunca limpiar el firewall del router a mano y esperar que el panel siga alineado. Si alguien toca iptables a mano, el panel y la red dejan de contar la misma historia.

2. **Antes de cualquier trabajo físico:** activar modo mantenimiento en Guardian. Al terminar: desactivarlo.

3. **Tres tipos de alerta Telegram — son distintas:**
   - 🟢🔴 **Guardian** → disponibilidad de APs (caída, recuperación, reboot)
   - 🚨 **Hunter** → IP bloqueada por tráfico sospechoso detectado por Suricata
   - 🛡️ **Wazuh → Shomer** → IP bloqueada por regla del sistema (brute force, malware, etc.)

4. **Cierre de inventario:** guarda el Excel exportado el mismo día del cierre. Después de un snapshot formal, el inventario vivo puede quedar vacío — es por diseño.

5. **Si algo no funciona y no sabes por qué:** escala a ingeniería antes de hacer cambios. El sistema tiene logs que ingeniería puede leer para entender qué pasó.

6. **La NIC espejo nunca lleva IP.** Si un día ves que le asignaron una dirección y hay problemas de red: eso es la causa. Avisar a ingeniería para removerla.

---

*USB Ingeniería SAS — documento operacional para técnico de campo.*
*Los valores específicos de cada instalación (IPs, credenciales, tokens, comunidades SNMP) se entregan por canal seguro separado, nunca en este documento.*
*Versión mayo 2026 — unificado: incluye checklist Hunter campo + integración Wazuh.*

---

# PARTE 10 — HUNTER: CHECKLIST DE PRUEBAS EN CAMPO

**Objetivo:** confirmar que el tráfico espejado llega a Suricata, que las alertas son visibles en el producto y (si aplica) que el bloqueo vía firewall está alineado con el cliente.

**Prerrequisitos:** MikroTik/OpenWrt con TEE o reglas de espejo ya aplicadas; `rp_filter=0` en la NIC de captura del Shomer (`Instalacion_Shomer_Produccion_Tecnico.md` §2.3).

> **Nota firewall — OpenWrt:** bloqueo por `iptables` en `FORWARD` (automático vía SSH).  
> **Nota firewall — MikroTik RouterOS nativo:** soportado con `hunter.firewall_type=routeros`. Shomer agrega IPs a la address-list `shomer-blocked`; **obligatorio** crear una vez la regla DROP en `chain=forward` (panel Hunter → *Verificar regla DROP*; en **producción** aplicación manual). Sin esa regla el bloqueo no es efectivo. Ver `HUNTER_MIKROTIK_ROUTEROS.md` en el panel (`/static/docs/`).
>
> **Nota bot (jun 2026):** no repite “amenaza contenida” por IPs ya bloqueadas ni “riesgos altos pendientes” si ya están marcados terminado en panel. Alertas en panel Hunter (Suricata) pueden continuar — es el IDS en espejo, no Telegram.

## A. Infraestructura (5 min)

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| A1 | `suricata` activo | `systemctl is-active suricata` | |
| A2 | Servicios Core / Tools | `systemctl is-active shomer-guardian shomer-tools redis-server` | |
| A3 | Puertos API | `ss -tlnp \| egrep ':(8000\|8001)\b'` — un listener en cada uno (8001 suele ser localhost) | |
| A4 | Circuit breaker firewall | `GET /remedies/firewall/status` — `circuit_open: false` esperado | |

## B. Espejo de tráfico (obligatorio)

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| B1 | Tráfico en NIC mirror | `sudo tcpdump -i enp4s0 -n -c 40` (cambiar si la NIC mirror tiene otro nombre) — deben verse paquetes de la LAN | |
| B2 | Si B1 = vacío | Revisar cable espejo, TEE en OpenWrt, `sysctl` rp_filter, rutas; **no** seguir a alertas hasta ver tráfico | |

## C. Regla de laboratorio ICMP (si está desplegada)

> Firma de ejemplo: **SID 9009001** (ICMP visible en captura). Detalle: `CLAUDE.md` §E.

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| C1 | Regla cargada | Panel Hunter → recarga de reglas, o verificar fichero bajo `/etc/suricata/rules/` | |
| C2 | Generar ICMP | Desde un PC en la LAN: `ping` hacia otra IP que pase por el tráfico espejado hacia el Shomer | |
| C3 | Ver alerta en EVE | Panel Hunter **o** `GET /remedies/suricata/recent` (autenticado) | |

## D. Subredes y configuración panel

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| D1 | Subredes del cliente | Hunter → Configuración: `hunter.subnets` = subred real del cliente. Revalidar si cambió la LAN | |
| D2 | Credenciales firewall | `hunter.firewall_ip`, `hunter.firewall_user`, `hunter.firewall_pass`, `hunter.firewall_port` configurados en panel | |
| D3 | Excepciones autobloqueo | `hunter.auto_block_exceptions` incluye IPs de gestión, Shomer propio, gateway | |
| D4 | Probar SSH al firewall | `GET /remedies/firewall/status` — `circuit_open: false`. Si falla: `POST /remedies/firewall/reset` y revisar credenciales | |

## E. Bloqueo y desbloqueo de prueba (usar IP reservada RFC 5737)

> **Usar siempre `198.51.100.1`** u otra IP reservada RFC 5737. **Nunca** IPs operativas del cliente.

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| E1 | Bloqueo manual | `POST /remedies/block {"ip":"198.51.100.1","blocked_by":"manual"}` — `success:true, firewall_ok:true` | |
| E2 | Verificar en firewall | SSH al OpenWrt: `iptables -L FORWARD -n \| grep 198.51.100.1` — debe aparecer `DROP` | |
| E3 | Desbloqueo | `POST /remedies/unblock {"ip":"198.51.100.1"}` — `success:true, firewall_ok:true` | |
| E4 | Verificar limpieza | SSH al OpenWrt: `iptables -L FORWARD -n \| grep 198.51.100.1` — no debe aparecer | |

## F. Wazuh y bloqueo (solo si el contrato lo incluye)

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| F1 | Clave integración | `hunter.integration_key` en BD (panel Hunter → sección Wazuh). Misma clave en script active-response | |
| F2 | Script active-response | `/var/ossec/active-response/bin/wazuh-shomer-block` presente y ejecutable (`chmod 750`, `chown root:wazuh`) | |
| F3 | Prueba manual script | Ver PARTE 7 §3 — `echo '{...json...}' \| SHOMER_WAZUH_INTEGRATION_KEY=... ./wazuh_shomer_block.py` | |
| F4 | Active-response en `ossec.conf` | `<level>12</level>` apuntando a `wazuh-shomer-block`. Reiniciar `wazuh-manager` tras cambio | |
| F5 | Pipeline Wazuh/Suricata | `GET /remedies/pipeline/health` — `overall_ok: true`, EVE age < 300 s en actividad | |

## G. Seguridad operativa — checklist anti-riesgo (OBLIGATORIO sitio nuevo)

| # | Comprobación | Cómo | ✓ |
|---|----------------|------|---|
| G1 | **Subredes correctas** | `hunter.subnets` = subred real cliente. Verificar que una IP interna aparezca como `external: false` | |
| G2 | **Excepciones permanentes** | `hunter.auto_block_exceptions`: gateway, IP del Shomer, IP servidor Wazuh si aplica | |
| G3 | **Primera semana: solo Critical** | `hunter.auto_block_min_severity = 1` hasta afinar el ruido del sitio | |
| G4 | **Puerto y timeout SSH** | `hunter.firewall_port` y `hunter.firewall_timeout` (default 10 s) ajustados si el router del cliente usa valores distintos | |
| G5 | **Sync tras reboot del router** | Si el OpenWrt se reinicia, usar `POST /remedies/sync-firewall` o botón **↺ Sincronizar Firewall** para re-aplicar bloqueos activos | |
| G6 | **Estado firewall_blocked** | Panel Hunter → Bloqueadas activas: columna Firewall debe mostrar `✔ red`. `solo BD` indica que la regla no se aplicó o se perdió | |

**Cierre:**
- [ ] Ticket interno: resultado B1, E1-E4, F si aplica, G completo, incidencias.
- [ ] Si B1 falla, **abrir** seguimiento de red — no dar por "Hunter OK" sin espejo.
- [ ] **Nunca activar `auto_block_enabled` sin completar G1 y G2 primero.**

---

# PARTE 12 — WAZUH: INTEGRACIÓN DE BLOQUEO

## Cadena de capas

| Ruta | Descripción |
|------|-------------|
| **Suricata → panel Hunter** | Suricata escribe EVE/alertas; Shomer lee y las muestra. El autobloqueo `blocked_by: auto` aplica la política `hunter.auto_block_*`. No pasa por Wazuh. |
| **Suricata → Wazuh → Shomer** | El manager Wazuh ingiere logs/decoders, asigna niveles; el active response dispara el script `wazuh_shomer_block` → `POST /remedies/block` con `blocked_by: wazuh` y cabecera `X-Shomer-Integration-Key`. |

Las dos rutas pueden convivir — conviene no duplicar criterio al azar (ver §5).

## 1. Clave y política en el panel

1. Panel **Hunter → Configuración → Integración Wazuh**: genera o pega una clave y pulsa **Guardar** (se guarda como `hunter.integration_key`).
2. O en el entorno del servicio `shomer-guardian`: `SHOMER_WAZUH_INTEGRATION_KEY=...` (o `SHOMER_WAZUH_KEY_FILE=/etc/shomer/wazuh-integration.key`).
3. Las **excepciones** `hunter.auto_block_exceptions` también aplican a bloqueos vía Wazuh.
4. **Seguridad de la clave:** Wazuh y Shomer corren en el mismo servidor (loopback `127.0.0.1:8000`). Clave en texto plano en header es suficiente — el puerto 8000 no está expuesto al exterior.

## 2. Política de autobloqueo (Redis y severidad)

- **Solo externas**: por defecto no se autobloquea una IP interna salvo severidad 1 (Critical).
- **Recurrencia ALTA**: si `high_recurrence_min > 1`, el backend cuenta eventos con Redis. Sin Redis disponible → responde `skipped` explícito.
- **Telegram**: al bloquear por Wazuh llega aviso **"BLOQUEO (Wazuh → Shomer)"**. Si ya estaba bloqueada → no reenvía Telegram (evita spam).

## 3. API

`POST /remedies/block` con cabecera `X-Shomer-Integration-Key: <clave>`

```json
{
  "ip": "1.2.3.4",
  "blocked_by": "wazuh",
  "alert_signature": "texto opcional",
  "severity": 2,
  "alert_sid": 2013426
}
```

## 4. Script active-response

Ruta en el repo: `tools/cazador/wazuh_shomer_block.py`

```bash
# Instalación
sudo install -m 750 -o root -g wazuh \
  /opt/network_monitor/tools/cazador/wazuh_shomer_block.py \
  /var/ossec/active-response/bin/wazuh-shomer-block

sudo printf '%s' 'TU_CLAVE_LARGA' | sudo tee /etc/shomer/wazuh-integration.key
sudo chmod 600 /etc/shomer/wazuh-integration.key
sudo chown root:wazuh /etc/shomer/wazuh-integration.key

# Prueba manual
export SHOMER_WAZUH_INTEGRATION_KEY="TU_CLAVE"
echo '{"data":{"src_ip":"1.1.1.1"},"parameters":{"message":"test"}}' \
  | /opt/network_monitor/tools/cazador/wazuh_shomer_block.py
```

## 5. Fragmento `ossec.conf`

```xml
<ossec_config>
  <command>
    <name>wazuh-shomer-block</name>
    <executable>wazuh-shomer-block</executable>
    <timeout_allowed>no</timeout_allowed>
  </command>
  <active-response>
    <disabled>no</disabled>
    <command>wazuh-shomer-block</command>
    <location>local</location>
    <level>12</level>
  </active-response>
</ossec_config>
```

Tras editar: `sudo systemctl restart wazuh-manager`.

## 6. Coexistencia con autobloqueo del panel

Si hay ruido, elegir **una** política y mantenerla fija:
- (a) Restringir autobloqueo Hunter a solo Critical o solo IPs externas; **o**
- (b) Dejar el bloqueo "fuerte" solo en Wazuh (nivel ≥ 12) y usar Hunter solo para bloqueo manual.

`hunter.auto_block_enabled` arranca en `false` — hay que activarlo explícitamente si se desea.

## 7. Troubleshooting Wazuh dashboard "There are no results"

1. Quitar el filtro de `manager.name` o ampliar el rango de tiempo (*Last 7 days*).
2. Verificar el nombre real del manager en los índices (campo `manager.name` en Discover).
3. Sin alertas de Suricata ingeridas por Wazuh no habrá nada que mostrar — revisar decodificador/`<localfile>`/agente.
4. UFW: si el Dashboard (puerto 443) no responde desde el navegador, añadir: `sudo ufw allow from 192.168.1.0/24 to any port 443 proto tcp`.

## 8. Verificación lab end-to-end (Sesión 23 — 10 mayo 2026)

```bash
echo '{"data":{"src_ip":"5.5.5.5","alert":{"signature":"ET SCAN test","signature_id":9009001,"severity":1}},"parameters":{"message":"test"}}' \
  | SHOMER_WAZUH_INTEGRATION_KEY="Usbing08*@2026" \
    SHOMER_API_URL="http://127.0.0.1:8000/remedies/block" \
    ./venv/bin/python tools/cazador/wazuh_shomer_block.py
# → {"success":true,"firewall_ok":true,"telegram_sent":true}

# iptables -L FORWARD -n  →  DROP all -- 5.5.5.5  ✅
# POST /remedies/unblock {"ip":"5.5.5.5"}  →  regla eliminada  ✅
```

Entorno: `.205` Ubuntu 22.04 / Shomer, `.206` OpenWrt 23.05.5 MIPS, asyncssh, iptables v1.8.8.
