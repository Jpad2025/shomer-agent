# Changelog — Shomer Agent

Formato libre, una entrada por release. La versión activa vive en `VERSION`
(consultable también con `/version` en el bot). Fecha = cuando se desplegó
en Ópera (maestro), no cuando se escribió el código.

## 1.26.2 — 2026-09-07

- **Fix: `/salud` mostraba "Groq (Llama 3.3 70B)" fijo en el código, pero el modelo real
  configurado es `openai/gpt-oss-20b`.** Encontrado al revisar límites diarios de IA con
  Juan Pablo -- el texto nunca se actualizó cuando cambió `GROQ_MODEL`. Ahora `status_lines()`
  lee el nombre real vía `groq_helper.GROQ_MODEL` en vez de un string fijo, así nunca vuelve
  a quedar desactualizado.

## 1.26.1 — 2026-09-07

- **Fix de costo real en la integración de KB del chat (v1.26.0), encontrado por pregunta
  directa de Juan Pablo sobre si esto subía el costo de OpenAI.** Al probar con un saludo
  casual ("hola como estás") encontré que SÍ inyectaba igual ~325 tokens de conocimiento
  genérico -- `_matching_domains()` cae a un fallback fijo ('metodologia') cuando no hay
  match real de palabra clave, comportamiento correcto para cerebro (un cluster de equipos
  siempre es una situación técnica) pero desperdicio puro en chat casual. Nuevo parámetro
  `strict` en `_matching_domains()`/`find_relevant()`/`format_for_prompt()` (default `False`,
  cerebro sin cambios); `llm_router.py` ahora llama con `strict=True` -- sin match real de
  palabra clave, no se inyecta nada. Probado con pregunta técnica (sigue trayendo KB) y
  saludo casual (ya no trae nada) antes de desplegar.

## 1.26.0 — 2026-09-07

- **KB CompTIA conectada al chat interactivo del técnico.** Auditoría pedida por Juan Pablo
  sobre las dos IAs (OpenAI gpt-4o-mini para chat, Groq Llama 3.3 70B para monitores/fallback)
  + cerebro (gpt-4o) + la base de 436 reglas/conceptos técnicos validados encontró que la KB
  solo llegaba al análisis automático de fondo (cerebro, Fase 2) y al comando manual
  `/conocimiento` -- el chat natural del técnico (`llm_router.py`) respondía sin verla nunca.
  `conocimiento_general.format_for_prompt()` ya hacía matching por palabra clave sobre texto
  libre (no exige nombres de equipo), así que la pregunta del técnico funciona igual de bien
  que un nombre de entidad -- cero lógica de matching nueva. Ahora `_inject_snapshot()` agrega
  el bloque de conocimiento relevante a la última pregunta del usuario, igual que ya hace con
  skills/patrones. Probado con una pregunta real ("¿por qué el switch de piso 3 se cae tanto?")
  antes de desplegar -- hizo match correcto con reglas de cableado/switching.

## 1.25.0 — 2026-09-07

- **Fase 7 del cerebro: estado real del WAN + fallas/reboots por nodo.** Al revisar qué más
  faltaba conectar a cerebro (pregunta directa de Juan Pablo), dos fuentes reales ya existían
  en `shomer_api.py` pero nunca se habían conectado al ciclo de razonamiento:
  `get_wan_status()` (estado del quorum de internet vía Redis, ver
  `shomer_guardian_server_health.py`) y `get_node_failures(ip)` (fallas acumuladas + último
  reboot por nodo Guardian, también vía Redis). Sin esto cerebro podía tratar una caída masiva
  causada por el WAN como N incidentes independientes, o un reinicio reciente de un equipo
  como si fuera un ataque nuevo. Ahora `run_cycle()` incluye `estado_wan` y
  `fallas_y_reboots_recientes_por_nodo` en el payload, con instrucciones explícitas en
  `_SYSTEM_PROMPT` sobre cómo pesarlos. Probado contra datos reales antes de desplegar (WAN
  `ok`, 0 nodos con fallas activas en este momento — comportamiento correcto, no hay nada que
  reportar ahora mismo).
- **Verificado que no se duplicó el reporte de Hunter por mes/trimestre/año** que Juan Pablo
  pidió: ya existe completo en network_monitor (`shomer_reports.py`, PDF automático día 1 de
  cada mes + rango custom vía `/reports/generate`, 4 meses reales archivados en
  `/srv/shomer_reports/`) y en vivo en el NOC (`shomer_noc.py::_hunter_stats()`). No se
  construyó nada nuevo para esto — hubiera sido una segunda fuente de verdad divergente.

## 1.24.0 — 2026-09-07

- **Cierre automático de ruido de Hunter confirmado (+14 días), con aviso por Telegram.** Nace
  de una conversación directa sobre los 108 incidentes de Hunter nunca reconocidos (auditoría de
  seguridad del 6 sep): en vez de cerrarlos todos por igual, se acordó con Juan Pablo un criterio
  conservador -- solo el patrón ya documentado en la KB como ruido de internet ("ET CINS Poor
  Reputation" en IPs externas), después de 14 días sin actividad. **IPs internas (192.168.x) y
  firmas distintas NUNCA se cierran solas, sin excepción** -- siempre esperan revisión humana.
  - Nuevo watcher `watch_hunter_noise_cleanup` (32ª tarea): corre una vez al día, cierra lo que
    califique y manda un resumen por Telegram de qué se cerró y por qué.
  - **Bug real encontrado y corregido en el camino**: la primera versión de
    `close_stale_noise_incidents()` escribía SQL directo a `/storage/db/network_monitor.db` --
    y falló en silencio con `attempt to write a readonly database`, porque ese volumen está
    montado **solo-lectura** en este contenedor a propósito (`docker-compose.yml`), para que el
    bot nunca pueda escribir la base de datos de Guardian sin pasar por su propia lógica de
    auditoría. `log.debug()` no es visible a nivel WARNING, así que el error real quedaba
    invisible y la función simplemente devolvía una lista vacía sin explicar por qué.
  - Corregido construyendo el endpoint real en network_monitor
    (`POST /incidents/close_stale_noise`, mismo repo, commit `5d0ec4d`) que reutiliza la misma
    lógica de auditoría (`status`/`closed_by`/`notes`) que el cierre manual de un solo incidente
    ya existente -- y `close_stale_noise_incidents()` aquí ahora llama a esa API por HTTP, mismo
    patrón que `block_ip()`/`unblock_ip()`, en vez de tocar la base de datos directamente.
  - Probado contra producción real: 49 incidentes de ruido externo cerrados correctamente, los 3
    de IPs internas (incluido el de "PIN en texto plano" de la auditoría) quedaron intactos,
    confirmado en la base de datos.

## 1.23.0 — 2026-09-07

- **Fase 6 del cerebro: 3 fuentes reales más, todas ya existentes en el sistema pero que el
  cerebro nunca consultaba.** Mismo principio que las fases anteriores: hechos ya verificados por
  otro sistema, no algo que el modelo deba adivinar desde los eventos crudos.
  - `shomer_api.get_recent_ip_change(ip)`: consulta `mac_reconcile_log` -- si un equipo "offline"
    en realidad solo cambió de IP (DHCP/reconfiguración), el cerebro ahora lo sabe en vez de
    tratarlo como una caída real. Tabla vacía hoy (0 reconciliaciones registradas aún) -- la
    función es correcta, simplemente no ha tenido nada que reconciliar todavía.
  - `shomer_api.get_hunter_incidents(ips)`: incidentes de Hunter/Suricata actualmente abiertos
    sobre IPs internas del cluster. **Sin ventana de tiempo a propósito** -- primer intento
    filtraba a 24h y no encontraba nada real porque los incidentes de Hunter quedan abiertos
    indefinidamente en la práctica (hallazgo de la auditoría de seguridad del 6 sep: ninguno se
    cierra hoy). Corregido para verificar solo si sigue abierto AHORA, sin importar cuándo abrió.
    Probado con datos reales: encuentra el incidente "PIN en texto plano" (192.168.0.28, abierto
    desde el 30 de agosto, el mismo que quedó pendiente de revisión en esa auditoría).
  - `shomer_api.get_pending_audit_findings(ips)`: hallazgos de auditoría de red pendientes de
    severidad alta/crítica (ej. "RDP expuesto", "VNC expuesto") para IPs del cluster. Probado con
    datos reales -- 166 hallazgos en la tabla, encuentra correctamente los de severidad alta.
  - `get_switch_port_errors()` (ya existía, nunca se usaba desde brain.py): ahora se filtra al
    cluster actual y solo se incluyen puertos con errores reales (no se infla el prompt con
    puertos sanos). Probado con datos reales: un switch con 8568 errores acumulados en un puerto
    específico -- evidencia mucho más fuerte que "sospechar del cable" sin datos.
  - System prompt actualizado explicando las 4 fuentes (topología de Fase 5 + estas 3) y cómo
    pesarlas: todas son hechos verificados, no conjeturas -- si dicen "ninguno", no inventar que
    sí hay.
  - Sin cambio de comportamiento cuando no hay datos para un cluster (todos los campos nuevos
    caen a "ninguno" explícito, el cerebro sigue funcionando igual que antes de esta fase).

## 1.22.0 — 2026-09-06

- **Fase 5 del cerebro: correlación por topología real (LLDP/SNMP), no solo coincidencia de
  tiempo.** Complementa las Fases 1-4 (correlación por tiempo, conocimiento técnico, verificación
  en vivo, aprendizaje) construidas antes en esta misma sesión. Requirió construir primero el
  descubrimiento real de topología en network_monitor (antes era un placeholder que solo releía
  enlaces cargados a mano) y un ciclo automático que lo mantiene actualizado cada 5 minutos.
  - `shomer_api.get_topology_parents(ips)`: lee `network_links` directamente (mismo host, solo
    lectura, mismo patrón que `get_switch_port_errors()`) y devuelve el switch/router padre real
    para las IPs dadas, cuando se conoce.
  - `brain.py`: en cada cluster, si 2+ entidades comparten el mismo switch padre real (hecho
    verificado por SNMP, no una suposición), se le informa explícitamente al modelo como
    `topologia_confirmada_por_lldp` -- el prompt del sistema ahora distingue claramente "hecho
    verificado por topología" (más fuerte) de "solo coincidencia de tiempo" (más débil), y pide
    no inflar una coincidencia temporal a certeza de switch compartido si la topología no la
    confirma.
  - Probado end-to-end contra datos reales: `get_topology_parents(['192.168.0.1',
    '192.168.0.217', '192.168.0.129'])` devuelve correctamente el switch padre real para cada IP
    con enlace conocido.
  - Sin cambio de comportamiento cuando no hay enlaces conocidos para las IPs de un cluster
    (`topologia_confirmada_por_lldp` queda vacío, el cerebro sigue funcionando exactamente igual
    que antes de esta fase).

## 1.21.0 — 2026-09-06

- **Primera suite de pruebas automatizadas de shomer-agent — hasta ahora tenía CERO pruebas.**
  Surgió de la auditoría de estabilidad para despliegue multi-cliente: se encontraron 3 bugs
  reales ese mismo día (memoria de shomer-tools, discover_macs.py roto, cálculo uptime_24h)
  sin que ninguna prueba automatizada los detectara -- solo auditoría manual. Se prioriza
  empezar por los dos módulos más autocontenidos y de mayor impacto (sin dependencias externas,
  puro stdlib): `conocimiento_general.py` (la base de 436 entradas que alimenta el prompt del
  cerebro) y `chronic_tickets.py` (evita duplicar/perder tickets de alertas hacia Telegram).
  - `tests/conftest.py`: fixture que aísla cada test contra su propia `knowledge.db` temporal
    (nunca toca `/app/data/knowledge.db` real) vía `KNOWLEDGE_DB_PATH` + `importlib.reload`.
  - `tests/test_conocimiento_general.py` (17 pruebas): seed idempotente y con conteo correcto,
    integridad de campos (ningún campo vacío en las 436 entradas), dominios en snake_case,
    matching de dominios por marca (Bixolon/MikroTik/servidor), **prueba de regresión directa
    del bug real de "pc" haciendo falso positivo dentro de "recepcion"** (encontrado y corregido
    en v1.16.0), format_for_prompt no revienta sin seed y no fuerza contenido irrelevante,
    ciclo de aprendizaje confirmación/refutación incrementa el contador correcto.
  - `tests/test_chronic_tickets.py` (14 pruebas): no duplica tickets para la misma IP+fuente
    mientras siga abierto, sí distingue tickets de fuentes distintas para el mismo equipo,
    reabre un ticket nuevo si el anterior ya se cerró, cerrar dos veces el mismo ticket no
    revienta, list_open excluye cerrados y respeta orden de apertura.
  - **31/31 pruebas pasan** en la primera corrida -- validan que las correcciones aplicadas
    durante la auditoría del mismo día quedaron bien.
  - `pytest.ini`, `requirements-dev.txt` (pytest como dependencia SOLO de desarrollo, la imagen
    Docker de producción no la instala), `.gitignore` actualizado con `.venv-test/`.
  - Pendiente explícito, no resuelto hoy: cobertura de `brain.py` (requiere mockear OpenAI/Groq
    y las llamadas de verificación en vivo) y del resto de los ~35 módulos restantes de `core/`.
    Este commit es el punto de partida, no la cobertura completa.

## 1.20.1 — 2026-09-06

- **Unificación de la metodología de troubleshooting, pedida por Juan Pablo tras la auditoría**:
  existían dos marcos coexistiendo (A+ genérico de 6 pasos -- plan e implementación combinados --
  y Network+ N10-009 de 7 pasos -- separados), ambos oficiales pero potencialmente confusos
  dentro del dominio `metodologia` que el cerebro usa como respaldo genérico. Shomer ahora
  estandariza en UNA sola versión: la de 7 pasos (identificar → teorizar → probar → plan de
  acción → implementar o escalar → verificar → documentar), porque separar "planear" de
  "implementar o escalar" es justo la distinción que importa para un sistema que recomienda una
  acción pero no la ejecuta directamente -- el paso "o escalar" no existe en la versión combinada
  de A+.
  - Las 3 entradas que citaban "Metodología CompTIA A+ de 6 pasos" ahora citan "Metodología de
    troubleshooting de 7 pasos (estándar unificado de Shomer, CompTIA Network+ N10-009 — 5.1)".
  - Renumerado "paso 6" → "paso 7" en la entrada sobre por qué documentar no es opcional.
  - El concepto principal (antes "Los 7 pasos formales de troubleshooting de red (versión
    completa oficial)") ahora se titula "Los 7 pasos de troubleshooting (estándar unificado de
    Shomer)" y su explicación deja explícito por qué se eligió esta versión sobre la de A+.
  - Sin cambio en el total de entradas (436) -- unificación de citas/redacción, no contenido
    nuevo. Probado (seed + idempotencia) contra copia aislada antes de desplegar.

## 1.20.0 — 2026-09-06

- **Auditoría externa COMPLETA de las 436 entradas de la base de conocimiento** (no una muestra
  como en v1.19.1), pedida explícitamente por Juan Pablo: "audítalas todas". Se paralelizó en 8
  lotes (uno por certificación, Network+ dividido en dos por tamaño), cada uno verificando sus
  afirmaciones técnicas contra fuentes autorizadas reales (Microsoft Learn, Cisco, Fluke Networks,
  Ethernet Alliance/IEEE 802.3bt, RFC 3227, NIST SP 800-88, MITRE, Gartner, CompTIA -- incluyendo
  descargar de nuevo el PDF oficial de A+ Core 2 para verificar numeración exacta de sub-objetivos).
  - **Resultado: 397 de 436 confirmadas correctas sin cambios (91%). 39 entradas con algún
    hallazgo, las 39 corregidas.**
  - A+ Core 1: 65 revisadas, 1 corregida -- RAID 10 usaba el término "fragmentación" en vez de
    "striping" (segmentación en bandas); inconsistente con la entrada hermana que sí decía
    striping correctamente.
  - **A+ Core 2: 69 revisadas, 28 con hallazgo (el lote con más problemas).** 26 entradas tenían
    el CONTENIDO técnico correcto pero el número de sub-objetivo mal citado en `fuente` (ej.
    contenido de BitLocker/ediciones de Windows citado como "1.1" cuando es "1.3"; contenido de
    NTFS-vs-share citado como "2.4" cuando es "2.2"; toda la sección 4.x con los números
    desplazados en cascada). Corregidas las 26 citas por posición exacta en el archivo (no
    reemplazo global de texto, para no tocar citas de OTRAS entradas que sí tenían el número
    correcto). Además 2 errores de CONTENIDO real: el proceso de eliminación de malware SOHO
    tenía 7 pasos cuando la versión vigente del objetivo 2.6 (220-1202 V15) tiene 8 e incluye
    reimagen/reinstalación como paso independiente -- agregado; y el orden de volatilidad forense
    tenía la memoria RAM completa en primer lugar y las conexiones de red/procesos después,
    cuando RFC 3227 pone caché de CPU primero, luego tablas de enrutamiento/ARP/procesos, y
    RECIÉN DESPUÉS el volcado de RAM -- corregido al orden real de RFC 3227.
  - Network+ (lote A, cableado/PoE): 62 revisadas, 3 corregidas -- los nombres de "modo A" y
    "modo B" de PoE estaban invertidos respecto al estándar 802.3af/at (modo A = pares de datos,
    modo B = pares libres, no al revés); 802.3bt Tipo 4 decía 100W cuando el valor normativo
    IEEE es 90W en la fuente / 71.3W en el dispositivo; y una regla atribuía CRC crecientes a
    "TX/RX invertido" cuando esa falla causa ausencia total de enlace, no CRC crecientes -- la
    causa real y documentada es "split pair" (par dividido), corregida.
  - Network+ (lote B, enrutamiento/voz/arquitectura): 63 revisadas, 3 corregidas -- el orden de
    selección de ruta tenía la comparación de prefijo más específico subordinada al protocolo,
    cuando en realidad el longest-prefix-match manda SIEMPRE primero, sin importar distancia
    administrativa (corregido el orden real); la comparación de ancho de banda G.711 vs G.729
    mezclaba una cifra con overhead de red y otra sin él, exagerando el ahorro de G.729 de ~3x a
    ~8x (corregido con overhead consistente en ambos); y SASE/SSE se presentaban como sinónimos
    cuando SSE es un subconjunto de SASE sin el componente de red/SD-WAN (distinción agregada).
  - Security+: 40 revisadas, 0 con problemas. Server+: 33 revisadas, 1 corregida ("slipstreamed"
    y "unattended" tratados como sinónimos -- son técnicas distintas y complementarias,
    corregido). CySA+: 33 revisadas, 0 con problemas.
  - Contenido previo/curado (marcas reales de Ópera -- UniFi, MikroTik, Hikvision, ZKTeco,
    Ingenico, Epson, Bixolon): 71 revisadas, 3 corregidas -- tres entradas de metodología general
    citaban "7 pasos de CompTIA" cuando la versión A+ genérica (más comúnmente citada fuera del
    contexto de networking) combina plan de acción e implementación en un solo paso, dando 6 --
    corregido, y aclarado explícitamente en la cita que Network+ N10-009 sí usa una variante
    oficial de 7 pasos (objetivo 5.1, ya presente correctamente en una entrada separada del
    dominio `metodologia` específica de Network+, verificada y sin tocar).
  - Total sigue en 436 entradas -- todas las correcciones fueron de texto/cita, ninguna
    agregada ni eliminada. Probado (seed + idempotencia) contra copia aislada antes de desplegar.
  - **Con esta auditoría completa, la base de conocimiento pasa de "temario oficial cubierto sin
    verificar" a "temario oficial cubierto y verificado contra fuentes externas al 100% de sus
    entradas", con una tasa de acierto medida del 91% en la primera pasada y 100% tras aplicar
    las correcciones encontradas.**

## 1.19.1 — 2026-09-06

- **Primera auditoría externa de la base de conocimiento (436 entradas), pedida explícitamente por
  Juan Pablo tras aclarar que "cubrir el temario oficial" NO significa "tener las respuestas del
  examen"** -- el contenido lo escribió Claude desde su propio conocimiento técnico, usando el
  temario solo como checklist de cobertura, sin verificación externa entrada por entrada hasta
  ahora. Se auditaron 19 afirmaciones técnicas específicas y verificables (cifras exactas,
  fórmulas, comportamiento de protocolos), una muestra distribuida en las 6 certificaciones,
  contra fuentes autorizadas (documentación de Microsoft, Cisco, NIST SP 800-207, MITRE, CISA,
  IBM, TechTarget): RAID 5/6 tolerancia a fallos, NAS vs SAN (NFS/CIFS vs iSCSI/FC/FCoE), fórmulas
  SLE/ALE/ARO, tolerancia de reloj de Kerberos (5 min), límite de 2TB de MBR, esquema de rotación
  GFS, regla de backup 3-2-1, componentes de Zero Trust (NIST 800-207: Policy Engine/
  Administrator/Enforcement Point), cyber kill chain (7 fases), Diamond Model (4 vértices),
  BPDU Guard/err-disabled, password spraying vs fuerza bruta, honeypot/honeynet/honeyfile/
  honeytoken, TOC/TOU, componentes de CVSS, 802.1X/EAP, agotamiento de presupuesto PoE, y
  agotamiento de pool DHCP/APIPA.
  - **Resultado: 18 de 19 confirmadas exactas contra la fuente.**
  - **1 hallazgo real, corregido**: la entrada sobre ediciones de Windows (`sistemas_operativos`,
    A+ Core 2 — 1.1) decía que Windows Home "no incluye BitLocker" sin matizar que SÍ existe
    "Device Encryption" en equipos modernos compatibles (TPM 2.0 + Modern Standby) -- una versión
    automática y simplificada de la misma tecnología, ligada a la cuenta Microsoft, sin gestión
    granular. No era falso, pero podía inducir a error frente a un equipo Home que sí muestra
    cifrado activo. Corregida la explicación y la relevancia diagnóstica; la regla de diagnóstico
    asociada ya era correcta (hablaba de BitLocker completo con panel de control) y no requirió
    cambio.
  - Total sigue en 436 entradas (solo se corrigió texto, no se agregó ni quitó contenido).
  - Esto es una auditoría por MUESTRA, no exhaustiva -- de las 436 entradas se verificaron 19
    afirmaciones puntuales. Da una señal de confianza real (95% de aciertos en la muestra) pero
    no es garantía de que las 417 entradas restantes no tengan errores similares sin detectar.

## 1.19.0 — 2026-09-06

- **CySA+ (CS0-003) completo — SEXTO y último certificado del método exhaustivo (de 414 a 436
  entradas). Las 6 certificaciones de CompTIA mandatadas por Juan Pablo quedan cubiertas con el
  método de objetivos oficiales completos.** Descargado directamente del CDN oficial de CompTIA
  y leído el documento de objetivos (v1.0, 2022), los 4 dominios cubiertos: 1.0 Security
  Operations (33%), 2.0 Vulnerability Management (30%), 3.0 Incident Response Management (20%),
  4.0 Reporting and Communication (17%). Ya existía contenido curado de CySA+ desde v1.13.0 (14
  referencias) -- esta entrada agrega los fundamentos oficiales que faltaban, no reemplaza lo
  anterior.
  - Nuevos dominios: `inteligencia_amenazas` (threat intelligence: niveles de confianza,
    fuentes OSINT/cerradas, threat hunting proactivo, honeypot/defensa activa),
    `reportes_comunicacion` (inhibidores de remediación, métricas MTTD/MTTR/MTTRemediate,
    estructura de reporte por audiencia).
  - Ampliado: `siem_analisis` (indicadores de red/host/aplicación -- beaconing, P2P irregular,
    cambios de registro --, herramientas Wireshark/tcpdump/VirusTotal/sandboxing, SOAR y single
    pane of glass), `gestion_vulnerabilidades` (tipos de escaneo credenciado/pasivo/activo/
    fuzzing con consideraciones OT/ICS/SCADA, CVSS desglosado por componente, SSRF/LFI-RFI/
    broken access control/insecure design, prácticas de codificación segura), `respuesta_
    incidentes` (cyber kill chain de 7 fases, MITRE ATT&CK y Diamond Model, orden correcto de
    contención→erradicación→recuperación).
  - Total: 436 entradas (173 reglas + 263 teoría). Probado (seed + idempotencia + matching de
    dominios + format_for_prompt) contra copia aislada de la base real antes de desplegar.
  - **Con esta entrada se completa el mandato explícito de Juan Pablo del 5-6 sep 2026**: cubrir
    exhaustivamente el temario oficial completo de las 6 certificaciones CompTIA principales
    (A+ Core 1, A+ Core 2, Network+, Security+, Server+, CySA+), no una selección curada por
    criterio propio. Progresión total de la base de conocimiento en esta sesión: 47 entradas
    (v1.7.0, curado) → 436 entradas (v1.19.0, exhaustivo por objetivos oficiales).

## 1.18.0 — 2026-09-06

- **Server+ (SK0-005) completo — quinto certificado del método exhaustivo (de 389 a 414
  entradas).** Descargado directamente del CDN oficial de CompTIA y leído el documento de
  objetivos (v1.0, 2019), los 4 dominios cubiertos: 1.0 Server Hardware Installation and
  Management (18%), 2.0 Server Administration (30%), 3.0 Security and Disaster Recovery (24%),
  4.0 Troubleshooting (28%). Ya existía contenido curado de Server+ desde v1.13.0 (8 referencias)
  -- esta entrada agrega los fundamentos oficiales que faltaban, no reemplaza lo anterior.
  - Nuevo dominio: `almacenamiento` (RAID 0/1/5/6/10/JBOD y qué protege cada uno, NAS vs SAN,
    iSCSI/Fibre Channel/FCoE, fallas y reconstrucción de arreglos).
  - Ampliado: `servidor_administracion` (gestión fuera de banda iDRAC/iLO, tipos de instalación
    GUI vs Core, GPT vs MBR, clustering active-active/passive y heartbeat, licenciamiento
    per-core/per-socket y true-up, metodología de troubleshooting en 8 pasos, clock skew),
    `virtualizacion` (redes virtuales bridged vs NAT, vNICs, virtual switches),
    `gestion_documentacion` (ciclo de vida de activos, MTBF/MTTR/RPO/RTO), `control_acceso`
    (permisos scope-based, segregación de funciones), `seguridad` (integridad de dos personas),
    `seguridad_endpoint` (decomisionamiento correcto de servidores), `backup` (full/incremental/
    differential/synthetic full), `servidor_recuperacion_desastres` (replicación síncrona vs
    asíncrona).
  - Total: 414 entradas (166 reglas + 248 teoría). Probado (seed + idempotencia + matching de
    dominios + format_for_prompt) contra copia aislada de la base real antes de desplegar.
    Pendiente en el mismo método: CySA+ (CS0-003) -- último certificado, su contenido actual
    (desde v1.13.0) es curado, no exhaustivo.

## 1.17.0 — 2026-09-06

- **Security+ (SY0-701) completo — cuarto certificado del método exhaustivo (de 356 a 389
  entradas).** Descargado y leído el documento oficial de objetivos (v5.0, 2023), los 5 dominios
  cubiertos: 1.0 General Security Concepts (12%), 2.0 Threats/Vulnerabilities/Mitigations (22%),
  3.0 Security Architecture (18%), 4.0 Security Operations (28%), 5.0 Security Program
  Management and Oversight (20%). Ya existía contenido curado de Security+ desde v1.13.0 (8
  referencias, solo en `seguridad_arquitectura`) -- esta entrada agrega los fundamentos oficiales
  que faltaban, no reemplaza lo anterior.
  - Nuevos dominios: `criptografia` (PKI, simétrico/asimétrico, hashing/salting/key stretching),
    `gestion_riesgo` (SLE/ARO/ALE, estrategias transferir/aceptar/evitar/mitigar),
    `gobernanza_cumplimiento` (acuerdos SLA/MOU/MSA/NDA/BPA, tipos de pentest por entorno).
  - Ampliado: `seguridad` (categorías/tipos de controles, Zero Trust plano de control/datos,
    honeypot/honeynet/honeyfile/honeytoken, actores de amenaza y motivaciones, spraying vs
    fuerza bruta), `seguridad_endpoint` (taxonomía completa de malware -- worm vs virus, logic
    bomb, bloatware -- objetivos de hardening por tipo de dispositivo), `gestion_vulnerabilidades`
    (condiciones de carrera TOC/TOU, VM escape, ciclo completo identificación→validación),
    `siem_analisis` (impossible travel, concurrent session, out-of-cycle logging),
    `seguridad_arquitectura` (jump server/proxy/IDS vs IPS, tipos de firewall Layer4/WAF/NGFW/UTM,
    clasificación y estados de datos), `servidor_recuperacion_desastres` (sitios hot/warm/cold),
    `control_acceso` (MAC/DAC/RBAC/ABAC, PAM just-in-time/vaulting), `respuesta_incidentes` (las
    7 fases formales del proceso, forense digital/legal hold/e-discovery).
  - Total: 389 entradas (158 reglas + 231 teoría). Probado (seed + idempotencia + matching de
    dominios + format_for_prompt) contra copia aislada de la base real antes de desplegar.
    Pendiente en el mismo método: Server+, CySA+ -- su contenido actual (desde v1.13.0) es
    curado, no exhaustivo, y necesita su propio documento oficial de objetivos.

## 1.16.0 — 2026-09-06

- **A+ Core 2 (220-1202) completo — tercer certificado del método exhaustivo (de 315 a 356
  entradas).** Descargado y leído el documento oficial de objetivos (v4.0/V15, 2024), los 4
  dominios cubiertos: 1.0 Operating Systems (28%), 2.0 Security (28%), 3.0 Software
  Troubleshooting (23%), 4.0 Operational Procedures (21%). Ya existía contenido curado de A+
  Core 2 en `conocimiento_general.py` desde v1.13.0 (escenarios prácticos de Ópera) -- esta
  entrada AGREGA la base teórica/fundamentos oficiales que faltaba, no reemplaza lo anterior.
  - Nuevos dominios: `sistemas_operativos` (sistemas de archivos, ediciones de Windows,
    herramientas MMC, comandos CLI, Active Directory OU/GPO, comandos Linux).
  - Ampliado: `seguridad_endpoint` (BitLocker vs EFS, permisos NTFS vs share, taxonomía de
    malware, destrucción de datos), `seguridad` (Zero Trust/MFA/SSO/PAM, proceso de 7 pasos
    para eliminar malware, ingeniería social: vishing/smishing/whaling/pretexting, seguridad
    SOHO), `control_acceso` (capas físicas complementarias), `dispositivos_moviles` (MDM,
    hardening, keyword de matching agregado por primera vez), `backup` (esquema GFS + regla
    3-2-1), `gestion_documentacion` (change management formal), `metodologia` (cadena de
    custodia/orden de volatilidad, comunicación profesional, fundamentos de scripting, y una
    entrada nueva de CompTIA V15 sobre limitaciones de IA generativa -- sesgo, alucinaciones,
    privacidad -- que documenta explícitamente por qué el cerebro de Shomer nunca concluye sin
    verificación en vivo, ver `core/brain.py` Fase 3), `acceso_remoto` (RDP/VNC/SSH, riesgo de
    exposición directa a internet).
  - **Bug encontrado y corregido antes de desplegar**: la keyword `"pc"` agregada a
    `_DOMAIN_KEYWORDS["sistemas_operativos"]` producía falso positivo por coincidencia de
    substring dentro de palabras como "rece**pc**ion" (el matching es por substring, no por
    palabra completa). Se detectó probando `matching_domains(["Tablet Recepcion"])` contra la
    copia aislada antes de desplegar, y se corrigió quitando `"pc"` (dejando `laptop`/
    `notebook`/`workstation`, sin colisión conocida).
  - Total: 356 entradas (151 reglas + 205 teoría). Probado (seed + idempotencia + matching de
    dominios) contra copia aislada de la base real antes de desplegar. Pendiente en el mismo
    método: Security+, Server+, CySA+ -- su contenido actual (desde v1.13.0) es curado, no
    exhaustivo, y necesita su propio documento oficial de objetivos.

## 1.15.0 — 2026-09-06

- **Network+ (N10-009) completo — segundo certificado del método exhaustivo (de 272 a 315
  entradas).** Descargado y leído el documento oficial de objetivos (v6.0, 2023), los 5 dominios
  cubiertos punto por punto: 1.0 Networking Concepts (23%), 2.0 Network Implementation (20%),
  3.0 Network Operations (19%), 4.0 Network Security (14%), 5.0 Network Troubleshooting (24%).
  - Nuevos dominios: `enrutamiento` (FHRP/VIP/distancia administrativa), `ataques_red` (MAC
    flooding, ARP/DNS spoofing, evil twin, ingeniería social), `gestion_documentacion`
    (EOL/EOS, gestión de cambios/configuración), `acceso_remoto` (VPN sitio-a-sitio/túnel
    dividido, jump box, banda/fuera de banda).
  - Ampliado significativamente: `redes_ip` (tabla completa de puertos, CIDR/VLSM, tipos de
    tráfico), `switching` (topologías spine-leaf/3 capas, VLAN de voz, contadores de interfaz,
    estados de puerto, elección de root bridge STP), `wifi` (SSID/BSSID/ESSID, AP autónomo vs
    ligero), `dns_dhcp` (zonas primaria/secundaria, DoH/DoT), `seguridad_arquitectura` (IAM/
    RADIUS/LDAP/SAML/TACACS+, honeypot, 802.1X), `servidor_recuperacion_desastres` (MTTR/MTBF,
    activo-activo vs pasivo), `metodologia` (los 7 pasos oficiales completos, herramientas CLI).
  - Total: 315 entradas (133 reglas + 182 teoría). Probado antes de desplegar. Pendiente en el
    mismo método: A+ Core 2, Security+, Server+, CySA+.

## 1.14.0 — 2026-09-06

- **A+ Core 1 (220-1201) completo — primer paso de un trabajo multi-sesión pedido explícitamente
  por Juan Pablo: cubrir el temario oficial COMPLETO de las 6 certificaciones, no una selección
  curada por criterio propio.** Corrección de método real: en vez de escribir de memoria "lo que
  parece relevante", se descargó y leyó el documento oficial de objetivos de CompTIA (versión 2.0,
  2024) y se trabajó cada subtema listado, en orden, sin saltar ninguno.
  - Dominio 1.0 Mobile Devices (13% del examen) — antes casi sin cubrir: hardware reemplazable,
    métodos de conexión, MDM corporativo vs BYOD.
  - Dominio 2.0 Networking — huecos que faltaban: tabla de puertos TCP/UDP, TCP vs UDP, tipos de
    red por alcance (PAN/LAN/MAN/WAN/SAN), herramientas físicas de diagnóstico.
  - Dominio 3.0 Hardware — huecos que faltaban: tipos de pantalla, conectores de fibra (ST/SC/LC),
    RAM (SODIMM/DIMM/DDR/ECC), RAID 0/1/5/6/10 en profundidad, TPM/Secure Boot, especificaciones
    de fuente de poder, PCL vs PostScript, impresoras de impacto.
  - Dominio 4.0 Virtualization/Cloud — contenedores vs VMs, elasticidad/multitenencia.
  - **Dominio 5.0 Hardware and Network Troubleshooting (28%, el dominio más grande del examen)** —
    convertido íntegro en reglas de diagnóstico: síntomas de motherboard/RAM/CPU/energía, discos/
    RAID, video/proyectores, dispositivos móviles, red, e impresoras (specklng, imágenes eco,
    atascos de finalizador).
  - Total: 272 entradas (128 reglas + 144 teoría). Probado (siembra + idempotencia) antes de
    desplegar. Quedan pendientes, en el mismo método exhaustivo: Network+, A+ Core 2, Security+,
    Server+, CySA+ — se seguirá en próximas sesiones, sin apuro artificial.

## 1.13.0 — 2026-09-06

- **Security+, Server+ y CySA+ agregadas (de 212 a 238 entradas).** Ampliación pedida por Juan
  Pablo tras revisar qué certificaciones CompTIA faltaban. Dominios oficiales verificados con
  fuentes antes de escribir contenido (SY0-701: 5 dominios; SK0-005: 4 dominios; CS0-003: 4
  dominios). 7 dominios nuevos:
  - `seguridad_arquitectura` (Security+): defensa en profundidad, Zero Trust, superficie de ataque
  - `gestion_vulnerabilidades` (CySA+): CVSS en contexto, falsos positivos de escaneo, ventana
    de exposición — directamente aplicable a los hallazgos de `run_network_audit_scan`
  - `siem_analisis` (CySA+): IoC vs ruido de internet, correlación de eventos, threat hunting —
    conecta explícitamente con el principio que ya usa `brain.py` para correlacionar
  - `respuesta_incidentes` (Security+/CySA+): fases formales de respuesta — y se documentó que
    `incident_escalation.py` ya sigue este mismo patrón sin haberlo llamado así
  - `servidor_administracion` (Server+): clustering/HA, SAN/NAS, ventanas de mantenimiento
  - `servidor_recuperacion_desastres` (Server+): RTO/RPO, sitios fríos/tibios/calientes
  - Total: 238 entradas (111 reglas + 127 teoría) en 38 dominios de teoría / 34 de reglas.
  - Probado (siembra + idempotencia) contra copia aislada antes de desplegar.

## 1.12.0 — 2026-09-06

- **Fase 3 (verificación en vivo) y Fase 4 (cerrar el ciclo de aprendizaje) del plan de "ingeniero
  dentro del sistema".** Motivado por un hallazgo real de Juan Pablo: un evento de "offline" por
  sí solo no dice si la causa es cable, energía o algo puntual del equipo (ej. sensor de papel)
  — hasta ahora el cerebro daba una "suposición educada" disfrazada de diagnóstico.
  - **Fase 3 — `_verificar_en_vivo()`:** antes de concluir, el cerebro ahora comprueba el estado
    REAL del equipo en ese instante (no solo el historial): para impresoras usa el mismo chequeo
    ESC/POS que ya usa el chat (papel/tóner/error reales), para equipos Infra usa su estado SNMP/TCP
    actual, y como respaldo un ping en vivo. El prompt le da más peso a esta verificación que a
    una suposición genérica. Probado con la impresora Bixolon real: la respuesta pasó de adivinar
    "cable o alimentación" a decir explícitamente "reporta estar online en la verificación en
    vivo" cuando así era.
  - **Fase 4 — `registrar_confirmacion()`/`registrar_refutacion()`:** cada conclusión guarda qué
    dominios de conocimiento usó (`dominios_conocimiento`). Cuando un técnico cierra un pendiente
    que abrió el cerebro (confirmando que la causa era correcta), sube `veces_confirmado` en las
    reglas de esos dominios — el sistema empieza a acumular evidencia real de qué reglas aciertan
    más, no solo las usa a ciegas para siempre. Visible en `/conocimiento <dominio>` (contador de
    confirmado/refutado por regla).
  - Probado extremo a extremo antes de desplegar: ciclo completo con 2 switches → ticket abierto
    con dominios correctos (`cableado,switching`) → cierre del ticket → confianza subió de 0→1 en
    las 18 reglas de esos dominios, confirmado con datos reales, no simulado.

## 1.11.0 — 2026-09-06

- **Fase 2: la base de conocimiento técnico (212 entradas) queda conectada al razonamiento del
  cerebro.** Hasta ahora existía pero nadie la consultaba. `conocimiento_general.py` gana
  `find_relevant()`/`format_for_prompt()`: por cada grupo de eventos que analiza el cerebro,
  identifica qué dominios aplican según el **nombre real del equipo** (determinístico por
  palabra clave — "SW " → switching, "Bixolon" → impresoras térmicas POS, "MikroTik" → WAN,
  "ZK" → control de acceso, etc. — nunca decidido por el LLM, mismo principio anti-alucinación
  que `pattern_analysis.py`) y le agrega solo las reglas/teoría relevantes a ESE grupo, no las
  212 completas cada vez.
  - Probado contra los 8 tipos de equipo reales de Ópera: acertó el dominio correcto en los 8
    casos (switches, MikroTik, Bixolon, APs, Hikvision, ZKTeco, Ingenico, Epson).
  - Probado un ciclo completo end-to-end (evento real de impresora Bixolon) contra copia
    aislada antes de desplegar — funcionó correctamente.

## 1.10.0 — 2026-09-06

- **Dominios de marca real, basados en el inventario verificado de Ópera (de 180 a 212 entradas).**
  Pedido de Juan Pablo: ampliar dominios revisando los equipos reales del hotel, no suposiciones.
  Consultado `infra_devices` en vivo antes de escribir una sola regla — la mezcla real de marcas
  encontrada: UniFi (30 APs + switches EdgeSwitch), MikroTik (gateway), Cisco (otros switches),
  Bixolon (impresoras térmicas POS), **Epson WorkForce M5899 en recepción — inkjet comercial, no
  láser, un tipo no cubierto antes**, Hikvision (2 NVR + cámaras), ZKTeco (biométrico), Ingenico
  (2 datáfonos). 6 dominios nuevos específicos de estas marcas:
  - `unifi` (adopción de equipos, inform URL, interoperabilidad con Cisco)
  - `mikrotik` (orden de reglas en RouterOS, Winbox vs SSH, cadenas input/forward)
  - `hikvision` (P2P/nube vs acceso local, grabación continua vs detección de movimiento)
  - `zkteco` (modos RS485 vs TCP/IP, degradación de sensores de huella)
  - `ingenico` (fallback a canal de respaldo, segmentación PCI)
  - `impresoras_inkjet` (distinto de láser y térmica: cabezales, almohadilla de mantenimiento)
    + ampliación de `impresoras_termicas_pos` (sensor de papel, cortador automático)
  - Total: 212 entradas (101 reglas + 111 teoría) en 32 dominios de teoría / 28 de reglas.
  - Probado (siembra + idempotencia) contra copia aislada; tablas de producción limpiadas y
    resembradas en Ópera y los 3 labs para que el número real llegara, no solo el código.

## 1.9.0 — 2026-09-06

- **Expansión real de escala de la base de conocimiento — corrección sobre 1.8.0.** Juan Pablo
  (ingeniero de sistemas, 8 meses invertidos en el proyecto) marcó que 90 entradas seguía sin
  servir — confirmó explícitamente que el problema era de **escala**, no de forma: "necesito una
  cantidad de conocimiento real de nivel profesional, sin límite artificial de cuántas reglas
  escribo a mano". Se dedicó una sesión de trabajo extensa, sin acortar el alcance, a expandir:
  - **De 90 a 180 entradas** (85 reglas de diagnóstico + 95 conceptos de teoría).
  - **De 13 a 25 dominios distintos**, agregando los que faltaban por completo: seguridad de
    endpoints (EDR vs antivirus, ransomware/backups offline), direccionamiento IP/subnetting
    (incl. IPv6 básico), energía eléctrica en profundidad (tipos de UPS, transferencia a planta,
    factor de potencia), backup/recuperación (3-2-1, incremental vs diferencial, prueba de
    restauración), voz IP (SIP/RTP, códecs), cámaras/CCTV (ONVIF, ancho de banda), control de
    acceso (modo standalone, FRR/FAR), bases de datos (bloqueos, índices), Linux (systemd,
    permisos), cloud (SaaS/IaaS/PaaS, latencia), monitoreo/observabilidad (SNMP, falsos
    positivos/negativos), y ampliación real de PMS/hospitalidad (channel manager, llaves
    electrónicas, revenue management) y metodología (documentación, escalamiento, comunicación).
  - Sigue siendo, honestamente, una fracción de lo que sería una base "profesional completa"
    (que en la industria real son miles de artículos) — esto es un paso real y grande, no el
    final del camino. Seguirá creciendo en próximas sesiones de trabajo.
  - Probado (siembra + idempotencia) contra copia aislada antes de desplegar.

## 1.8.0 — 2026-09-05

- **`conocimiento_teoria` (nueva tabla) — corrección de escala sobre 1.7.0.** Juan Pablo señaló,
  con razón, que 47 reglas de diagnóstico eran "un manual de 2 páginas", no una base de
  conocimiento real para un ingeniero — y aclaró qué pedía: no enumerar cada marca de equipo,
  sino la **teoría de fondo** (protocolos, estándares, mecanismos) que permite razonar sobre
  cualquier equipo, de cualquier marca.
  - 43 conceptos teóricos con profundidad real (no una línea — explicación del mecanismo +
    por qué importa para el diagnóstico + fuente), en 13 dominios: cableado (categorías de
    cable, PoE, fibra, presupuesto óptico), switching (STP/RSTP, BPDU guard, 802.1Q, duplex
    mismatch, LACP, storm control), WAN (NAT/PAT, MTU, QoS, DNS), WiFi (canales, roaming
    802.11k/v/r, MIMO/OFDMA, DFS), hardware (RAID, SMART, UPS), impresoras (térmica, puerto
    9100), seguridad (ARP spoofing, DHCP starvation, PCI-DSS), Windows/AD (Kerberos, FSMO,
    GPO), integración PMS/POS, virtualización, dispositivos móviles, sistemas operativos, y
    metodología (OSI como marco de diagnóstico).
  - Comando `/conocimiento teoria <dominio>` para revisar la teoría separada de las reglas de
    diagnóstico rápido.
  - Total combinado: 90 entradas (47 reglas + 43 conceptos), sembradas de forma idempotente
    (probado dos veces antes de desplegar).

## 1.7.0 — 2026-09-05

- **`conocimiento_general` (nuevo, Fase 1 del plan de "ingeniero dentro del sistema").** Pedido de
  Juan Pablo: además del aprendizaje propio del sitio (`agente_skills`), sembrar una base de
  conocimiento técnico validado y **genérico** — útil desde el día 1 en cualquier cliente nuevo,
  no solo después de acumular incidentes propios. Investigado con fuentes externas antes de
  escribir una sola regla (no inventado): CompTIA Network+ (N10-009), CompTIA A+ Core 1
  (220-1201) y Core 2 (220-1202), hallazgos reales de integración PMS↔POS en la industria
  hotelera (Shiji Insights, BringIT), y problemas documentados en comunidad técnica al mezclar
  marcas de red distintas (MikroTik + UniFi).
  - Nueva tabla `conocimiento_general` en `knowledge.db`: 47 reglas sembradas en 10 dominios
    (cableado, PoE, switching, WAN, WiFi, hardware/servidores, impresoras/POS, seguridad,
    Windows/AD, integración PMS/POS) + metodología general. Cada regla queda con su fuente y
    "aprobado_por" — nada entra como validado sin trazabilidad.
  - Comando nuevo `/conocimiento [dominio]` para revisarla directo en Telegram.
  - Siembra automática una sola vez al arrancar (`seed_if_empty`, idempotente — probado dos
    veces seguidas antes de desplegar, no duplica).
  - **Todavía NO conectado al razonamiento del cerebro** — eso es la Fase 2, pendiente de
    aprobación explícita antes de tocarlo (así se acordó en la sesión).

## 1.6.0 — 2026-09-04

- **`watch_poller_heartbeat` (nuevo).** Juan Pablo pidió auditar 4 documentos de "auditoría"
  antes de decidir si eran basura o no. Revisado contra el código real: 2 eran informes
  cerrados (archivados en `network_monitor/docs/archivo/`), pero **2 resultaron ser un plan de
  trabajo real, parcialmente implementado** (`AUDITORIA_POLLERS_CONSOLIDADA.md`). Uno de sus
  puntos (Fase D.1, jun 2026) proponía que Guardian e Infra escribieran un heartbeat en Redis
  cada ciclo y que "un monitor externo" avisara si dejaba de actualizarse — **la escritura se
  hizo, el monitor externo nunca se construyó**. Este watcher completa esa pieza: revisa
  `guardian:poller:last_ok` e `infra:poller:last_ok` cada 60s; si una de esas claves expira
  (el poller lleva colgado más de 4x su intervalo normal — congelado, no caído, que es
  precisamente el caso que systemd `Restart=on-failure` no detecta), avisa por Telegram, y
  avisa también cuando se recupera. Probado contra Redis real antes de desplegar: ambas claves
  vivas y con TTL correcto.

## 1.5.1 — 2026-09-04

- **Corrección sobre 1.5.0: se quitaron los 2 documentos de campo del conocimiento del cerebro/chat.**
  Al revisarlos completos con Juan Pablo, resultaron ser tareas fechadas para una persona
  (`OPERA-VISIBILIDAD-CAPA2-RICARDO.md`: "activa SNMP en estos switches", ya hecho hace meses;
  `REVISION-EN-SITIO-OPERA.md`: foto de equipos caídos el 8 jul 2026, ya no vigente) — ruido
  viejo, no conocimiento permanente. Queda solo `EQUIPOS.md` (arquitectura del sitio: VLANs,
  tipo de firewall, excepciones Hunter — no vive en ninguna tabla). La topología física
  (qué switch alimenta qué zona) no necesitaba documento: ya vive correcta y actualizada en
  `infra_devices.location` de la base de datos en vivo.

## 1.5.0 — 2026-09-04

- **Conocimiento operativo real conectado al chat y al cerebro.** Juan Pablo señaló que había
  documentación real (no código) que fue guardando con el tiempo pero que la IA nunca leía:
  `EQUIPOS.md` (inventario de los 4 servidores con lecciones reales sobre verificar antes de
  afirmar) y dos notas de visitas en sitio dirigidas a personas reales (Ricardo Romero, Cristian
  Romero) — revisado y confirmado: **el cerebro no leía ni siquiera `SITE.md`**, que el chat sí
  usa desde antes. Cambios:
  - `docker-compose.yml`: nuevos montajes de solo lectura para `EQUIPOS.md` y los 2 documentos
    de campo (mismo patrón que `SITE.md`).
  - `agente_skills.py`: nueva `load_operational_docs()` (cada documento con su propio tope de
    caracteres) sumada a `get_learning_context()` — el chat se beneficia automáticamente.
  - `brain.py`: ahora carga `SITE.md` + estos documentos **una vez por ciclo** (no por cada
    hallazgo) y se los pasa al modelo de razonamiento como contexto real del sitio — antes
    razonaba solo con datos crudos de la BD, sin las "mañas conocidas" del hotel.
  - **Nota importante:** cambiar `docker-compose.yml` requiere recrear el contenedor
    (`sudo systemctl restart shomer-agent`, que internamente hace `docker compose up`), un
    `docker restart` simple NO aplica montajes nuevos.

## 1.4.0 — 2026-09-04

- **Protagonismo real del cerebro — pedido explícito de Juan Pablo tras ver que, aunque
  funcionaba, "sigue siendo un punto aparte, debería ser algo central".** Evidencia concreta
  que motivó esto: el incidente real del rack (15:36) generó 1 mensaje del cerebro + 6 avisos
  sueltos idénticos de `equipos_red` sobre los mismos equipos — el cerebro tenía la explicación
  correcta pero cero autoridad sobre el ruido a su alrededor. Cambios:
  - **`/pendientes` y el sistema de tickets ya existente pasan a ser el hogar real del cerebro.**
    Un hallazgo de 2+ equipos con urgencia alta abre un pendiente de verdad (`chronic_tickets`,
    `fuente='cerebro'`) — aparece en `/pendientes` junto a los tickets de Guardian/Infra, no en
    un comando aparte que hay que acordarse de escribir.
  - **`recently_covered(ip)`**: si un equipo ya salió en un hallazgo del cerebro en los últimos
    20 min, `watch_infra` ya no repite el aviso completo — manda una referencia corta ("ya
    explicado por el 🧠 cerebro, ver /pendientes #N") en su lugar. Aplica tanto a caídas nuevas
    como a recuperaciones.
  - **`BRAIN_INTERVAL_MIN` 20 → 5 minutos** — reacciona mucho más cerca del tiempo real.
  - **Visible en los reportes que ya se leen a diario**: `/salud` muestra el hallazgo más
    reciente arriba de todo; `daily_summary` y `evening_summary` incluyen una sección "🧠
    Cerebro" con lo encontrado ese día — sin tener que escribir `/cerebro`.
  - **Bug real encontrado al probar antes de desplegar:** abrir el ticket desde dentro de la
    misma transacción de `sqlite3` que grababa la conclusión producía `database is locked`
    (dos conexiones de escritura simultáneas al mismo archivo). Corregido separando el commit
    de la conclusión del paso de abrir el ticket. Reprobado extremo a extremo: hallazgo de 3
    equipos con urgencia alta → ticket abierto correctamente, visible junto a los tickets reales
    existentes, y `recently_covered()` lo encuentra por IP.

## 1.3.1 — 2026-09-04

- **Fix real encontrado en producción a los pocos minutos de desplegar el cerebro (1.3.0):**
  un incidente real (MikroTik gateway degradado → 30 eventos de switches/NVRs/cámaras/POS/
  terminales de pago cayendo juntos, ciclo 08:07) se perdió en silencio — el payload se cortaba
  con `[:4000]` caracteres a ciegas antes de mandarlo al modelo, rompiendo el JSON de entrada y
  produciendo una respuesta también truncada. Corregido acotando eventos/entidades por
  **cantidad** (nunca por caracteres), subiendo `max_tokens` 700→900 e instrucción explícita de
  brevedad. Reprobado contra el mismo evento real: ahora genera el hallazgo correcto ("fallo
  temporal del MikroTik Router — reiniciar remoto primero", urgencia alta). Ver `core/brain.py`.

## 1.3.0 — 2026-09-04

- **Cerebro unificado (`core/brain.py`).** Pedido explícito de Juan Pablo: "el sistema
  está bien pero está suelto, no es un conjunto con cerebro propio". Hasta hoy cada
  sistema (Guardian/Hunter/Infra/pattern_analysis/chronic_tickets) decidía y avisaba
  por su cuenta sin ver el cuadro completo. `watch_memoria_sync` ya unificaba
  Guardian+Infra+auto_task en una bitácora común (`memoria_incidentes`) con la intención
  explícita (ver su docstring) de que "todo el razonamiento futuro" leyera de ahí — pero
  nada lo hacía. El cerebro es esa pieza:
  - `memoria_central.py`: nueva sincronización de Hunter (`blocked_ips` → `memoria_incidentes`,
    antes corría aparte y nunca entraba a la bitácora común).
  - `brain.py`: cada 20 min (`BRAIN_INTERVAL_MIN`) agrupa eventos nuevos por **proximidad
    temporal sin importar el sistema de origen** (a diferencia de `pattern_analysis.py`, que
    agrupa por entidad individual y nunca cruza sistemas) — así detecta, por ejemplo, varios
    equipos caídos juntos por una causa común en vez de tratarlos como problemas separados.
    Cruza cada equipo del grupo con su aprendizaje real (`agente_skills`: éxitos/fallos de
    remediaciones previas, patrón crónico, ticket abierto) — aprendizaje **activo** como
    insumo de la decisión, no solo contexto pasivo pegado al chat. Le pide a un modelo de
    razonamiento (`BRAIN_MODEL`) una causa raíz + recomendación respaldada en esa evidencia
    (nunca inventada — los conteos los calcula código, igual que `pattern_analysis.py`).
    Nunca reemplaza las alertas existentes: es una capa adicional que solo interrumpe por
    Telegram con urgencia media/alta, para no sumar ruido. Fallback automático a Groq si
    OpenAI no responde (probado apagando la key). Nuevas tablas `brain_conclusions` y
    `brain_state` en `knowledge.db`.
  - Comando nuevo `/cerebro` (`/cerebro ahora` fuerza un análisis manual).
  - Probado extremo a extremo contra datos reales de producción (copia aislada, sin tocar
    la BD viva): agrupó correctamente 2 APs caídos con 2 min de diferencia, los separó de un
    bloqueo Hunter 35 min después, y generó una recomendación citando el historial real
    (ej. "reinicio remoto funcionó 100% de las veces anteriores").
  - Nota honesta: `BRAIN_MODEL` quedó en `gpt-4o-mini` porque el proyecto OpenAI actual no
    tiene habilitado `gpt-4o` (403 model_not_found, confirmado en prueba real) — para el
    salto de calidad que pidió Juan Pablo ("pagar otra IA") falta solo habilitarlo en
    platform.openai.com y cambiar una variable, sin tocar código.

## 1.2.0 — 2026-09-03

- **Sistema de "pendientes" (tickets) conectado al patrón crónico.** Antes, un equipo
  reconocido como crónico (opción 3) simplemente dejaba de avisar para siempre. Ahora:
  al reconocerse como crónico se abre un pendiente (aviso único), y se recuerda 3 veces al
  día (10am/3pm/8pm, `chronic_tickets_reminder`) hasta que el técnico lo **cierre** (se
  resolvió de verdad) o lo **pause** (ej. esperando un repuesto — reusa el mismo mecanismo
  de `/silenciar`, 3 días por defecto vía botón, o duración personalizada por comando).
  Comando nuevo `/pendientes` para verlos todos on-demand. Nueva tabla `chronic_tickets` en
  `knowledge.db`, módulo `core/chronic_tickets.py`.
- **Fix: aviso duplicado de Hunter.** Cada bloqueo de Wazuh generaba dos mensajes — uno
  instantáneo de network_monitor (vía la cola) y otro del bot ~1 min después (su propio
  polling). Ahora el bot recuerda qué IPs ya se avisaron por la vía directa y no las repite.
- **Fix: hueco real encontrado en auditoría — el aviso de "falló el reinicio" (network_monitor,
  directo) no respetaba el patrón crónico.** Un equipo ya reconocido como crónico por el bot
  (ej. AP PASILLO HAB 701-702, 17 ocurrencias desde junio) igual interrumpía por este camino
  aparte. Corregido en `network_monitor/app/api/shomer_guardian_nodes.py` — mismo criterio y
  umbral que usa el bot, leyendo `knowledge.db` de solo lectura.

## 1.1.9 — 2026-09-03

- **Usar el aprendizaje acumulado (`agente_skills`) en más lugares**, no solo como contexto
  invisible de la IA: `/diagnostico <ip>` y `/criticidad <ip>` ahora muestran el historial de
  soluciones ya confirmadas para ese equipo; el resumen matutino agrega una sección de
  "patrones confirmados" (equipos con 3+ arreglos remotos confirmados — candidatos a revisión
  física, no solo celebrar que el auto-fix funciona). Se descartó explícitamente cualquier
  skill ligada a una TASK-* automática (ej. auditoría de backups) para no confundir una tarea
  rutinaria exitosa con un equipo que sigue fallando.
- **Fix: el resumen matutino podía mandarse dos veces** si el bot se reiniciaba justo dentro de
  la ventana 07:00-07:02 (pasó hoy mismo, en vivo, desplegando este mismo cambio). El día del
  último envío ahora se guarda también en disco (`bot_state` en `knowledge.db`), no solo en
  memoria — sobrevive a un reinicio. Mismo fix aplicado al resumen de las 22:00.

## 1.1.8 — 2026-09-03

- **UX del bot: más fácil de usar sin memorizar comandos** (pedido Juan Pablo tras revisar el
  estado del bot). Cuatro cambios:
  1. Botones "🔍 Ver detalle" en las listas de `/equipos` e `/infra` para cada equipo con
     problema — ya no hay que copiar la IP a mano para diagnosticar.
  2. Comando `/menu` — botones grandes por categoría (WiFi, Infra, Seguridad, Servidor,
     Reporte, Ayuda), navegación sin escribir nada.
  3. Teclado fijo de accesos rápidos (Salud, Equipos, Alertas, Menú) que aparece tras el primer
     saludo o `/ayuda` y queda pegado abajo del chat.
  4. `/start` — no existía; alguien nuevo que tocaba "Iniciar" en Telegram no recibía nada.
     También se reforzó el texto libre como primera opción en `/ayuda` (antes la lista de
     comandos aparecía antes que la opción de simplemente preguntar).

## 1.1.7 — 2026-09-03

- **Resumen matutino: backup + inventario, y limpieza de comentarios editoriales.**
  Se agregó backup local + última subida a B2 (Protector) y último inventario (Tracker) al
  resumen de las 07:00. `app/api/backups.py` (network_monitor) ahora guarda
  `protector.last_b2_sync_at` al terminar el sync — antes esa confirmación solo se mandaba por
  Telegram y no quedaba en ningún lado consultable.
  Se quitaron 3 comentarios editoriales que se habían colado en el texto de reportes reales
  ("nunca se liberan solas", explicación de MAC-reconcile, instrucciones de `ethtool` en el
  mensaje de NIC) — un reporte debe traer datos limpios, no explicaciones del asistente. La
  línea de Hunter ahora trae la fecha de la IP bloqueada más antigua, en vez de solo un número
  sin contexto temporal.
- **Bot de Telegram: 3 mejoras pedidas tras revisar el estado del bot.**
  1. Se quitaron 21 alias legacy (`shomer_*`, `guardian_*`, `hunter_*`, `infra_*`,
     `instalar_*`) que duplicaban comandos ya existentes sin aportar nada — quedan los nombres
     cortos y los alias genuinamente útiles (`/diag`, `/reiniciar`, `/mantenimiento`,
     `/autobloqueo`).
  2. `/revertir` ahora también deshace cambios de modo mantenimiento y de tipo de equipo
     (antes solo bloqueos/desbloqueos de Hunter y agregar/quitar equipo).
  3. Comando nuevo `/criticidad <ip> [tipo]` — ver o cambiar el tipo/criticidad de negocio de
     un equipo Infra desde Telegram (antes solo desde el panel web), reutilizando el endpoint
     `PATCH /infra/devices/{id}` de la Tarea pendiente 2 opción 4.

## 1.1.6 — 2026-09-02

- **Telegram separado por hotel/cliente, nunca compartido:** se encontró que shomer243 y
  shomer245 usaban el mismo bot que shomer205 (clonado por `fleet_sync.sh` sin regenerar
  token), y los 4 sitios (Ópera incluida) mandaban a un mismo chat personal. Se crearon 3 bots
  nuevos vía BotFather y 4 grupos de Telegram separados, cada uno verificado con mensaje de
  prueba real antes de dar por hecho el cambio.
- **Tarea pendiente 2 (parte 2), opciones 1, 3 y 4** (`core/monitor.py`, commits `0f7fb28` y
  `c9e7e1e`): completa el trabajo de la 1.1.4 (que solo registraba, no cambiaba nada).
  - Opción 1: si el auto-reboot de Guardian funciona, ya no interrumpe (solo si sigue caído
    a los 3 min).
  - Opción 3: patrón crónico (5+ ocurrencias) deja de interrumpir en tiempo real — antes solo
    acortaba el texto del mensaje, ahora no manda nada, queda en `eventos_filtrados`.
  - Opción 4 (solo Inframonitor): criticidad de negocio por `device_type` —
    `pos`/`router`/`server`/`controller`/`switch` avisan ya; `printer` no-POS y `camera`
    esperan al resumen. Configurable con `INFRA_CRITICAL_DEVICE_TYPES`. Incluye fix de
    consistencia: la recuperación de un equipo cuya caída se silenció tampoco avisa (antes
    hubiera mandado un "recuperado" de algo que nunca se avisó como caído).
  - Opción 2 evaluada y descartada — se solapaba con 3+4+6 y aplicarla tal cual habría
    apagado el aviso inmediato de un router/gateway caído, que la opción 4 marca como crítico.
  Ver `PENDIENTES_LAB.md` § Tarea pendiente 2 para el detalle completo de las 6 opciones.

## 1.1.5 — 2026-08-27

- **Fix: `pattern_analysis` perdía hallazgos por JSON truncado** (`core/pattern_analysis.py`):
  el LLM cortaba la respuesta a mitad de un array JSON (~4 veces/24h en producción) y se
  descartaba el lote completo. `_salvage_truncated_json_array()` nuevo rescata los objetos ya
  completos antes del corte, en vez de perderlos todos. También se acortó el prompt para
  reducir la frecuencia del corte.
- **Fix: `/agregar` crasheaba en silencio con puerto no numérico** (`core/bot.py`,
  `cmd_agregar`): faltaba validar `args[3]` antes de `int(args[3])` — el error solo quedaba en
  logs, sin respuesta al usuario en Telegram. Ahora responde con el error claro antes de
  intentar convertir.

## 1.1.4 — 2026-08-16

- **Tarea pendiente 2 (parte 1):** nueva tabla `eventos_filtrados` en
  `knowledge.db` + `incident_escalation.record_filtered_event()` — registra
  cada "recuperado" que se suprime por `is_flapping` (3 puntos en
  `monitor.py`: Guardian y las 2 rutas de recuperación de Inframonitor), sin
  tocar la decisión de avisar (diff solo agrega líneas). Objetivo: separar
  "qué pasó" de "si se avisó" para auditar después sin reconstruir logs a
  mano. Ver `PENDIENTES_LAB.md` § Tarea pendiente 2. Complementa el registro
  del lado de network_monitor (blip gateway/masivo) hecho el mismo día.

## 1.1.3 — 2026-08-13

- **`watch_infra` ahora usa escalamiento crónico (paso 5 del mapa)** — hasta
  ahora esta protección solo la tenía Guardian (wifi); switches, impresoras,
  cámaras y datáfonos mandaban un mensaje completo por cada caída de un
  mismo equipo flapeando, sin agrupar (el mismo problema que tuvo OFC-COCINA
  en Guardian, Sesión 71, pero nunca arreglado del lado de Inframonitor).
  `core/monitor.py::watch_infra`: la caída individual (no-oleada) ahora pasa
  por `incident_escalation.handle_event()`; las dos rutas de recuperación
  individual ahora chequean `is_flapping()` antes de avisar "recuperado".
  No toca la detección de oleada (Pulse Correlate) — eso ya agrupaba bien.

## 1.1.2 — 2026-08-13

- **Solo comentarios, sin cambio de comportamiento.** Se agregaron marcas
  "Mapa de decisión de alertas (CLAUDE.md), paso N" en `core/monitor.py`
  (chequeo de patrón crónico paso 7, `incident_escalation`/`is_flapping`
  pasos 5-6) y en el docstring de `core/incident_escalation.py` — para que
  el código mismo indique en qué parte del mapa está cada pieza, en vez de
  tener que reconstruir el orden leyendo 3 archivos cada vez. Pedido
  explícito de Juan Pablo tras revisar 2 meses de ajustes de sensibilidad.

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
