"""conocimiento_general -- base de conocimiento tecnico VALIDADO, generico
para cualquier cliente (no especifico de Hotel Opera).

Distinto de agente_skills.py (aprendizaje PROPIO de este sitio, por equipo
especifico: "el AP .140 se arreglo con reinicio 4 veces"). Esto es lo que
cualquier ingeniero de soporte con experiencia ya sabe de redes, hardware,
software y sistemas de hospitalidad -- util desde el primer dia en un sitio
nuevo, antes de que acumule su propio historial.

Fuentes (sesion 81 cont., 4 sep 2026, investigado con Juan Pablo antes de
sembrar -- no inventado):
  - CompTIA Network+ (N10-009): cableado, switching, WAN, WiFi, metodologia
  - CompTIA A+ Core 1 (220-1201): hardware, dispositivos moviles, nube/virt.
  - CompTIA A+ Core 2 (220-1202): sistemas operativos, seguridad, software
  - Industria hotelera (Shiji Insights, BringIT): fallas reales de
    integracion PMS<->POS -- "conectado" en pantalla no implica que el flujo
    de datos real funcione, hay que probar con una transaccion real
  - Comunidad tecnica (foros MikroTik/UniFi): incompatibilidades documentadas
    reales al mezclar esas marcas (VLAN/trunk)

Cada regla queda con `aprobado_por` -- nada entra como "validado" sin
aprobacion humana, para que la IA nunca "aprenda" algo falso como si fuera
universal. El campo `confianza` sube/baja con el tiempo segun se confirme o
no en la practica (mecanismo de retroalimentacion -- fase futura, no
implementada aun: hoy solo se siembra y se puede consultar).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Optional

log = logging.getLogger("shomer-conocimiento-general")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")


def init_db_teoria() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conocimiento_teoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dominio TEXT NOT NULL,
                concepto TEXT NOT NULL,
                explicacion TEXT NOT NULL,
                relevancia_diagnostica TEXT NOT NULL,
                fuente TEXT NOT NULL,
                aprobado_por TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_teoria_dominio ON conocimiento_teoria(dominio)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("conocimiento_teoria init: %s", e)


def init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conocimiento_general (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dominio TEXT NOT NULL,
                patron TEXT NOT NULL,
                causa_probable TEXT NOT NULL,
                recomendacion TEXT NOT NULL,
                fuente TEXT NOT NULL,
                confianza TEXT DEFAULT 'alta',
                veces_confirmado INTEGER DEFAULT 0,
                veces_refutado INTEGER DEFAULT 0,
                aprobado_por TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_conocimiento_dominio ON conocimiento_general(dominio)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("conocimiento_general init: %s", e)


# ── Semilla -- conocimiento validado, generico, sin nada especifico de Opera ──

_SEED_TEORIA: list[dict[str, str]] = [
    # ══════════════════════ CABLEADO Y CAPA FÍSICA ══════════════════════
    dict(dominio="cableado", concepto="Categorías de cable UTP/STP y sus límites reales",
         explicacion=(
             "Cat5e certifica hasta 100MHz y 1Gbps a 100m. Cat6 certifica 250MHz y soporta "
             "10Gbps pero solo hasta 37-55m (no los 100m completos) por el aumento de "
             "diafonía a esa velocidad; a 100m completos Cat6 solo garantiza 1Gbps. Cat6a "
             "certifica 500MHz y sí sostiene 10Gbps a 100m completos, con mejor blindaje "
             "contra crosstalk alien (entre cables adyacentes, no solo dentro del mismo)."
         ),
         relevancia_diagnostica=(
             "Si un enlace Cat6 de 90-100m no alcanza 10Gbps mientras uno de 30m sí, no es "
             "una falla — es el cable operando dentro de su límite real de categoría/distancia. "
             "No se soluciona cambiando electrónica, se soluciona con Cat6a o acortando el tramo."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Diafonía (crosstalk): NEXT vs FEXT",
         explicacion=(
             "NEXT (Near-End Crosstalk) mide la interferencia entre pares medida en el mismo "
             "extremo donde se inyecta la señal — el problema más común en terminaciones mal "
             "hechas. FEXT (Far-End Crosstalk) se mide en el extremo opuesto y es menos crítico "
             "en distancias cortas. Un certificador de cable mide ambos; un simple tester de "
             "continuidad no detecta ninguno de los dos."
         ),
         relevancia_diagnostica=(
             "Un cable que 'hace ping' pero tiene errores intermitentes bajo carga real puede "
             "tener NEXT alto por una terminación descrenchada (pares destrenzados más de lo "
             "permitido en la punta) — un tester de continuidad barato no lo va a mostrar, "
             "hace falta un certificador real o simplemente reterminar el conector."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Fibra óptica: monomodo vs multimodo",
         explicacion=(
             "Monomodo (SMF, núcleo ~9 micras) usa láser y transmite un solo modo de luz — "
             "alcanza decenas de kilómetros, es el estándar para enlaces largos entre edificios. "
             "Multimodo (MMF, núcleo 50 o 62.5 micras) usa LED o VCSEL, más barato, pero la "
             "dispersión modal limita el alcance a cientos de metros (OM3/OM4 llegan más lejos "
             "que OM1/OM2 a igual velocidad)."
         ),
         relevancia_diagnostica=(
             "Conectar un transceptor monomodo a fibra multimodo (o viceversa) no destruye el "
             "equipo pero el enlace simplemente no sube o tiene errores masivos — antes de "
             "sospechar del switch, confirmar que el tipo de transceptor coincide con el tipo "
             "de fibra instalada."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Presupuesto de pérdida óptica (dB budget)",
         explicacion=(
             "Cada conector, empalme y metro de fibra atenúa la señal en dB. Un enlace tiene un "
             "presupuesto máximo de pérdida (definido por el transceptor) — si la suma de "
             "pérdidas de todos los componentes lo supera, el enlace falla o tiene errores "
             "aunque físicamente 'esté conectado'."
         ),
         relevancia_diagnostica=(
             "Un enlace de fibra que funcionaba y empezó a fallar tras un cambio de patch cord "
             "o un empalme nuevo — sospechar de un conector sucio o mal pulido antes que del "
             "transceptor; limpiar los conectores ópticos es el primer paso, no reemplazar."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Estándares PoE y sus clases de potencia",
         explicacion=(
             "802.3af (PoE) entrega hasta 15.4W en la fuente, ~12.95W disponibles en el "
             "dispositivo tras pérdida en el cable. 802.3at (PoE+) sube a 30W/25.5W. 802.3bt "
             "(PoE++) tipo 3 llega a 60W y tipo 4 a 100W, pensado para APs WiFi6 de alta "
             "potencia, PTZ de cámaras y pantallas. Cada dispositivo se anuncia en una 'clase' "
             "(0 a 8) que le dice al switch cuánta energía reservarle."
         ),
         relevancia_diagnostica=(
             "Un switch con PoE+ (30W por puerto) puede tener suficiente potencia POR PUERTO "
             "pero no suficiente potencia TOTAL si se satura con muchos equipos a la vez — el "
             "presupuesto total del switch es finito, no solo el de cada puerto individual."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ SWITCHING (CAPA 2) ══════════════════════
    dict(dominio="switching", concepto="Spanning Tree Protocol: por qué existe y cómo elige rutas",
         explicacion=(
             "STP (802.1D) evita loops de broadcast eligiendo un 'root bridge' (el switch con "
             "menor Bridge ID = prioridad + MAC) y calculando la ruta más corta de cada switch "
             "hacia él, bloqueando enlaces redundantes. La convergencia clásica de STP tarda "
             "30-50 segundos (estados listening→learning→forwarding). RSTP (802.1w) reduce esto "
             "a segundos usando roles alternativos pre-calculados."
         ),
         relevancia_diagnostica=(
             "Si toda la red se cae por 30-50 segundos cada vez que se conecta o desconecta un "
             "cable redundante, es STP clásico recalculando — la solución no es 'arreglar' nada, "
             "es migrar a RSTP si el hardware lo soporta."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="BPDU Guard, Root Guard y PortFast",
         explicacion=(
             "PortFast salta los estados de espera de STP en puertos de acceso (donde se sabe "
             "que no habrá otro switch conectado), permitiendo que un PC se conecte y tenga red "
             "de inmediato. BPDU Guard apaga automáticamente un puerto PortFast si detecta "
             "tráfico BPDU (señal de que alguien conectó un switch no autorizado ahí). Root "
             "Guard evita que un puerto se convierta en el camino hacia un nuevo root bridge no "
             "autorizado."
         ),
         relevancia_diagnostica=(
             "Un puerto de PC que de repente queda 'err-disabled' casi siempre es BPDU Guard "
             "reaccionando a que alguien conectó un switch/router doméstico ahí sin autorización "
             "— no es una falla del puerto, es una protección funcionando como debe."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Etiquetado 802.1Q y el riesgo de la VLAN nativa",
         explicacion=(
             "Un trunk 802.1Q agrega una etiqueta de 4 bytes a cada trama para identificar su "
             "VLAN. La 'VLAN nativa' es la única que viaja SIN etiqueta por el trunk — si ambos "
             "extremos no tienen configurada la MISMA VLAN nativa, el tráfico de esa VLAN puede "
             "terminar mezclado con otra (y en el peor caso, permite un ataque de doble "
             "etiquetado / VLAN hopping)."
         ),
         relevancia_diagnostica=(
             "Tráfico de una VLAN apareciendo donde no debería, entre switches de marcas "
             "distintas, es casi siempre un desajuste de VLAN nativa entre ambos extremos del "
             "trunk — revisar ambos, no solo uno."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Duplex mismatch: por qué el ping funciona pero todo va lento",
         explicacion=(
             "Si un extremo de un enlace queda en half-duplex (por autonegociación fallida) y "
             "el otro en full-duplex, ICMP (ping) básico puede funcionar perfecto porque el "
             "tráfico es mínimo y no genera colisiones — pero bajo carga real (transferencias "
             "grandes) aparecen colisiones tardías y retransmisiones masivas, percibidas como "
             "'lentitud aleatoria'."
         ),
         relevancia_diagnostica=(
             "Lentitud que NO se detecta con ping ni con monitoreo básico de estado, pero sí "
             "con transferencias reales de archivos, es la firma clásica de duplex mismatch — "
             "revisar contadores de colisiones tardías (late collisions) en el puerto, no solo "
             "si está 'up/up'."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="LACP y agregación de enlaces",
         explicacion=(
             "802.3ad (LACP) permite combinar varios puertos físicos en un solo enlace lógico "
             "para redundancia y más ancho de banda agregado — pero el tráfico de UNA sola "
             "conversación (un solo flujo TCP) sigue viajando por UN solo puerto físico del "
             "grupo, según el algoritmo de balanceo (hash de MAC/IP/puerto). No reparte una "
             "sola transferencia entre varios cables."
         ),
         relevancia_diagnostica=(
             "Un LACP de 2x1Gbps no va a hacer que UNA transferencia grande vaya a 2Gbps — eso "
             "es un malentendido común. Sirve para más conexiones simultáneas totales y "
             "redundancia ante la caída de un cable, no para acelerar un solo flujo."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Storm control: protección contra tormentas de broadcast",
         explicacion=(
             "Storm control limita el porcentaje de ancho de banda de un puerto que puede "
             "consumir tráfico broadcast, multicast o unicast desconocido, cortando o "
             "limitando el puerto si se supera el umbral — previene que UN equipo defectuoso "
             "o un loop satsuren toda la red."
         ),
         relevancia_diagnostica=(
             "Si un puerto específico se apaga solo cuando se conecta cierto equipo, revisar "
             "si storm control lo está bloqueando por generar tráfico anómalo — es una señal "
             "de que ESE equipo tiene un problema (NIC defectuosa, loop), no el switch."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ ENRUTAMIENTO Y WAN ══════════════════════
    dict(dominio="wan", concepto="NAT/PAT: cómo cientos de dispositivos comparten una sola IP pública",
         explicacion=(
             "PAT (Port Address Translation, también llamado NAT overload) traduce cada "
             "conexión saliente a la IP pública única del router, usando un puerto distinto "
             "para cada una — la tabla de traducción tiene un límite de conexiones simultáneas "
             "que, si se satura, hace que nuevas conexiones fallen silenciosamente aunque "
             "internet 'funcione'."
         ),
         relevancia_diagnostica=(
             "Con muchos huéspedes conectados a la vez, aplicaciones que abren muchas "
             "conexiones (streaming, algunos juegos) pueden agotar la tabla NAT del router — "
             "el síntoma es 'internet lento para todos' sin que el ancho de banda esté "
             "realmente saturado."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="MTU y el problema silencioso de la fragmentación",
         explicacion=(
             "Ethernet estándar usa MTU de 1500 bytes. Una VPN o conexión PPPoE agrega "
             "encabezados extra, reduciendo el MTU efectivo (a menudo ~1492 o menos) — si un "
             "paquete más grande no se fragmenta correctamente y el firewall bloquea los "
             "mensajes ICMP necesarios para 'Path MTU Discovery', el resultado es un 'black "
             "hole': conexiones pequeñas (como cargar una página) funcionan, pero "
             "transferencias grandes o ciertas VPN se cuelgan sin error claro."
         ),
         relevancia_diagnostica=(
             "'La VPN se conecta pero no pasa datos grandes' o 'algunos sitios cargan y otros "
             "se quedan pegados' es la firma clásica de un problema de MTU/fragmentación, no "
             "de ancho de banda."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="QoS: marcado DSCP vs CoS, shaping vs policing",
         explicacion=(
             "DSCP (6 bits en la cabecera IP, capa 3) marca prioridad de extremo a extremo a "
             "través de routers; CoS (802.1p, capa 2) solo tiene alcance dentro de la red local "
             "etiquetada. 'Shaping' retiene el tráfico excedente en una cola para enviarlo "
             "después (suaviza picos); 'policing' simplemente descarta lo que excede el límite "
             "(más agresivo, usado en el borde del proveedor)."
         ),
         relevancia_diagnostica=(
             "Voz/video con cortes bajo carga, en una red donde 'hay suficiente ancho de "
             "banda total', casi siempre es falta de QoS priorizando ese tráfico sobre "
             "descargas masivas — el problema no es capacidad, es orden de salida."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="Registros DNS que casi siempre se pasan por alto",
         explicacion=(
             "MX define a qué servidor va el correo de un dominio. SPF (registro TXT) lista "
             "qué servidores tienen permiso de enviar correo en nombre del dominio — sin él, "
             "el correo propio puede caer en spam ajeno. DKIM firma criptográficamente el "
             "correo saliente. DMARC le dice a quien recibe qué hacer si SPF/DKIM fallan."
         ),
         relevancia_diagnostica=(
             "'El correo no llega' o 'llega a spam' casi nunca es un problema del servidor de "
             "correo en sí — primero se revisan SPF/DKIM/DMARC, son la causa más común y la "
             "más rápida de descartar."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),

    # ══════════════════════ WIFI / INGENIERÍA DE RF ══════════════════════
    dict(dominio="wifi", concepto="Canales no solapados y por qué solo hay 3 reales en 2.4GHz",
         explicacion=(
             "2.4GHz tiene canales del 1 al 11 (EE.UU.) separados apenas 5MHz, pero cada canal "
             "ocupa 20-22MHz de ancho — solo 1, 6 y 11 no se solapan entre sí. Usar canales "
             "intermedios (2,3,4,5,7,8,9,10) garantiza interferencia con los vecinos. 5GHz tiene "
             "muchísimos más canales no solapados disponibles, por eso soporta mucha más "
             "densidad de APs sin interferencia."
         ),
         relevancia_diagnostica=(
             "WiFi lento en 2.4GHz en un edificio con muchos APs (propios o de vecinos) casi "
             "siempre es interferencia co-canal por mala planificación de canales — antes de "
             "sospechar de hardware, revisar qué canales está usando cada AP."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="Interferencia co-canal vs adyacente",
         explicacion=(
             "Interferencia co-canal (mismo canal exacto) hace que los APs 'se turnen' el aire "
             "correctamente vía CSMA/CA — es ineficiente pero no genera errores, solo menos "
             "capacidad para cada uno. Interferencia de canal adyacente (canales que se "
             "solapan parcialmente) SÍ genera ruido/errores reales porque los dispositivos no "
             "se 'escuchan' entre sí para turnarse, transmiten a la vez y corrompen tramas."
         ),
         relevancia_diagnostica=(
             "Errores de trama y baja velocidad real (no solo 'muchos usuarios') apunta a "
             "canales adyacentes mal planificados — es peor que compartir el mismo canal "
             "exacto."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="Roaming asistido: 802.11k, 802.11v y 802.11r",
         explicacion=(
             "802.11k le da al cliente una lista de APs vecinos y su calidad, para que decida "
             "mejor a cuál moverse. 802.11v permite que la RED sugiera activamente a un cliente "
             "que se mueva a otro AP (BSS Transition Management). 802.11r acelera el proceso de "
             "autenticación al cambiar de AP (fast BSS transition), crítico para llamadas VoIP "
             "que no toleran cortes de más de ~150ms."
         ),
         relevancia_diagnostica=(
             "Un dispositivo que se queda 'pegado' a un AP lejano con señal débil en vez de "
             "saltar a uno cercano más fuerte (sticky client) es un problema de falta de "
             "roaming asistido, no de la potencia del AP nuevo — el cliente decide, la red solo "
             "puede sugerir."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="MIMO, MU-MIMO y OFDMA (WiFi 6)",
         explicacion=(
             "MIMO usa múltiples antenas para enviar varios flujos de datos al MISMO cliente "
             "en simultáneo, aumentando velocidad. MU-MIMO (WiFi5+) permite atender a VARIOS "
             "clientes distintos a la vez en el mismo instante de aire, no uno por uno. OFDMA "
             "(WiFi6) divide un canal en sub-canales más pequeños para servir a múltiples "
             "clientes con paquetes pequeños (IoT, sensores) sin desperdiciar el canal completo "
             "en cada uno."
         ),
         relevancia_diagnostica=(
             "En un salón de eventos con muchos dispositivos pequeños conectados (o control de "
             "acceso, cámaras IoT), un AP WiFi6 real rinde mucho mejor que uno WiFi5 aunque la "
             "velocidad 'pico' anunciada sea similar — la diferencia está en cuántos clientes "
             "atiende bien a la vez, no en la velocidad máxima teórica."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="DFS (Dynamic Frequency Selection) en 5GHz",
         explicacion=(
             "Varios canales de 5GHz están compartidos con radares (meteorológicos, "
             "aeronáuticos) y por regulación, el AP debe monitorear y ceder el canal si detecta "
             "un radar, cambiando automáticamente de canal sin aviso — esto puede causar una "
             "breve desconexión de todos los clientes en ese canal."
         ),
         relevancia_diagnostica=(
             "Desconexiones breves y sincronizadas de todos los clientes en 5GHz, sin patrón "
             "de carga ni hora fija, puede ser un evento DFS — revisar logs del AP por eventos "
             "de radar antes de sospechar de una falla de hardware."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ HARDWARE / SERVIDORES ══════════════════════
    dict(dominio="hardware", concepto="Niveles de RAID y qué protegen realmente",
         explicacion=(
             "RAID 0 (striping) reparte datos entre discos SIN redundancia — más velocidad, "
             "cero protección, si falla un disco se pierde todo. RAID 1 (mirroring) duplica "
             "los datos en dos discos. RAID 5 usa paridad distribuida y tolera la falla de UN "
             "disco, pero reconstruir tras un fallo estresa mucho los discos restantes (riesgo "
             "real de una segunda falla durante la reconstrucción). RAID 10 combina espejo y "
             "striping — mejor rendimiento y tolerancia que RAID 5, pero usa el doble de "
             "capacidad."
         ),
         relevancia_diagnostica=(
             "RAID 0 en un servidor de producción no es 'más rápido y ya' — es una decisión "
             "sin respaldo real ante falla de disco; si aparece en un sitio, es una bandera "
             "roja de diseño, no un simple dato técnico."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="hardware", concepto="SMART: qué atributos predicen falla real de disco",
         explicacion=(
             "De las docenas de atributos SMART, los que de verdad predicen falla inminente "
             "son: Reallocated Sectors Count (sectores dañados ya reubicados — si crece, el "
             "disco se está deteriorando activamente), Current Pending Sector (sectores "
             "sospechosos aún sin confirmar), y Reported Uncorrectable Errors. Temperatura alta "
             "sostenida acelera el deterioro de todos los demás."
         ),
         relevancia_diagnostica=(
             "Un disco con Reallocated Sectors subiendo, aunque el sistema operativo no "
             "reporte ningún error visible todavía, va a fallar — reemplazar preventivamente, "
             "no esperar el error real."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="hardware", concepto="Ciclo de vida real de una batería UPS",
         explicacion=(
             "Las baterías de plomo-ácido selladas (las más comunes en UPS) se degradan por "
             "edad Y por ciclos de descarga, típicamente 2-4 años de vida útil real "
             "independiente de si 'nunca se usaron' — el software del UPS puede reportar "
             "'batería OK' en una autoprueba corta sin detectar que ya no sostiene la carga "
             "real por el tiempo esperado bajo un corte largo."
         ),
         relevancia_diagnostica=(
             "Un UPS con más de 3 años sin cambio de batería, aunque el panel diga 'OK', debe "
             "tratarse como sospechoso hasta probar una descarga real — la autoprueba de "
             "software no es garantía suficiente para equipo crítico."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ IMPRESORAS Y POS ══════════════════════
    dict(dominio="impresoras", concepto="Impresión térmica directa: por qué se degrada con el tiempo",
         explicacion=(
             "La impresión térmica no usa tinta ni tóner — el cabezal calienta puntos "
             "específicos de un papel químicamente sensible al calor. El papel térmico se "
             "degrada con luz, calor ambiente y tiempo (por eso los recibos viejos se ponen "
             "amarillos y se borran solos), y el cabezal acumula residuos que causan líneas "
             "blancas verticales en la impresión."
         ),
         relevancia_diagnostica=(
             "Líneas blancas verticales consistentes en cada impresión = cabezal sucio o con "
             "elementos quemados, no un problema de la comanda ni del POS — limpieza o "
             "reemplazo de cabezal, no reinicio del sistema."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="impresoras", concepto="Puerto 9100 (raw/JetDirect) vs colas gestionadas",
         explicacion=(
             "Muchas impresoras de red aceptan impresión 'raw' directo al puerto TCP 9100 sin "
             "pasar por un driver complejo del lado del cliente — el software (POS, PMS) le "
             "manda los bytes de comando directo a ese puerto. Si el firewall interno bloquea "
             "el puerto 9100 entre el segmento del POS y el de impresoras, la impresora sigue "
             "'en línea' (responde ping, responde en el puerto de administración) pero nunca "
             "recibe trabajos de impresión."
         ),
         relevancia_diagnostica=(
             "Impresora que hace ping perfecto pero nunca imprime nada desde el software de "
             "negocio — verificar que el puerto 9100 específicamente esté abierto entre esos "
             "dos segmentos, no solo la conectividad general."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),

    # ══════════════════════ SEGURIDAD ══════════════════════
    dict(dominio="seguridad", concepto="ARP spoofing y por qué las redes planas son vulnerables",
         explicacion=(
             "ARP no tiene autenticación — cualquier dispositivo en la misma red local puede "
             "anunciar 'yo soy tal IP' y los demás equipos le van a creer, redirigiendo tráfico "
             "hacia el atacante (man-in-the-middle) sin que nada se vea 'caído'. Esto solo es "
             "posible dentro del mismo segmento de capa 2 — es una de las razones principales "
             "para segmentar con VLANs, no solo por organización sino por seguridad real."
         ),
         relevancia_diagnostica=(
             "Lentitud o comportamiento errático de red sin ninguna causa física identificable, "
             "en una red plana grande sin segmentar, puede ser ARP spoofing — revisar tablas "
             "ARP duplicadas para la misma IP con distinta MAC."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad", concepto="DHCP starvation y rogue DHCP",
         explicacion=(
             "Un atacante (o un router doméstico mal conectado por error) puede agotar el pool "
             "de direcciones DHCP legítimo, o peor, ofrecer SU PROPIO servidor DHCP compitiendo "
             "con el real — los dispositivos que reciban configuración del servidor falso "
             "quedan con gateway/DNS incorrectos, dirigiendo su tráfico a donde el atacante "
             "quiera."
         ),
         relevancia_diagnostica=(
             "Algunos equipos en la misma red obtienen IPs de un rango distinto al esperado, o "
             "no tienen internet mientras otros sí — sospechar de un segundo servidor DHCP no "
             "autorizado (a menudo un router doméstico conectado por error), no de fallas "
             "individuales de cada equipo."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad", concepto="Por qué PCI-DSS exige segmentación real, no solo contraseñas",
         explicacion=(
             "El estándar de seguridad de datos de tarjetas (PCI-DSS) parte de la premisa de "
             "que el 'Entorno de Datos del Titular' (CDE) debe estar aislado de red mediante "
             "firewalls/VLANs — no basta con que el datáfono tenga buena contraseña si comparte "
             "la misma red lógica que el WiFi de invitados; el objetivo es reducir el alcance "
             "(scope) de auditoría y el riesgo real de exposición."
         ),
         relevancia_diagnostica=(
             "Un datáfono/terminal de pago funcionando perfecto técnicamente pero en la misma "
             "VLAN que la red pública es un hallazgo de cumplimiento tan real como cualquier "
             "falla técnica — no esperar a que algo falle para corregirlo."
         ),
         fuente="Normas de seguridad de datos de pago (PCI-DSS), aplicable a cualquier negocio con datáfonos"),

    # ══════════════════════ WINDOWS / ACTIVE DIRECTORY ══════════════════════
    dict(dominio="windows_ad", concepto="Kerberos y por qué la hora del sistema es crítica",
         explicacion=(
             "Active Directory usa Kerberos para autenticación, que depende de tickets con "
             "marca de tiempo — si el reloj de un equipo se desincroniza más de 5 minutos "
             "(el valor por defecto de tolerancia) respecto al controlador de dominio, la "
             "autenticación falla por completo, con errores que parecen de red o de "
             "credenciales pero son, en realidad, de sincronización horaria."
         ),
         relevancia_diagnostica=(
             "Fallas de autenticación de dominio repentinas en un equipo, sin cambio de "
             "contraseña ni de red, revisar primero la hora del sistema — un CMOS con batería "
             "agotada es una causa común y fácil de pasar por alto."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="windows_ad", concepto="Roles FSMO y qué pasa cuando el que los tiene se cae",
         explicacion=(
             "En un dominio con varios controladores, 5 roles críticos (FSMO) los tiene un "
             "solo controlador a la vez (no se reparten automáticamente) — si ESE controlador "
             "específico cae, funciones puntuales fallan (crear usuarios nuevos, cambios de "
             "esquema) aunque los demás controladores sigan respondiendo autenticación normal."
         ),
         relevancia_diagnostica=(
             "'La autenticación funciona pero no puedo crear un usuario nuevo' con AD "
             "funcionando aparentemente bien, revisar cuál controlador tiene los roles FSMO — "
             "puede estar caído específicamente ese, no todo el dominio."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="windows_ad", concepto="Orden de aplicación de Políticas de Grupo (GPO): LSDOU",
         explicacion=(
             "Las políticas se aplican en orden Local → Sitio → Dominio → Unidad Organizativa, "
             "y la última en aplicarse (la más específica, la OU) gana en caso de conflicto — "
             "salvo que una política superior tenga 'forzar' (enforce) activado, en cuyo caso "
             "ignora este orden."
         ),
         relevancia_diagnostica=(
             "Un cambio de política que 'no se aplica' a un equipo específico casi siempre es "
             "una política más específica (de su propia OU) sobreescribiéndola — revisar en qué "
             "OU está el objeto antes de asumir que la política nueva está mal escrita."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),

    # ══════════════════════ INTEGRACIÓN DE SISTEMAS DE NEGOCIO ══════════════════════
    dict(dominio="pms_integracion", concepto="Por qué 'conectado' no significa que los datos fluyan",
         explicacion=(
             "La mayoría de integraciones PMS↔POS usan una API o un proceso de sincronización "
             "por lotes (batch) que reporta un estado de conexión (heartbeat) SEPARADO del "
             "flujo real de datos de negocio — el heartbeat puede estar perfecto mientras la "
             "sincronización de transacciones reales falla silenciosamente por un cambio de "
             "formato, un campo nuevo no mapeado, o un límite de tasa (rate limit) alcanzado."
         ),
         relevancia_diagnostica=(
             "La única forma confiable de confirmar que una integración funciona de verdad es "
             "probar el flujo de negocio real (una venta de prueba, un cargo a habitación de "
             "prueba) — el estado 'conectado' en pantalla es necesario pero no suficiente."
         ),
         fuente="Industria hotelera (Shiji Insights, BringIT Professional Services)"),
    dict(dominio="pms_integracion", concepto="Procesos batch nocturnos e idempotencia",
         explicacion=(
             "El cierre nocturno (night audit) de un PMS suele ser un proceso batch que corre "
             "sin supervisión humana — si no está diseñado para ser idempotente (poder "
             "reintentarse sin duplicar datos si se interrumpe a la mitad), un corte de energía "
             "o de red a mitad de proceso puede dejar datos duplicados o incompletos sin ningún "
             "error visible al día siguiente."
         ),
         relevancia_diagnostica=(
             "Discrepancias en reportes financieros del día que no tienen explicación operativa "
             "clara — revisar si el proceso de cierre nocturno se interrumpió esa noche (cortes "
             "de energía, reinicios programados) antes de asumir error humano."
         ),
         fuente="Industria hotelera -- patrón operativo documentado"),

    # ══════════════════════ METODOLOGÍA ══════════════════════
    dict(dominio="metodologia", concepto="El modelo OSI como marco de diagnóstico, no solo teoría",
         explicacion=(
             "Las 7 capas OSI (física, enlace, red, transporte, sesión, presentación, "
             "aplicación) dan un orden lógico de diagnóstico: enfoque 'bottom-up' (de la capa "
             "física hacia arriba) es más rápido para fallas totales — se descarta cable/puerto "
             "antes de sospechar de la aplicación. Enfoque 'top-down' (desde la aplicación "
             "hacia abajo) tiene más sentido cuando SOLO una aplicación falla y el resto de la "
             "red funciona bien — ahí ir a la capa física sería perder tiempo."
         ),
         relevancia_diagnostica=(
             "Elegir el sentido correcto (bottom-up vs top-down) según el síntoma ahorra tiempo "
             "real — un fallo total de conectividad se diagnostica de abajo hacia arriba, un "
             "fallo de una sola aplicación con red funcionando bien se diagnostica de arriba "
             "hacia abajo."
         ),
         fuente="CompTIA Network+ N10-009 / metodología de troubleshooting por capas"),
    # ══════════════════════ VIRTUALIZACIÓN Y NUBE ══════════════════════
    dict(dominio="virtualizacion", concepto="Hipervisores tipo 1 vs tipo 2",
         explicacion=(
             "Un hipervisor tipo 1 (bare metal — ej. servidores de producción) corre "
             "directamente sobre el hardware, sin sistema operativo anfitrión de por medio — "
             "mejor rendimiento y aislamiento. Un hipervisor tipo 2 corre COMO una aplicación "
             "dentro de un sistema operativo normal (uso típico: pruebas en una laptop) — el "
             "sistema anfitrión compite por los mismos recursos que las máquinas virtuales."
         ),
         relevancia_diagnostica=(
             "Una máquina virtual crítica de producción corriendo sobre un hipervisor tipo 2 "
             "(dentro de un Windows/Linux de escritorio normal) es una señal de arquitectura "
             "frágil — cualquier proceso del sistema anfitrión puede degradar el rendimiento "
             "de la VM sin ninguna alerta específica de virtualización."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="virtualizacion", concepto="Snapshots no son respaldos (backups) reales",
         explicacion=(
             "Un snapshot guarda solo los CAMBIOS desde un punto en el tiempo, dependiendo del "
             "disco original para reconstruirse — si el disco base se corrompe o se pierde, el "
             "snapshot por sí solo no sirve de nada. Un backup real es una copia completa e "
             "independiente, restaurable sin depender del origen."
         ),
         relevancia_diagnostica=(
             "'Tenemos snapshots diarios' no es lo mismo que 'tenemos respaldo' — si el "
             "servidor físico o el almacenamiento donde viven los snapshots falla, se pierden "
             "junto con los datos originales. Verificar que exista un respaldo real, aparte."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ DISPOSITIVOS MÓVILES ══════════════════════
    dict(dominio="dispositivos_moviles", concepto="Por qué un dispositivo móvil se desconecta al cambiar de banda",
         explicacion=(
             "Muchos dispositivos móviles (tablets de recepción, lectores de código de barras) "
             "tienen radios WiFi más simples que un laptop — pueden no soportar bien el roaming "
             "asistido (802.11k/v/r) ni cambiar de banda (2.4↔5GHz) sin una breve desconexión "
             "y reconexión completa, a diferencia de equipos más nuevos."
         ),
         relevancia_diagnostica=(
             "Un dispositivo móvil específico que se desconecta al moverse por el edificio, "
             "mientras laptops no tienen el problema, puede ser una limitación real del "
             "hardware del dispositivo — no siempre es un problema de la red WiFi."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="dispositivos_moviles", concepto="Gestión de dispositivos móviles (MDM) y perfiles",
         explicacion=(
             "Un MDM permite configurar remotamente WiFi, restricciones y aplicaciones en "
             "dispositivos de la empresa (tablets, móviles) sin tocarlos físicamente uno por "
             "uno — sin MDM, cada cambio de configuración (ej. cambiar la contraseña WiFi) "
             "requiere tocar cada dispositivo a mano."
         ),
         relevancia_diagnostica=(
             "Si hay 10+ tablets operativas sin MDM, cualquier cambio de red (contraseña WiFi, "
             "certificado) se vuelve una tarea manual larga y propensa a error — vale la pena "
             "señalarlo como riesgo operativo, no solo técnico."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ SISTEMAS OPERATIVOS Y SOFTWARE ══════════════════════
    dict(dominio="sistemas_operativos", concepto="Servicios de Windows: por qué 'el programa está abierto' no basta",
         explicacion=(
             "Muchas aplicaciones de negocio (PMS, POS) corren su lógica principal como un "
             "SERVICIO de Windows en segundo plano, independiente de si hay una ventana "
             "visible abierta — el servicio puede estar detenido o colgado mientras la "
             "interfaz gráfica sigue respondiendo (o viceversa: el servicio vivo, la ventana "
             "congelada)."
         ),
         relevancia_diagnostica=(
             "Antes de reiniciar todo un equipo, verificar el estado específico del servicio "
             "de la aplicación (en el administrador de servicios de Windows) — muchas veces "
             "reiniciar solo el servicio resuelve sin necesidad de reiniciar el equipo "
             "completo."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="sistemas_operativos", concepto="Perfiles de usuario corruptos en Windows",
         explicacion=(
             "Cada usuario de Windows tiene un perfil (configuración, escritorio, datos de "
             "aplicaciones) que puede corromperse por un apagado incorrecto o un disco lleno — "
             "el síntoma típico es un login que tarda mucho, o que carga un 'perfil temporal' "
             "genérico sin ninguna de las configuraciones esperadas."
         ),
         relevancia_diagnostica=(
             "'Le funciona a todos menos a este usuario, en la misma máquina' apunta casi "
             "siempre a un perfil de usuario dañado — la solución suele ser recrear el perfil, "
             "no reinstalar el sistema completo."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="sistemas_operativos", concepto="Actualizaciones de Windows y ventanas de mantenimiento",
         explicacion=(
             "Las actualizaciones automáticas de Windows pueden reiniciar un equipo sin aviso "
             "fuera de una ventana de mantenimiento configurada, interrumpiendo un turno activo "
             "en recepción o POS — y algunas actualizaciones cambian comportamiento de "
             "controladores (drivers) de red o impresión sin que nadie lo note hasta que algo "
             "deja de funcionar días después."
         ),
         relevancia_diagnostica=(
             "Una falla nueva que aparece sin ningún cambio local aparente — revisar si hubo "
             "una actualización de Windows reciente antes de descartarla como causa."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="sistemas_operativos", concepto="Malware vs. comportamiento anómalo legítimo",
         explicacion=(
             "Uso alto de CPU/red sostenido no siempre es malware — puede ser un proceso de "
             "respaldo, un antivirus escaneando, o una actualización descargándose. La forma "
             "de distinguir es identificar el PROCESO específico responsable antes de asumir "
             "infección; un malware real casi siempre também genera conexiones de red salientes "
             "a destinos desconocidos, no solo uso alto de CPU."
         ),
         relevancia_diagnostica=(
             "Antes de reinstalar un equipo por sospecha de virus, identificar el proceso "
             "exacto responsable del consumo — muchas veces es una tarea legítima mal "
             "programada (ej. un respaldo corriendo en horario pico), no una infección real."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),

    dict(dominio="metodologia", concepto="Aislar variables: cambiar una cosa a la vez",
         explicacion=(
             "Cambiar múltiples cosas a la vez (cable, configuración y equipo en el mismo "
             "intento) puede 'resolver' el síntoma sin que se sepa cuál cambio fue el real — "
             "la próxima vez que pase algo similar, no hay aprendizaje aprovechable porque no "
             "se sabe qué funcionó de verdad."
         ),
         relevancia_diagnostica=(
             "Este principio es la razón de fondo por la que un sistema de aprendizaje (como "
             "agente_skills) solo es confiable si cada acción se prueba y registra por "
             "separado — mezclar varias soluciones a la vez contamina el aprendizaje futuro."
         ),
         fuente="Metodología CompTIA de 7 pasos"),

    # ══════════════════════ CABLEADO — AMPLIACIÓN ══════════════════════
    dict(dominio="cableado", concepto="T568A vs T568B y por qué casi nunca importa hoy",
         explicacion=(
             "Son dos esquemas de asignación de colores de pares al conector RJ45 — "
             "eléctricamente equivalentes, solo cambia el orden de 2 pares. Lo único que "
             "importa es usar el MISMO esquema en ambos extremos de un cable derecho "
             "(straight-through). Los cables cruzados (crossover) ya casi no se necesitan "
             "porque Auto-MDIX detecta y corrige automáticamente en casi todo equipo moderno."
         ),
         relevancia_diagnostica=(
             "Un enlace que no sube nunca por 'cable cruzado vs derecho' en equipo moderno es "
             "poco probable — casi siempre el problema real es otro (categoría, terminación, "
             "daño físico), no el esquema de colores."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Modos PoE A y B (spare pairs vs data pairs)",
         explicacion=(
             "El PoE puede viajar sobre los mismos pares que llevan datos (modo B, común en "
             "Gigabit donde los 4 pares llevan datos) o sobre los pares 'libres' en cableado "
             "10/100 (modo A). Si un inyector PoE y un switch/AP usan modos distintos de forma "
             "incompatible, el equipo simplemente no recibe energía aunque el cable esté "
             "perfecto."
         ),
         relevancia_diagnostica=(
             "Mezclar un inyector PoE de una marca con un AP de otra marca a veces no entrega "
             "energía por incompatibilidad de modo — antes de sospechar del cable, confirmar "
             "que ambos extremos usan el mismo estándar/modo PoE."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Certificación vs verificación de cable",
         explicacion=(
             "'Verificar' un cable (con un tester barato) solo confirma continuidad — que cada "
             "pin llega al otro extremo. 'Certificar' (con equipo especializado tipo Fluke) "
             "mide parámetros reales de transmisión: atenuación, NEXT, return loss, retardo de "
             "propagación — y compara contra el estándar de la categoría declarada."
         ),
         relevancia_diagnostica=(
             "Un cable que 'pasa' con un tester barato puede seguir teniendo errores bajo carga "
             "real — un tester de continuidad NO prueba si el cable de verdad cumple su "
             "categoría, solo si los 8 pines conducen electricidad."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", concepto="Puesta a tierra en equipos exteriores",
         explicacion=(
             "APs, cámaras y switches en exteriores (o cableado que corre por techo/exterior de "
             "un edificio) son vulnerables a inducción de descargas eléctricas cercanas, incluso "
             "sin impacto directo — un protector de sobretensión (surge protector) puesto a "
             "tierra correctamente en la línea de datos/PoE reduce ese riesgo real."
         ),
         relevancia_diagnostica=(
             "Equipos exteriores que fallan repetidamente después de tormentas eléctricas, sin "
             "otra explicación, señalan falta de protección contra sobretensión — no es una "
             "casualidad ni una falla de fábrica repetida."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ SWITCHING — AMPLIACIÓN ══════════════════════
    dict(dominio="switching", concepto="EtherChannel/LACP: modo activo vs pasivo",
         explicacion=(
             "En modo activo, el puerto envía paquetes LACP para negociar la agregación "
             "proactivamente. En modo pasivo, espera a que el otro extremo inicie la "
             "negociación. Si AMBOS extremos quedan en pasivo, nunca se negocia nada y el "
             "enlace agregado simplemente no se forma, aunque los cables y puertos individuales "
             "estén perfectamente arriba."
         ),
         relevancia_diagnostica=(
             "Un EtherChannel/LACP que 'no sube' con todos los cables físicamente bien "
             "conectados — revisar que al menos un extremo esté en modo activo."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Tablas MAC y su límite (CAM table overflow)",
         explicacion=(
             "Un switch aprende qué MAC está en qué puerto y guarda esa tabla en memoria "
             "limitada (CAM table). Si se satura (por un ataque, o por miles de dispositivos "
             "virtuales/contenedores mal configurados generando MACs), el switch puede empezar "
             "a comportarse como un hub, inundando tráfico por todos los puertos en vez de "
             "dirigirlo — un problema de seguridad y de rendimiento a la vez."
         ),
         relevancia_diagnostica=(
             "Tráfico visible en puertos donde no debería estar, junto con lentitud general, "
             "puede ser saturación de la tabla MAC — no asumir automáticamente que es un "
             "problema de cableado o de VLAN."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Jumbo frames y cuándo tienen sentido",
         explicacion=(
             "Ethernet estándar usa tramas de hasta 1500 bytes; 'jumbo frames' permiten hasta "
             "9000 bytes, reduciendo la sobrecarga de procesamiento por byte transmitido — útil "
             "en tráfico de almacenamiento (iSCSI, backups) de alto volumen, pero TODO el "
             "camino (switches, NICs) debe soportarlo consistentemente o aparecen "
             "fragmentaciones y caídas de rendimiento peores que sin jumbo frames."
         ),
         relevancia_diagnostica=(
             "Activar jumbo frames en un solo tramo de la red, sin verificar que todo el "
             "camino lo soporte, puede EMPEORAR el rendimiento en vez de mejorarlo — es una "
             "optimización que requiere consistencia total, no parcial."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Puertos err-disabled y sus causas típicas",
         explicacion=(
             "Un puerto puede auto-apagarse (err-disabled) por varias razones distintas: BPDU "
             "guard (spanning tree), port security (MAC no autorizada), storm control "
             "(tráfico anómalo), o un error físico repetido — cada causa requiere una solución "
             "distinta y el log del switch dice exactamente cuál fue, no hay que adivinar."
         ),
         relevancia_diagnostica=(
             "Antes de simplemente 'reactivar' un puerto err-disabled, revisar el log del "
             "switch para saber POR QUÉ se apagó — reactivarlo sin resolver la causa real hace "
             "que se vuelva a apagar."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", concepto="Private VLANs para aislar equipos en la misma subred",
         explicacion=(
             "Una VLAN privada permite que varios equipos compartan la misma subred IP pero NO "
             "puedan verse entre sí directamente en capa 2 (solo hablan con un puerto "
             "'promiscuo', típicamente el gateway) — útil para redes de huéspedes donde cada "
             "habitación no debería ver el tráfico de la habitación vecina aunque compartan "
             "rango de IP."
         ),
         relevancia_diagnostica=(
             "Si dispositivos de huéspedes distintos NO deberían verse entre sí mismos por "
             "seguridad, una VLAN normal no lo garantiza — hace falta private VLAN o "
             "aislamiento de cliente (client isolation) específico en el AP/switch."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ WAN — AMPLIACIÓN ══════════════════════
    dict(dominio="wan", concepto="BGP y por qué casi ningún sitio pequeño lo necesita",
         explicacion=(
             "BGP es el protocolo que decide rutas ENTRE proveedores de internet distintos a "
             "escala global — solo tiene sentido si una organización tiene su propio bloque de "
             "IPs públicas y múltiples conexiones a distintos ISPs anunciando esas rutas ella "
             "misma. Un sitio con 1-2 conexiones a internet normales usa simplemente rutas "
             "estáticas o failover simple, BGP sería sobre-ingeniería."
         ),
         relevancia_diagnostica=(
             "Si alguien propone BGP para un sitio con un router doméstico/empresarial normal "
             "y 1-2 ISPs, es una solución desproporcionada al problema real — el failover "
             "simple por rutas estáticas con detección de caída (BFD o similar) resuelve lo "
             "mismo con mucha menos complejidad."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="BFD: detección rápida de caída de enlace",
         explicacion=(
             "Sin BFD, un router puede tardar decenas de segundos en darse cuenta de que un "
             "enlace cayó (esperando varios 'hellos' perdidos del protocolo de enrutamiento). "
             "BFD envía verificaciones mucho más frecuentes (cada pocos milisegundos) "
             "dedicadas solo a detectar caídas, permitiendo failover en menos de un segundo."
         ),
         relevancia_diagnostica=(
             "Un failover WAN que tarda 20-30 segundos en activarse, con cortes de servicio "
             "notorios cada vez, es candidato a mejorar con BFD si el hardware lo soporta — no "
             "es 'así de lento por diseño', se puede acelerar mucho."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="CGNAT y por qué algunos servicios no funcionan bien detrás de él",
         explicacion=(
             "Muchos proveedores de internet, ante la escasez de IPv4, ponen a sus clientes "
             "detrás de Carrier-Grade NAT — varios clientes finales comparten una sola IP "
             "pública del proveedor. Esto rompe el 'port forwarding' tradicional (no hay una "
             "IP pública propia que exponer) y puede causar problemas con VPNs entrantes, "
             "cámaras accedidas remotamente, o servidores que necesitan ser alcanzables desde "
             "afuera."
         ),
         relevancia_diagnostica=(
             "'No puedo abrir un puerto en mi router para acceder remotamente' cuando la "
             "configuración parece correcta — verificar primero si el ISP está entregando una "
             "IP pública real o una IP privada de CGNAT (rango 100.64.0.0/10 es la señal "
             "clásica)."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", concepto="Latencia vs jitter vs pérdida de paquetes: tres problemas distintos",
         explicacion=(
             "Latencia es el tiempo que tarda un paquete en llegar (afecta la sensación de "
             "'lag'). Jitter es la VARIACIÓN de esa latencia entre paquetes (el enemigo real de "
             "voz/video, que necesita ritmo constante, no solo velocidad). Pérdida de paquetes "
             "es cuando simplemente no llegan. Un enlace puede tener latencia baja pero jitter "
             "alto y sonar entrecortado en llamadas, sin que 'la velocidad' explique el "
             "problema."
         ),
         relevancia_diagnostica=(
             "Llamadas de voz que suenan entrecortadas en un enlace con buena velocidad "
             "medida — medir jitter específicamente, no solo velocidad de descarga/subida, "
             "que no lo captura."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ DNS / DHCP EN PROFUNDIDAD ══════════════════════
    dict(dominio="dns_dhcp", concepto="Cómo funciona una resolución DNS completa",
         explicacion=(
             "Un cliente pregunta primero a su caché local, luego al DNS configurado "
             "(recursivo) — ese servidor recursivo, si no tiene la respuesta cacheada, pregunta "
             "a los servidores raíz, luego a los del dominio (TLD), y finalmente al servidor "
             "autoritativo del dominio específico. Cada salto puede fallar o estar cacheado con "
             "datos viejos (TTL) de forma independiente."
         ),
         relevancia_diagnostica=(
             "'El sitio cambió de servidor pero algunos usuarios siguen viendo el viejo' es "
             "casi siempre caché DNS en algún punto de esa cadena con TTL alto que aún no "
             "expiró — no es un problema del servidor nuevo, es tiempo de propagación."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="dns_dhcp", concepto="DHCP: el proceso DORA y por qué importa el orden",
         explicacion=(
             "Discover (el cliente pregunta si hay servidor DHCP) → Offer (el servidor ofrece "
             "una IP) → Request (el cliente la pide formalmente, incluso a veces confirmando "
             "con broadcast para que otros servidores DHCP compitiendo sepan que perdieron) → "
             "Acknowledge (confirmación final). Si hay DOS servidores DHCP respondiendo "
             "Discover, el cliente toma la PRIMERA oferta que le llegue, no necesariamente la "
             "del servidor 'correcto'."
         ),
         relevancia_diagnostica=(
             "En una red con un DHCP no autorizado (rogue), no es que 'a veces' un dispositivo "
             "se conecte al malo — es prácticamente aleatorio cuál oferta gana, por eso el "
             "síntoma es inconsistente entre dispositivos, lo que confunde el diagnóstico."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="dns_dhcp", concepto="Reservas DHCP vs IP estática configurada en el equipo",
         explicacion=(
             "Una reserva DHCP asigna siempre la misma IP a una MAC específica pero SIGUE "
             "dependiendo de que el servidor DHCP esté vivo. Una IP estática configurada "
             "directamente en el equipo no depende de nada externo, pero es fácil de duplicar "
             "por error humano (dos equipos con la misma IP estática) generando conflictos "
             "intermitentes y confusos."
         ),
         relevancia_diagnostica=(
             "Un equipo que 'a veces' pierde conectividad de forma extraña, sin patrón, en una "
             "red con IPs estáticas mezcladas con DHCP, revisar conflicto de IP duplicada — es "
             "más común de lo que parece cuando hay configuración manual dispersa."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ WIFI — AMPLIACIÓN ══════════════════════
    dict(dominio="wifi", concepto="EIRP, potencia de transmisión y ganancia de antena",
         explicacion=(
             "La potencia efectiva radiada (EIRP) combina la potencia de salida del "
             "transmisor MÁS la ganancia de la antena — subir la potencia de transmisión no "
             "sirve de nada si la antena tiene poca ganancia, y hay límites regulatorios "
             "máximos de EIRP que no se pueden exceder legalmente, distintos por banda y país."
         ),
         relevancia_diagnostica=(
             "'Subir la potencia' del AP al máximo no siempre mejora la cobertura real — puede "
             "generar más interferencia hacia zonas vecinas sin mejorar la señal donde se "
             "necesita, especialmente si el problema real es obstáculos físicos, no potencia."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="Zona de Fresnel en enlaces punto a punto exteriores",
         explicacion=(
             "Un enlace inalámbrico direccional entre dos puntos (ej. dos edificios) no solo "
             "necesita línea de vista directa — necesita una zona elíptica libre de obstáculos "
             "alrededor de esa línea (zona de Fresnel). Un obstáculo que no bloquea la vista "
             "directa pero invade esa zona (un árbol creciendo, una construcción nueva) puede "
             "degradar el enlace gradualmente."
         ),
         relevancia_diagnostica=(
             "Un enlace punto a punto que se degrada progresivamente durante meses sin ningún "
             "cambio de configuración — sospechar de crecimiento vegetal o construcción nueva "
             "invadiendo la zona de Fresnel, no de una falla de hardware."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="WPA2 vs WPA3: qué cambia realmente",
         explicacion=(
             "WPA2 usa un apretón de manos (4-way handshake) vulnerable a ataques de "
             "diccionario offline si se captura ese handshake. WPA3 usa SAE (Simultaneous "
             "Authentication of Equals), que resiste ataques de diccionario offline incluso "
             "con contraseñas débiles, y ofrece cifrado individualizado por sesión incluso en "
             "redes abiertas (Enhanced Open)."
         ),
         relevancia_diagnostica=(
             "Dispositivos viejos que no logran conectarse a una red configurada solo en "
             "WPA3 — es un problema real de compatibilidad, no una falla; el modo mixto "
             "WPA2/WPA3 existe justamente para esa transición."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="Portal cautivo: cómo funciona y por qué a veces no aparece",
         explicacion=(
             "Un portal cautivo intercepta las primeras peticiones HTTP del dispositivo y lo "
             "redirige a una página de login/aceptación — depende de que el sistema operativo "
             "del cliente dispare su propia detección de 'red con portal' (CNA — Captive "
             "Network Assistant) haciendo una petición de prueba a una URL conocida. Si esa "
             "detección falla o el dispositivo usa DNS-over-HTTPS que evita la intercepción, el "
             "portal simplemente no aparece."
         ),
         relevancia_diagnostica=(
             "'El portal de WiFi no me aparece' en un dispositivo específico, mientras a otros "
             "sí, casi siempre es una particularidad de detección de ESE sistema operativo o "
             "una configuración de DNS-over-HTTPS que evade el mecanismo — no un fallo general "
             "del portal."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", concepto="Antenas omnidireccionales vs direccionales/sectoriales",
         explicacion=(
             "Una antena omnidireccional distribuye la señal por igual en 360° pero con menos "
             "alcance por dirección — ideal para cobertura general en una habitación/pasillo. "
             "Una antena direccional o sectorial concentra la energía en un ángulo específico, "
             "logrando mucho más alcance en esa dirección — ideal para cubrir un salón alargado "
             "o un patio específico desde un punto fijo."
         ),
         relevancia_diagnostica=(
             "Cobertura pobre en un espacio alargado (pasillo largo, salón rectangular) con un "
             "AP omnidireccional en el centro puede resolverse mejor con antenas sectoriales "
             "orientadas, no necesariamente con más APs omnidireccionales."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ ALMACENAMIENTO Y BACKUP ══════════════════════
    dict(dominio="backup", concepto="Backup completo, incremental y diferencial",
         explicacion=(
             "Completo copia TODO cada vez (lento, mucho espacio, restauración simple — un solo "
             "archivo). Incremental copia solo lo que cambió desde el ÚLTIMO backup (rápido, "
             "poco espacio, pero restaurar requiere el completo MÁS todos los incrementales en "
             "orden). Diferencial copia lo que cambió desde el ÚLTIMO COMPLETO (tamaño "
             "intermedio, restaurar requiere solo el completo más el último diferencial)."
         ),
         relevancia_diagnostica=(
             "Una cadena de backups incrementales larga sin un completo reciente es frágil — "
             "si UN incremental de la cadena se corrompe, todos los posteriores a él quedan "
             "inutilizables para restaurar. Revisar la frecuencia de backups completos, no "
             "solo si 'los backups corren'."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="backup", concepto="La regla 3-2-1 de respaldo",
         explicacion=(
             "3 copias de los datos, en 2 tipos de medio distintos, con 1 copia fuera del "
             "sitio físico (offsite) — el objetivo es que ningún evento único (robo, incendio, "
             "falla de un solo disco) pueda destruir todas las copias a la vez."
         ),
         relevancia_diagnostica=(
             "Backups que solo existen en el mismo servidor o el mismo rack que los datos "
             "originales no cumplen ninguna función real ante un incendio, robo o falla mayor "
             "del sitio — 'tener backup' no es suficiente si está en el mismo lugar físico."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="backup", concepto="Probar la restauración, no solo confirmar que el backup corrió",
         explicacion=(
             "Un backup que 'terminó sin error' no garantiza que sea restaurable — puede haber "
             "corrupción silenciosa, archivos bloqueados que se saltaron sin marcar error "
             "claro, o un formato incompatible con la versión de recuperación disponible. La "
             "única prueba real es restaurar de verdad, al menos periódicamente."
         ),
         relevancia_diagnostica=(
             "Confiar en 'el backup dice que corrió bien' sin nunca haber restaurado un archivo "
             "de prueba es un riesgo invisible hasta el día que se necesita de verdad — "
             "recomendar pruebas de restauración periódicas, no solo monitoreo de ejecución."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ VOZ IP Y TELEFONÍA (relevante en hoteles) ══════════════════════
    dict(dominio="voz_ip", concepto="SIP: cómo se establece una llamada VoIP",
         explicacion=(
             "SIP (Session Initiation Protocol) negocia el INICIO de la llamada (quién llama, "
             "a quién, qué códec usar) pero el audio en sí generalmente viaja por RTP, un "
             "protocolo separado — esto significa que la señalización puede funcionar "
             "perfecto (el teléfono 'timbra') mientras el audio falla por completo si RTP está "
             "bloqueado en el firewall, dando la falsa impresión de que 'la llamada conecta "
             "pero no se escucha nada'."
         ),
         relevancia_diagnostica=(
             "'La llamada timbra y conecta pero no hay audio en ningún sentido' es la firma "
             "clásica de RTP bloqueado (firewall, NAT mal configurado) mientras SIP sí pasa — "
             "dos protocolos distintos, dos posibles puntos de falla independientes."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="voz_ip", concepto="Códecs de voz y su impacto en ancho de banda vs calidad",
         explicacion=(
             "G.711 no comprime (mejor calidad, ~64-87kbps por llamada) — ideal con ancho de "
             "banda de sobra. G.729 comprime mucho más (~8kbps) a costa de algo de calidad y "
             "más uso de CPU para codificar/decodificar — preferible en enlaces WAN limitados. "
             "Elegir el códec incorrecto para el enlace disponible es una causa común de mala "
             "calidad de llamada que no tiene que ver con 'la red estar mal'."
         ),
         relevancia_diagnostica=(
             "Llamadas de mala calidad en un enlace WAN limitado usando G.711 (sin comprimir) "
             "para muchas llamadas simultáneas — el enlace se satura antes de lo esperado; "
             "cambiar de códec puede resolver sin necesitar más ancho de banda contratado."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ CÁMARAS IP / CCTV ══════════════════════
    dict(dominio="camaras_cctv", concepto="Ancho de banda real de un sistema de cámaras IP",
         explicacion=(
             "El consumo de ancho de banda de una cámara IP depende de resolución, tasa de "
             "cuadros, codec (H.264 vs H.265 — este último reduce el tamaño a la mitad "
             "aproximadamente para la misma calidad) y si usa tasa de bits constante (CBR, "
             "predecible) o variable (VBR, más eficiente pero con picos). Un sistema con "
             "muchas cámaras 4K en CBR puede saturar un enlace sin que ningún equipo esté "
             "'fallando'."
         ),
         relevancia_diagnostica=(
             "Grabación con cuadros perdidos o video entrecortado en el NVR, con las cámaras "
             "individualmente respondiendo bien, sugiere saturación de ancho de banda agregado "
             "hacia el NVR — revisar el consumo total, no cámara por cámara."
         ),
         fuente="Conocimiento técnico de sistemas CCTV/vigilancia IP"),
    dict(dominio="camaras_cctv", concepto="ONVIF: el estándar que permite mezclar marcas de cámaras",
         explicacion=(
             "ONVIF es un estándar abierto que define cómo un NVR/VMS descubre y controla "
             "cámaras de marcas distintas — pero el cumplimiento del estándar varía entre "
             "fabricantes ('perfiles' ONVIF distintos: S para video básico, T para funciones "
             "avanzadas), por lo que dos equipos 'compatibles con ONVIF' no siempre funcionan "
             "igual de bien juntos."
         ),
         relevancia_diagnostica=(
             "Una cámara nueva de otra marca que se conecta al NVR pero le faltan funciones "
             "(zoom, PTZ, analíticas) que sí tenían las cámaras originales — revisar qué "
             "perfil ONVIF soporta cada una, no asumir compatibilidad total solo por decir "
             "'ONVIF' en la caja."
         ),
         fuente="Conocimiento técnico de sistemas CCTV/vigilancia IP"),

    # ══════════════════════ CONTROL DE ACCESO / BIOMÉTRICOS ══════════════════════
    dict(dominio="control_acceso", concepto="Modo standalone vs conectado a servidor central",
         explicacion=(
             "Un control de acceso biométrico/de tarjetas puede operar en modo 'standalone' "
             "(decide localmente si abrir, con su propia lista de usuarios) o conectado "
             "permanentemente a un servidor central que autoriza cada evento — el modo "
             "standalone sigue funcionando aunque la red caiga, pero los cambios de permisos "
             "(dar de baja a un empleado) no se reflejan hasta que sincroniza de nuevo."
         ),
         relevancia_diagnostica=(
             "Un usuario dado de baja en el sistema central que TODAVÍA puede entrar por un "
             "lector específico — revisar si ese lector está en modo standalone sin haber "
             "sincronizado el cambio, es un riesgo de seguridad real, no solo un capricho del "
             "sistema."
         ),
         fuente="Conocimiento técnico de sistemas de control de acceso"),
    dict(dominio="control_acceso", concepto="Falsos rechazos (FRR) vs falsos aceptos (FAR) en biometría",
         explicacion=(
             "Todo sistema biométrico (huella, facial) tiene un balance configurable entre "
             "tasa de falso rechazo (rechazar a alguien autorizado — molesto pero seguro) y "
             "tasa de falso acepto (aceptar a alguien no autorizado — inseguro). Ajustar la "
             "sensibilidad para reducir rechazos molestos aumenta, inevitablemente, el riesgo "
             "de aceptar a quien no debería."
         ),
         relevancia_diagnostica=(
             "'El biométrico rechaza mucho a la gente autorizada' — bajar la sensibilidad "
             "resuelve la molestia pero es una decisión de seguridad, no solo un ajuste técnico "
             "neutro; debe comunicarse como tal, no aplicarse en silencio."
         ),
         fuente="Conocimiento técnico de sistemas de control de acceso"),

    # ══════════════════════ BASES DE DATOS (soporte a cualquier PMS/POS/ERP) ══════════════════════
    dict(dominio="bases_datos", concepto="Bloqueos (locks) y por qué 'todo se pone lento a la vez'",
         explicacion=(
             "Cuando muchas estaciones escriben a la misma tabla de una base de datos al mismo "
             "tiempo (ej. check-ins simultáneos en recepción), el motor de base de datos puede "
             "bloquear filas o tablas completas para mantener consistencia — si un bloqueo se "
             "mantiene más de lo esperado (una transacción lenta o mal cerrada), TODAS las "
             "demás estaciones que necesitan esa misma fila/tabla se congelan esperando, "
             "aunque la red y los servidores individuales estén perfectamente sanos."
         ),
         relevancia_diagnostica=(
             "Varias estaciones de trabajo distintas congeladas al mismo tiempo, todas usando "
             "la misma aplicación de base de datos, con la red funcionando bien — sospechar de "
             "un bloqueo de base de datos antes que de un problema de red o de cada estación "
             "individual."
         ),
         fuente="Buenas prácticas de administración de bases de datos, genérico"),
    dict(dominio="bases_datos", concepto="Índices y por qué una base de datos se pone lenta con el tiempo",
         explicacion=(
             "A medida que una tabla crece (años de transacciones de huéspedes, por ejemplo), "
             "consultas que antes eran instantáneas se vuelven lentas si no hay índices "
             "adecuados en las columnas que se consultan frecuentemente — el motor tiene que "
             "revisar cada vez más filas una por una en vez de saltar directo a la que "
             "necesita."
         ),
         relevancia_diagnostica=(
             "Un sistema que 'antes era rápido y con el tiempo se puso lento', sin ningún "
             "cambio de hardware ni de red, es un patrón clásico de crecimiento de datos sin "
             "mantenimiento de índices — no siempre requiere hardware nuevo, a veces requiere "
             "mantenimiento de la base de datos."
         ),
         fuente="Buenas prácticas de administración de bases de datos, genérico"),

    # ══════════════════════ LINUX (muchos servidores/appliances corren sobre esto) ══════════════════════
    dict(dominio="linux", concepto="systemd: por qué un servicio 'no arranca solo' tras reiniciar",
         explicacion=(
             "En sistemas Linux modernos, systemd gestiona qué servicios arrancan "
             "automáticamente al iniciar el sistema — un servicio puede estar instalado y "
             "funcionando perfecto, pero si nunca se hizo 'enable' (solo se inició "
             "manualmente una vez), sobrevive hasta el próximo reinicio y luego simplemente no "
             "vuelve a arrancar solo, sin ningún mensaje de error visible."
         ),
         relevancia_diagnostica=(
             "Un servicio que funcionaba bien y 'desapareció' después de un reinicio o corte "
             "de energía (no de una falla activa) — verificar si el servicio está habilitado "
             "para arranque automático, no solo si el ejecutable/configuración está bien."
         ),
         fuente="CompTIA A+ Core 2 220-1202 / administración de sistemas Linux"),
    dict(dominio="linux", concepto="Permisos y por qué 'funciona con sudo pero no sin él'",
         explicacion=(
             "Un proceso que corre como un usuario específico (no root) solo puede acceder a "
             "archivos/recursos que ese usuario tiene permitido — un servicio que se probó "
             "manualmente con privilegios elevados (sudo/root) puede parecer que funciona, pero "
             "fallar silenciosamente cuando corre automáticamente con permisos normales, por no "
             "tener acceso a un archivo o puerto específico."
         ),
         relevancia_diagnostica=(
             "'Funciona cuando yo lo prueba a mano pero falla en automático' es casi siempre "
             "una diferencia de permisos/usuario entre la prueba manual y la ejecución "
             "automática real — no un problema del código o la configuración en sí."
         ),
         fuente="CompTIA A+ Core 2 220-1202 / administración de sistemas Linux"),

    # ══════════════════════ NUBE / CLOUD EN PROFUNDIDAD ══════════════════════
    dict(dominio="cloud", concepto="SaaS vs IaaS vs PaaS: quién es responsable de qué",
         explicacion=(
             "En SaaS (ej. correo en la nube) el proveedor gestiona todo, el cliente solo usa "
             "la aplicación. En IaaS (servidores virtuales en la nube) el proveedor da la "
             "infraestructura, el cliente administra sistema operativo y aplicaciones. En PaaS "
             "el proveedor da una plataforma de ejecución, el cliente solo pone su aplicación. "
             "Cada modelo cambia radicalmente QUIÉN debe resolver un problema dado."
         ),
         relevancia_diagnostica=(
             "Antes de intentar 'arreglar' algo en un servicio en la nube, identificar el "
             "modelo (SaaS/IaaS/PaaS) — muchos problemas simplemente no son resolubles del "
             "lado del cliente y requieren abrir un ticket con el proveedor en vez de seguir "
             "invirtiendo tiempo local."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="cloud", concepto="Latencia hacia servicios en la nube y su impacto real",
         explicacion=(
             "Un servicio en la nube alojado lejos geográficamente introduce latencia base "
             "que ninguna optimización local puede eliminar — aplicaciones diseñadas asumiendo "
             "baja latencia (algunas integraciones síncronas) pueden sentirse 'lentas' aunque "
             "el ancho de banda disponible sea de sobra, porque el problema es el tiempo de "
             "viaje, no la capacidad."
         ),
         relevancia_diagnostica=(
             "Una aplicación en la nube que se siente lenta pese a tener buen ancho de banda "
             "medido — medir latencia (RTT) hacia el servicio específico, no solo velocidad "
             "de descarga genérica."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ MONITOREO Y OBSERVABILIDAD ══════════════════════
    dict(dominio="monitoreo", concepto="SNMP: qué es realmente y sus versiones",
         explicacion=(
             "SNMP permite a un sistema de monitoreo CONSULTAR (polling) el estado de un "
             "equipo de red, o que el equipo AVISE proactivamente (traps) ante un evento. "
             "SNMPv1/v2c usan una 'comunidad' como contraseña compartida en texto plano (poco "
             "seguro); SNMPv3 agrega autenticación y cifrado reales — usar v2c en una red "
             "insegura expone esa 'contraseña' a cualquiera que capture tráfico."
         ),
         relevancia_diagnostica=(
             "Usar la comunidad SNMP 'public' (el valor por defecto de fábrica) en producción "
             "es un hallazgo de seguridad real, no solo un detalle técnico — cualquiera en la "
             "red podría consultar (y en algunos casos hasta modificar) la configuración del "
             "equipo."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="monitoreo", concepto="Falso positivo vs falso negativo en alertas de monitoreo",
         explicacion=(
             "Un falso positivo avisa de un problema que no existe (ruido, erosiona la "
             "confianza en el sistema con el tiempo). Un falso negativo NO avisa de un "
             "problema real (silencioso, mucho más peligroso porque nadie actúa). Ajustar "
             "umbrales para eliminar falsos positivos casi siempre aumenta el riesgo de crear "
             "falsos negativos — es un trade-off, no una mejora gratuita."
         ),
         relevancia_diagnostica=(
             "Antes de 'silenciar' una alerta que molesta, evaluar qué tan grave sería un "
             "falso negativo en ese caso específico — subir un umbral para dejar de recibir "
             "avisos menores puede esconder también el aviso real cuando de verdad importe."
         ),
         fuente="Metodología general de observabilidad de sistemas"),

    # ══════════════════════ SEGURIDAD DE ENDPOINTS ══════════════════════
    dict(dominio="seguridad_endpoint", concepto="Antivirus tradicional vs EDR (Endpoint Detection and Response)",
         explicacion=(
             "Un antivirus tradicional compara archivos contra firmas conocidas de malware — "
             "no detecta amenazas nuevas (día cero) hasta que existe una firma. Un EDR "
             "monitorea COMPORTAMIENTO (qué procesos hace qué cosas, qué conexiones abre) y "
             "puede detectar actividad sospechosa aunque el archivo específico nunca se haya "
             "visto antes — a cambio, requiere más recursos y puede generar más falsos "
             "positivos que hay que triar."
         ),
         relevancia_diagnostica=(
             "Un EDR bloqueando una aplicación de negocio legítima (falso positivo) es un "
             "problema real y frecuente al desplegar EDR nuevo — antes de deshabilitarlo por "
             "completo, crear una excepción específica para esa aplicación."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad_endpoint", concepto="Ransomware: por qué los backups offline importan más que el antivirus",
         explicacion=(
             "El ransomware moderno a menudo busca activamente y cifra o borra backups "
             "conectados a la red antes de cifrar los datos principales, precisamente para "
             "eliminar la opción de restaurar sin pagar — un backup que está permanentemente "
             "conectado y accesible desde la misma red es vulnerable al mismo ataque que "
             "afecta los datos originales."
         ),
         relevancia_diagnostica=(
             "Backups accesibles desde cualquier equipo de la red en todo momento (sin "
             "aislamiento, sin copia offline/inmutable) representan el mismo riesgo que no "
             "tener backup en un escenario de ransomware real — evaluar aislamiento real, no "
             "solo existencia del backup."
         ),
         fuente="CompTIA A+ Core 2 220-1202"),

    # ══════════════════════ DIRECCIONAMIENTO IP / SUBREDES ══════════════════════
    dict(dominio="redes_ip", concepto="Máscaras de subred y por qué importan más allá de 'la IP'",
         explicacion=(
             "Una máscara de subred define qué parte de la IP identifica la RED y qué parte "
             "identifica el HOST específico — dos equipos con IPs parecidas pero en subredes "
             "distintas (según la máscara) no pueden comunicarse directamente sin pasar por un "
             "router, aunque 'se vean cerca' numéricamente."
         ),
         relevancia_diagnostica=(
             "Dos equipos que no se comunican pese a tener IPs 'parecidas' — verificar que "
             "estén realmente en la misma subred según la máscara configurada, no asumirlo "
             "por el parecido visual de las IPs."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="redes_ip", concepto="IPv6 básico: por qué coexiste con IPv4 y no lo reemplaza de golpe",
         explicacion=(
             "La mayoría de redes hoy corren en modo 'dual stack' (IPv4 e IPv6 simultáneos) — "
             "un equipo puede tener conectividad IPv4 perfecta pero problemas específicos de "
             "IPv6 (o viceversa) de forma independiente, ya que son protocolos separados con "
             "su propio enrutamiento, DNS y reglas de firewall."
         ),
         relevancia_diagnostica=(
             "Un problema de conectividad que aparece solo en ciertas aplicaciones (las que "
             "prefieren IPv6 si está disponible) mientras la mayoría funciona bien — revisar "
             "si hay un problema específico de la configuración IPv6, no solo de IPv4."
         ),
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="redes_ip", concepto="Direcciones IP privadas (RFC1918) y por qué nunca deben verse en internet",
         explicacion=(
             "Los rangos 10.0.0.0/8, 172.16.0.0/12 y 192.168.0.0/16 están reservados para uso "
             "interno y NO se enrutan en internet público — si una IP de estos rangos aparece "
             "intentando comunicarse directamente hacia afuera sin pasar por NAT, hay un "
             "problema de configuración de enrutamiento o NAT."
         ),
         relevancia_diagnostica=(
             "Un dispositivo con IP privada que 'no tiene internet' mientras otros en la misma "
             "red sí — verificar que esté usando el gateway/NAT correcto, no que le falte "
             "una IP pública propia (nunca debería tenerla)."
         ),
         fuente="CompTIA Network+ N10-009"),

    # ══════════════════════ ENERGÍA ELÉCTRICA (más allá del UPS básico) ══════════════════════
    dict(dominio="energia", concepto="Tipos de UPS: standby, line-interactive y online de doble conversión",
         explicacion=(
             "Un UPS standby solo entra en acción cuando detecta corte (con un breve tiempo de "
             "transferencia, milisegundos, que la mayoría de equipos tolera). Line-interactive "
             "regula variaciones de voltaje sin cambiar a batería. Online de doble conversión "
             "SIEMPRE alimenta desde la batería, regenerando la energía constantemente — cero "
             "tiempo de transferencia, el estándar para equipos que no toleran NINGÚN "
             "microcorte (servidores críticos, equipos médicos)."
         ),
         relevancia_diagnostica=(
             "Un servidor crítico con reinicios inexplicables coincidiendo con pequeñas "
             "variaciones de voltaje de la red eléctrica (no cortes totales) puede beneficiarse "
             "de un UPS online de doble conversión en vez de uno standby, que no reacciona a "
             "variaciones menores."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="energia", concepto="Transferencia automática a planta eléctrica: el hueco de tiempo real",
         explicacion=(
             "Una planta/generador eléctrico tarda segundos (típicamente 10-30s) en encender y "
             "estabilizarse tras un corte — el UPS es lo que cubre exactamente ESE hueco de "
             "tiempo, no un respaldo de horas. Un UPS dimensionado solo para cubrir unos "
             "minutos, en un sitio SIN generador, deja todo sin energía apenas se agota, sin "
             "ningún plan de respaldo real más allá de eso."
         ),
         relevancia_diagnostica=(
             "Antes de asumir que 'tenemos UPS, estamos cubiertos', verificar cuánto tiempo de "
             "autonomía real tiene y si existe (o no) un generador detrás — son dos capas de "
             "protección distintas con propósitos distintos."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="energia", concepto="Factor de potencia y por qué el VA de un UPS no es lo mismo que los watts reales",
         explicacion=(
             "Un UPS se especifica en VA (voltiamperios), pero la carga real de equipos "
             "electrónicos se mide en watts — la relación entre ambos (factor de potencia) "
             "varía según el tipo de carga; sobrestimar cuánta carga real soporta un UPS por "
             "confiar solo en su rating de VA puede llevar a sobrecargarlo sin saberlo."
         ),
         relevancia_diagnostica=(
             "Un UPS que se apaga o falla bajo una carga que 'en teoría' debería soportar según "
             "su VA nominal — recalcular la carga real en watts considerando el factor de "
             "potencia de los equipos conectados."
         ),
         fuente="CompTIA A+ Core 1 220-1201"),

    # ══════════════════════ PMS / HOSPITALIDAD — AMPLIACIÓN ══════════════════════
    dict(dominio="pms_integracion", concepto="Channel manager: el punto único de falla de la distribución de reservas",
         explicacion=(
             "Un 'channel manager' sincroniza disponibilidad y tarifas entre el PMS y "
             "múltiples plataformas de reserva externas (OTAs) — si falla silenciosamente, el "
             "PMS puede seguir funcionando perfecto para operación interna mientras las "
             "plataformas externas muestran disponibilidad desactualizada, generando "
             "sobreventas (overbooking) sin ninguna alerta visible en el día a día."
         ),
         relevancia_diagnostica=(
             "Sobreventas o discrepancias de disponibilidad entre canales externos y el PMS, "
             "sin ningún síntoma técnico visible en el sistema principal, apuntan al channel "
             "manager como sospechoso primario, no al PMS en sí."
         ),
         fuente="Industria hotelera -- patrón de integración documentado"),
    dict(dominio="pms_integracion", concepto="Sistemas de llaves electrónicas y su ventana de sincronización",
         explicacion=(
             "Los sistemas de llaves de habitación (RFID/tarjeta) generalmente sincronizan "
             "periódicamente con el PMS, no en tiempo real absoluto — un check-out procesado "
             "en el PMS puede tardar un intervalo de sincronización en reflejarse en el "
             "sistema de llaves, permitiendo brevemente que una tarjeta vieja siga funcionando."
         ),
         relevancia_diagnostica=(
             "'La tarjeta de un huésped que ya hizo check-out todavía abre la puerta' puede ser "
             "normal dentro de la ventana de sincronización esperada, no necesariamente una "
             "falla de seguridad — verificar el intervalo de sincronización configurado antes "
             "de escalar como incidente grave."
         ),
         fuente="Industria hotelera -- patrón de integración documentado"),
    dict(dominio="pms_integracion", concepto="Revenue management y su dependencia de datos limpios del PMS",
         explicacion=(
             "Los sistemas de gestión de ingresos (revenue management) que ajustan tarifas "
             "automáticamente dependen de datos históricos y actuales limpios del PMS — errores "
             "de integración que no se notan operativamente (una reserva mal clasificada, una "
             "tarifa mal registrada) pueden sesgar silenciosamente las decisiones automáticas "
             "de precios durante semanas antes de notarse."
         ),
         relevancia_diagnostica=(
             "Tarifas automáticas que no tienen sentido con la demanda real observada — revisar "
             "la calidad de los datos que alimentan el sistema de revenue management, no "
             "asumir que el algoritmo está mal calibrado."
         ),
         fuente="Industria hotelera -- patrón de integración documentado"),

    # ══════════════════════ METODOLOGÍA — AMPLIACIÓN ══════════════════════
    dict(dominio="metodologia", concepto="Documentar no es opcional: por qué el paso 7 de CompTIA existe",
         explicacion=(
             "Documentar qué se probó, qué funcionó y qué no, no es burocracia — es lo que "
             "convierte un incidente resuelto en conocimiento reutilizable la próxima vez que "
             "pase algo parecido. Sin documentación, cada técnico reinicia el proceso de "
             "diagnóstico desde cero aunque el mismo problema ya se haya resuelto antes."
         ),
         relevancia_diagnostica=(
             "Un problema recurrente que cada vez se diagnostica 'desde cero' pese a haberse "
             "resuelto antes, señala una falla de documentación, no de conocimiento técnico — "
             "el conocimiento existió, simplemente no quedó accesible para la próxima vez."
         ),
         fuente="Metodología CompTIA de 7 pasos"),
    dict(dominio="metodologia", concepto="Cuándo escalar en vez de seguir intentando",
         explicacion=(
             "Un ingeniero de soporte maduro reconoce cuándo un problema excede su nivel de "
             "acceso, conocimiento o autoridad, y escala explícitamente — seguir intentando "
             "indefinidamente sin escalar, en un sistema crítico de negocio, prolonga el "
             "impacto real sin garantía de resolución."
         ),
         relevancia_diagnostica=(
             "Tiempo de diagnóstico prolongado sin ningún avance medible en un sistema crítico "
             "es, en sí mismo, una señal de que debería escalarse — no es una falla admitir que "
             "algo requiere otro nivel de soporte."
         ),
         fuente="Metodología general de soporte técnico por niveles (ITIL)"),
    dict(dominio="metodologia", concepto="Comunicación con el usuario/cliente durante el diagnóstico",
         explicacion=(
             "Mantener informado a quien reportó el problema, con actualizaciones de progreso "
             "aunque no haya solución aún, reduce la percepción de que 'no se está haciendo "
             "nada' — el silencio durante un diagnóstico largo genera más fricción que el "
             "problema técnico en sí."
         ),
         relevancia_diagnostica=(
             "Quejas sobre 'falta de atención' en incidentes que sí se estaban trabajando "
             "activamente, a menudo son un problema de comunicación, no de esfuerzo técnico "
             "real — vale la pena distinguir ambos."
         ),
         fuente="Metodología general de soporte técnico (ITIL)"),

    # ══════════════════════ ECOSISTEMA UNIFI (marca real: APs + switches en Ópera) ══════════════════════
    dict(dominio="unifi", concepto="Adopción de equipos: por qué un AP/switch nuevo no aparece solo",
         explicacion=(
             "Un equipo UniFi nuevo (o reseteado de fábrica) no se integra a la red gestionada "
             "automáticamente — necesita ser 'adoptado' explícitamente por el Controller/gateway "
             "que administra el sitio. Hasta que se adopta, aparece como 'pending adoption' y "
             "NO recibe la configuración del sitio (VLANs, WiFi, políticas) aunque esté "
             "físicamente conectado y encendido."
         ),
         relevancia_diagnostica=(
             "Un AP o switch UniFi recién reemplazado que 'no aparece' en el panel, pese a "
             "tener luz de encendido y conexión de red — verificar el estado de adopción en el "
             "Controller antes de sospechar de un defecto de fábrica."
         ),
         fuente="Documentación oficial de Ubiquiti/UniFi"),
    dict(dominio="unifi", concepto="Inform URL: la dirección que un equipo UniFi necesita para reportar al Controller",
         explicacion=(
             "Cada equipo UniFi está configurado para 'reportar' (inform) a una URL específica "
             "del Controller que lo gestiona. Si el Controller cambia de IP, o el equipo se "
             "mueve a otra red donde no puede alcanzar esa URL, el equipo sigue funcionando de "
             "forma autónoma con su última configuración conocida, pero deja de reportar estado "
             "y no recibe cambios nuevos — puede parecer 'perdido' en el panel aunque siga "
             "operando la red normalmente para los clientes conectados."
         ),
         relevancia_diagnostica=(
             "Un AP que sigue dando WiFi a los huéspedes perfectamente pero aparece 'offline' o "
             "desactualizado en el Controller — revisar la conectividad hacia la inform URL "
             "configurada, no asumir que el AP en sí falló."
         ),
         fuente="Documentación oficial de Ubiquiti/UniFi"),
    dict(dominio="unifi", concepto="Mezclar switches UniFi con switches de otra marca (ej. Cisco) en la misma red",
         explicacion=(
             "UniFi gestiona sus propios switches con su Controller vía protocolos propios "
             "para VLANs, PoE y topología visual — un switch de otra marca en el medio de la "
             "topología sigue los estándares (802.1Q, LACP) pero NO aparece integrado en la "
             "vista de topología de UniFi ni se gestiona desde el mismo panel, lo que puede dar "
             "una falsa sensación de 'hueco' en el mapa de red aunque funcione correctamente a "
             "nivel de tráfico."
         ),
         relevancia_diagnostica=(
             "Un switch Cisco en medio de una red mayormente UniFi no debería tratarse como "
             "'no gestionado = sospechoso' solo por no aparecer en el panel UniFi — su "
             "configuración y salud deben revisarse por su propia interfaz de administración."
         ),
         fuente="Comunidad técnica -- interoperabilidad UniFi/Cisco documentada"),

    # ══════════════════════ MIKROTIK ROUTEROS (marca real: gateway en Ópera) ══════════════════════
    dict(dominio="mikrotik", concepto="RouterOS: configuración basada en reglas secuenciales, el orden importa",
         explicacion=(
             "En RouterOS (firewall, NAT, colas de tráfico) las reglas se evalúan en el orden "
             "en que aparecen en la lista, de arriba hacia abajo, y la primera que coincide "
             "generalmente decide el resultado — una regla correcta colocada en la posición "
             "incorrecta de la lista puede nunca llegar a aplicarse porque una regla anterior "
             "ya interceptó el tráfico."
         ),
         relevancia_diagnostica=(
             "Una regla de firewall/NAT en MikroTik que 'está bien escrita pero no hace nada' "
             "casi siempre es un problema de ORDEN en la lista, no de sintaxis — revisar qué "
             "reglas anteriores podrían estar interceptando el tráfico antes de llegar a ella."
         ),
         fuente="Documentación oficial de MikroTik RouterOS"),
    dict(dominio="mikrotik", concepto="Winbox vs acceso web vs SSH: mismas reglas, distinta vía",
         explicacion=(
             "RouterOS se puede administrar por Winbox (aplicación nativa, vía protocolo "
             "propietario), interfaz web, o SSH/consola — los tres acceden a la MISMA "
             "configuración subyacente, pero cada uno puede fallar de forma independiente "
             "(ej. el servicio Winbox deshabilitado no afecta el acceso SSH) sin que eso "
             "signifique que el equipo esté inaccesible por completo."
         ),
         relevancia_diagnostica=(
             "'No puedo entrar por Winbox' no significa que el MikroTik esté inalcanzable — "
             "probar SSH o la interfaz web antes de asumir que el equipo está caído o hay que "
             "acceder físicamente."
         ),
         fuente="Documentación oficial de MikroTik RouterOS"),
    dict(dominio="mikrotik", concepto="Reglas DROP en la cadena forward vs input",
         explicacion=(
             "La cadena 'input' filtra tráfico DIRIGIDO al router mismo (administración). La "
             "cadena 'forward' filtra tráfico que PASA a través del router hacia otra red — "
             "una regla de bloqueo puesta en la cadena equivocada no tiene ningún efecto sobre "
             "el tráfico que se pretendía bloquear, aunque parezca estar 'activa'."
         ),
         relevancia_diagnostica=(
             "Un bloqueo de IP que 'está configurado' en el MikroTik pero el tráfico sigue "
             "pasando — verificar que la regla esté en la cadena forward (para tráfico que "
             "atraviesa la red), no solo en input."
         ),
         fuente="Documentación oficial de MikroTik RouterOS"),

    # ══════════════════════ HIKVISION / NVR (marca real: cámaras en Ópera) ══════════════════════
    dict(dominio="hikvision", concepto="P2P/nube (Hik-Connect) vs acceso local directo",
         explicacion=(
             "Los NVR Hikvision suelen ofrecer acceso remoto vía su servicio de nube propio "
             "(P2P/Hik-Connect) ADEMÁS del acceso directo por IP local — el servicio de nube "
             "depende de que el NVR tenga salida a internet y que el servicio de Hikvision "
             "esté disponible; puede fallar completamente mientras el acceso local (dentro de "
             "la misma red) sigue funcionando sin problema."
         ),
         relevancia_diagnostica=(
             "'No puedo ver las cámaras desde el celular fuera del hotel' mientras localmente "
             "todo funciona bien, es un problema del servicio de nube/P2P o de la salida a "
             "internet del NVR, no de las cámaras ni de la red interna."
         ),
         fuente="Documentación técnica de sistemas Hikvision"),
    dict(dominio="hikvision", concepto="Grabación continua vs por detección de movimiento: impacto en almacenamiento",
         explicacion=(
             "Grabación continua llena el disco del NVR de forma predecible y constante. "
             "Grabación por detección de movimiento varía mucho según la actividad real de "
             "cada cámara — una cámara apuntando a una zona con mucho movimiento de "
             "aire/sombras puede grabar casi tanto como continua, agotando espacio de "
             "almacenamiento antes de lo esperado y sobrescribiendo grabaciones viejas más "
             "rápido de lo previsto."
         ),
         relevancia_diagnostica=(
             "Grabaciones de días anteriores que 'ya no están' antes del tiempo de retención "
             "esperado — revisar si alguna cámara en modo detección de movimiento está "
             "grabando mucho más de lo previsto (falsos positivos por viento, sombras, "
             "insectos frente al lente) y consumiendo el espacio de las demás."
         ),
         fuente="Documentación técnica de sistemas Hikvision"),

    # ══════════════════════ CONTROL DE ACCESO ZKTECO (marca real en Ópera) ══════════════════════
    dict(dominio="zkteco", concepto="Modos de comunicación: TCP/IP vs RS485",
         explicacion=(
             "Los equipos ZKTeco pueden conectarse a la red por TCP/IP directo (más simple, "
             "cada lector es un dispositivo de red independiente) o por RS485 en cadena "
             "(varios lectores comparten un solo cable hacia un controlador central) — el modo "
             "RS485 significa que un problema en UN punto de la cadena (un cable, un "
             "terminador mal puesto) puede afectar a TODOS los lectores conectados después de "
             "ese punto, no solo a uno."
         ),
         relevancia_diagnostica=(
             "Varios lectores de control de acceso fallando juntos, en el mismo momento, sin "
             "relación evidente entre ellos por red, es la firma de una cadena RS485 con un "
             "problema físico en un punto compartido — no tratarlos como fallas individuales "
             "no relacionadas."
         ),
         fuente="Documentación técnica de sistemas de control de acceso ZKTeco"),
    dict(dominio="zkteco", concepto="Degradación del sensor de huella con el tiempo y el uso",
         explicacion=(
             "Los sensores ópticos de huella digital acumulan grasa, suciedad y microrayones "
             "con el uso diario intensivo (típico en un hotel con rotación alta de personal y "
             "huéspedes) — la tasa de falsos rechazos sube gradualmente con el desgaste físico "
             "del sensor, no por un cambio de configuración."
         ),
         relevancia_diagnostica=(
             "Aumento gradual (no súbito) de rechazos de huella a lo largo de meses, en un "
             "equipo con mucho uso diario, sugiere limpieza o reemplazo del sensor antes que "
             "recalibración de software."
         ),
         fuente="Documentación técnica de sistemas de control de acceso ZKTeco"),

    # ══════════════════════ TERMINALES DE PAGO INGENICO (marca real en Ópera) ══════════════════════
    dict(dominio="ingenico", concepto="Conexión IP vs línea telefónica/GPRS en datáfonos",
         explicacion=(
             "Un terminal de pago puede procesar transacciones por IP (red del comercio, más "
             "rápido) o por línea telefónica/GPRS como respaldo — cuando la red IP falla, "
             "algunos modelos hacen 'fallback' automático al canal de respaldo sin que el "
             "cajero note ningún cambio visible, salvo transacciones más lentas de lo normal."
         ),
         relevancia_diagnostica=(
             "Transacciones de tarjeta notablemente más lentas de lo habitual, sin que el "
             "datáfono reporte error, puede ser un fallback silencioso a un canal de respaldo "
             "más lento por un problema de red IP no evidente todavía."
         ),
         fuente="Conocimiento general de terminales de pago electrónico"),
    dict(dominio="ingenico", concepto="Por qué un datáfono necesita su propia VLAN aislada",
         explicacion=(
             "Los terminales de pago manejan datos de tarjetas y están sujetos a normas de "
             "seguridad de pagos (PCI-DSS) que exigen aislamiento de red — compartir la misma "
             "VLAN que equipos no relacionados con pagos (WiFi de huéspedes, impresoras "
             "generales) amplía innecesariamente la superficie de auditoría de cumplimiento y "
             "el riesgo real de exposición de esos datos."
         ),
         relevancia_diagnostica=(
             "Un datáfono funcionando técnicamente bien pero compartiendo VLAN con equipos no "
             "relacionados con pagos es un hallazgo de cumplimiento tan importante como "
             "cualquier falla técnica — no depende de que algo 'se rompa' para ser relevante."
         ),
         fuente="Normas de seguridad de datos de pago (PCI-DSS)"),

    # ══════════════════════ IMPRESORAS DE INYECCIÓN DE TINTA (Epson WorkForce -- distinto de láser y térmica) ══════════════════════
    dict(dominio="impresoras_inkjet", concepto="Por qué una inkjet de uso comercial (Epson WorkForce/PrecisionCore) falla distinto a una láser",
         explicacion=(
             "Una impresora de inyección de tinta comercial no tiene tóner ni fusor — tiene "
             "cabezales de impresión que pueden obstruirse si la impresora pasa mucho tiempo "
             "sin usarse (la tinta se seca en las boquillas), y tanques o cartuchos de tinta "
             "independientes por color que se agotan a ritmos distintos según el contenido "
             "impreso (más texto negro consume más negro, más fotos consumen más color)."
         ),
         relevancia_diagnostica=(
             "Impresión con rayas o colores faltantes en una impresora de este tipo que estuvo "
             "varios días sin usarse (ej. tras un fin de semana de baja ocupación) — ejecutar "
             "una limpieza de cabezales antes de asumir una falla de hardware permanente."
         ),
         fuente="CompTIA A+ Core 1 220-1201 / documentación de impresoras Epson comerciales"),
    dict(dominio="impresoras_inkjet", concepto="Almohadillas de mantenimiento (maintenance box) y su fin de vida",
         explicacion=(
             "Muchas inkjet comerciales recolectan el exceso de tinta de limpieza en una "
             "almohadilla/caja de mantenimiento interna con capacidad finita — cuando se "
             "satura, la impresora se detiene por completo con un código de error específico, "
             "independientemente de si quedan cartuchos de tinta con contenido."
         ),
         relevancia_diagnostica=(
             "Una impresora inkjet que se niega a imprimir con un código de error específico "
             "de mantenimiento, aunque los cartuchos de tinta muestren nivel alto, casi "
             "siempre es la almohadilla de mantenimiento saturada, no falta de tinta."
         ),
         fuente="Documentación de impresoras Epson comerciales"),

    # ══════════════════════ IMPRESORAS TÉRMICAS BIXOLON (marca real, POS en Ópera) ══════════════════════
    dict(dominio="impresoras_termicas_pos", concepto="Sensor de papel y detección de 'fin de rollo' temprana",
         explicacion=(
             "Las impresoras térmicas POS tienen un sensor óptico que detecta el rollo de "
             "papel agotándose — algunos rollos con el reverso de color oscuro o con marcas "
             "impresas cerca del final pueden disparar el sensor antes de que el papel "
             "realmente se agote, generando una alerta de 'sin papel' con rollo aún utilizable."
         ),
         relevancia_diagnostica=(
             "Alertas de 'sin papel' frecuentes con rollos que a simple vista aún tienen "
             "papel — revisar el tipo/marca de rollo en uso, puede ser una incompatibilidad "
             "de sensor con ese papel específico, no una falla del sensor en sí."
         ),
         fuente="Documentación técnica de impresoras térmicas POS (Bixolon y equivalentes)"),
    dict(dominio="impresoras_termicas_pos", concepto="Cortador automático: causa frecuente de atascos",
         explicacion=(
             "El mecanismo de corte automático de papel en impresoras térmicas POS es una "
             "pieza móvil con desgaste — acumula residuos de papel y polvo con el tiempo, y es "
             "una de las causas más comunes de 'atasco' reportado como falla general de la "
             "impresora cuando en realidad es solo el cortador."
         ),
         relevancia_diagnostica=(
             "Impresión correcta del contenido pero fallo o atasco justo al momento de cortar "
             "el papel — limpiar/revisar el mecanismo de corte específicamente, no la "
             "impresora completa."
         ),
         fuente="Documentación técnica de impresoras térmicas POS (Bixolon y equivalentes)"),
]


_SEED_RULES: list[dict[str, str]] = [
    # ── Cableado estructurado ──
    dict(dominio="cableado", patron="Puerto con errores CRC/FCS creciendo",
         causa_probable="Cable dañado, mal ponchado o conector sucio -- no es falla del switch",
         recomendacion="Cambiar el cable/patch cord primero, antes de sospechar del equipo",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Cable UTP tendido a más de 100 metros",
         causa_probable="Pérdida de señal por exceder el límite del estándar de cableado",
         recomendacion="Verificar longitud real; usar repetidor, switch intermedio o fibra si excede 100m",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Enlace nuevo funciona pero muy por debajo de la velocidad esperada",
         causa_probable="Cable de categoría insuficiente para la velocidad (ej. Cat5 para Gigabit)",
         recomendacion="Verificar categoría real del cable instalado, no asumir por la etiqueta",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Errores intermitentes sin patrón horario claro, cable cerca de motores o luces fluorescentes",
         causa_probable="Interferencia electromagnética sobre cable UTP sin blindaje",
         recomendacion="Usar cable blindado (STP) o reubicar el tendido lejos de la fuente de interferencia",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Desconexiones intermitentes al mover el cable o el equipo",
         causa_probable="Conector RJ45 flojo o mal prensado",
         recomendacion="Reponchar el conector antes de reemplazar el equipo",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="cableado", patron="AP o cámara PoE no enciende pero el cable y el puerto están bien",
         causa_probable="El switch no entrega el estándar PoE requerido (802.3af/at/bt) o está saturado en potencia total",
         recomendacion="Verificar el presupuesto de energía PoE del switch, no solo la conectividad",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Varios equipos PoE fallan a la vez justo después de agregar uno nuevo",
         causa_probable="El switch superó su presupuesto total de energía PoE",
         recomendacion="Redistribuir equipos entre switches o usar inyector PoE dedicado",
         fuente="CompTIA Network+ N10-009"),

    # ── Switching (capa 2) ──
    dict(dominio="switching", patron="Toda la red se pone lenta de golpe sin ningún equipo reportado como caído",
         causa_probable="Loop de red (bucle) por un cable mal conectado creando un ciclo",
         recomendacion="Revisar spanning tree y conexiones redundantes accidentales antes que equipos individuales",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", patron="Errores de colisión en un puerto (no CRC)",
         causa_probable="Discordancia de dúplex (duplex mismatch) entre switch y equipo conectado",
         recomendacion="Igualar la configuración de dúplex en ambos extremos (o autonegociación en ambos)",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", patron="Tráfico de difusión (broadcast) anormalmente alto en toda la red",
         causa_probable="Loop de red o un dispositivo defectuoso inundando la red de broadcasts",
         recomendacion="Aislar la red segmento por segmento hasta ubicar el origen",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", patron="VLAN configurada en un switch pero el tráfico no llega a otro switch de otra marca",
         causa_probable="Etiquetado 802.1Q mal configurado en el enlace troncal -- común al mezclar marcas distintas",
         recomendacion="Verificar que ambos extremos del trunk permitan exactamente las mismas VLANs",
         fuente="CompTIA Network+ N10-009 + comunidad técnica (interoperabilidad entre marcas)"),
    dict(dominio="switching", patron="Switch pierde su configuración tras un corte de energía",
         causa_probable="La configuración no se guardó de forma persistente tras el último cambio",
         recomendacion="Confirmar guardado de configuración inmediatamente después de cualquier cambio",
         fuente="CompTIA Network+ N10-009"),

    # ── WAN / enrutamiento (capa 3) ──
    dict(dominio="wan", patron="Pérdida de paquetes solo en ciertas horas del día (horas pico)",
         causa_probable="Saturación del enlace a internet contratado, no una falla del equipo",
         recomendacion="Confirmar con el proveedor el ancho de banda contratado vs. consumo real medido",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", patron="Servicios internos no responden desde afuera aunque el router esté online",
         causa_probable="Doble NAT o direccionamiento duplicado entre router y firewall",
         recomendacion="Revisar la topología de enrutamiento completa, evitar NAT anidado innecesario",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", patron="El failover a un segundo proveedor de internet no ocurre automáticamente",
         causa_probable="Rutas estáticas o métricas de prioridad mal definidas",
         recomendacion="Verificar métricas de ruta y probar el failover real, no solo la configuración teórica",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", patron="Aplicaciones críticas lentas mientras hay tráfico de WiFi de invitados/huéspedes",
         causa_probable="Falta de priorización de tráfico (QoS) entre tráfico crítico y tráfico de invitados",
         recomendacion="Separar y priorizar el tráfico crítico (pagos, voz) sobre el de invitados",
         fuente="CompTIA Network+ N10-009"),

    # ── WiFi / RF ──
    dict(dominio="wifi", patron="WiFi lento en zonas con muchos dispositivos conectados a la vez",
         causa_probable="Densidad de dispositivos supera la capacidad del canal, no un fallo del AP",
         recomendacion="Agregar APs o reducir potencia de transmisión para células más pequeñas",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="Un dispositivo permanece conectado a un AP lejano en vez de uno más cercano (sticky client)",
         causa_probable="Falta de roaming asistido (band steering, 802.11k/v/r)",
         recomendacion="Habilitar roaming asistido si el hardware lo soporta",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="Interferencia intermitente en la banda 2.4GHz",
         causa_probable="Microondas, teléfonos inalámbricos u otros APs cercanos en el mismo canal",
         recomendacion="Cambiar de canal y preferir 5GHz para los dispositivos compatibles",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="APs de una marca pierden conexión al usar un router/gateway de otra marca",
         causa_probable="Incompatibilidad de configuración VLAN/trunk entre marcas distintas -- documentado en comunidad técnica (ej. MikroTik + UniFi)",
         recomendacion="Verificar configuración exacta de trunk en ambos extremos antes de sospechar de hardware defectuoso",
         fuente="Comunidad técnica (foros oficiales de fabricantes)"),
    dict(dominio="wifi", patron="Cobertura débil en un salón con mucha gente reunida temporalmente",
         causa_probable="Un solo AP no alcanza para la densidad temporal de dispositivos",
         recomendacion="Dimensionar APs adicionales o temporales para eventos, no depender de la cobertura normal",
         fuente="CompTIA Network+ N10-009"),

    # ── Hardware / servidores ──
    dict(dominio="hardware", patron="UPS reporta estado normal pero no sostiene la carga en un corte real",
         causa_probable="Batería degradada (vida útil típica 2-4 años, aunque el estado se vea 'OK')",
         recomendacion="Probar la autonomía real periódicamente, no confiar solo en el estado superficial",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="hardware", patron="Servidor con temperatura alta y reinicios inesperados",
         causa_probable="Ventilación insuficiente del rack o filtros de polvo obstruidos",
         recomendacion="Revisar temperatura ambiente y limpieza física antes de sospechar de la placa",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="hardware", patron="Disco con errores SMART crecientes pero aún operativo",
         causa_probable="Señal temprana de falla de disco inminente",
         recomendacion="Reemplazar preventivamente, no esperar a que falle por completo",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="hardware", patron="Servidor responde ping perfecto pero la aplicación principal no funciona",
         causa_probable="El servicio/aplicación específica está caído aunque el sistema operativo esté vivo",
         recomendacion="Verificar el estado del servicio puntual, no solo la conectividad de red",
         fuente="CompTIA A+ Core 2 220-1202"),

    # ── Impresoras / POS ──
    dict(dominio="impresoras", patron="Impresora responde ping pero no imprime",
         causa_probable="Cola de impresión (spooler) colgada -- no es problema de red",
         recomendacion="Reiniciar el servicio de impresión antes de revisar cualquier cable",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="impresoras", patron="Impresora térmica con impresión débil, cortada o ilegible",
         causa_probable="Cabezal térmico sucio o rodillo desgastado",
         recomendacion="Limpiar el cabezal térmico antes de asumir una falla eléctrica",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="impresoras", patron="Impresora láser con manchas repetitivas en el mismo lugar de cada página",
         causa_probable="Tóner o unidad de fusión defectuosa",
         recomendacion="Identificar el patrón/distancia de la mancha para aislar la pieza responsable",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="impresoras", patron="Un pedido de punto de venta (POS) no llega a la impresora de cocina/bar aunque el POS reporte 'enviado'",
         causa_probable="Falla de configuración lógica POS→impresora dentro del propio software, no de la red física",
         recomendacion="Verificar la configuración de impresión dentro del software POS antes de revisar cableado",
         fuente="Industria de hospitalidad (patrón documentado de integración POS)"),
    dict(dominio="impresoras", patron="Un terminal de pago queda sin conexión mientras otros equipos de la misma zona están bien",
         causa_probable="Problema puntual de ese punto de red específico (cable/puerto), no algo compartido",
         recomendacion="Diagnosticar ese punto específico sin escalarlo como incidente de zona completa",
         fuente="Metodología general de diagnóstico por capas"),

    # ── Seguridad ──
    dict(dominio="seguridad", patron="Tráfico anómalo desde la red de huéspedes/invitados hacia equipos administrativos",
         causa_probable="Falta de segmentación (VLANs) entre la red pública y la red interna",
         recomendacion="Aislar completamente ambas redes con VLANs separadas",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad", patron="Terminal de pago en la misma red lógica que el WiFi público",
         causa_probable="Incumplimiento de buenas prácticas de seguridad de datos de pago (segmentación PCI)",
         recomendacion="Segmentar el tráfico de pagos en una VLAN dedicada y restringida",
         fuente="Buenas prácticas de seguridad de pagos (PCI-DSS, aplicable a cualquier negocio con datáfonos)"),
    dict(dominio="seguridad", patron="Múltiples intentos de inicio de sesión fallidos seguidos de uno exitoso",
         causa_probable="Posible ataque de fuerza bruta que tuvo éxito",
         recomendacion="Forzar cambio de contraseña y revisar accesos recientes de esa cuenta",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad", patron="Dispositivo desconocido detectado en la red administrativa",
         causa_probable="Conexión no autorizada a un puerto o VLAN interna",
         recomendacion="Aislar el puerto/VLAN afectado y verificar físicamente antes de reconectar",
         fuente="CompTIA A+ Core 2 220-1202"),

    # ── Windows / Active Directory ──
    dict(dominio="windows_ad", patron="Un equipo no puede iniciar sesión con cuenta de dominio aunque la red funcione bien",
         causa_probable="Pérdida de la relación de confianza (trust) del equipo con el dominio",
         recomendacion="Volver a unir el equipo al dominio en vez de sospechar de la red",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="windows_ad", patron="Una cuenta de usuario se bloquea repetidamente",
         causa_probable="Política de bloqueo tras intentos fallidos, a menudo por un dispositivo con la contraseña vieja guardada",
         recomendacion="Revisar dispositivos (móviles, impresoras, servicios) con la contraseña anterior almacenada",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="windows_ad", patron="Un controlador de dominio no replica cambios a otro controlador",
         causa_probable="Problema de conectividad o de DNS interno entre controladores de dominio",
         recomendacion="Verificar conectividad y configuración DNS entre los controladores antes de sospechar de AD en sí",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="windows_ad", patron="Una impresora de red deja de funcionar solo para un usuario, no para todos",
         causa_probable="Problema del perfil o configuración de ESE usuario/estación específica",
         recomendacion="Descartar la red inmediatamente y enfocar el diagnóstico en el equipo/perfil de ese usuario",
         fuente="CompTIA A+ Core 2 220-1202"),

    # ── Integración de sistemas de negocio (PMS/POS, aplica a cualquier hotel/negocio) ──
    dict(dominio="pms_integracion", patron="El PMS y el POS muestran 'conectado' pero los consumos no se cargan correctamente",
         causa_probable="La integración puede estar técnicamente 'conectada' sin que el flujo de datos real esté funcionando",
         recomendacion="Probar con una transacción real de prueba -- nunca confiar solo en el estado que muestra la pantalla",
         fuente="Industria hotelera (Shiji Insights, BringIT Professional Services -- hallazgo validado con fuentes externas)"),
    dict(dominio="pms_integracion", patron="El reporte de cierre nocturno (night audit) del PMS falla sin ninguna alerta visible",
         causa_probable="Proceso batch nocturno con error silencioso, no notificado",
         recomendacion="Verificar los logs del proceso a la mañana siguiente, no asumir éxito solo por ausencia de alerta",
         fuente="Industria hotelera -- patrón operativo documentado"),
    dict(dominio="pms_integracion", patron="Las estaciones de recepción/POS no logran conectarse a la base de datos central en horas pico",
         causa_probable="Límite de conexiones concurrentes de la base de datos alcanzado",
         recomendacion="Revisar y ajustar la configuración de conexiones máximas de la base de datos",
         fuente="Buenas prácticas de administración de bases de datos (genérico, aplica a cualquier sistema cliente-servidor)"),
    dict(dominio="pms_integracion", patron="Un sistema secundario (llaves, control de acceso) no sincroniza tras una operación en el sistema principal",
         causa_probable="Falla puntual de esa integración específica, no un problema de red general",
         recomendacion="Aislar y diagnosticar ese flujo de integración por separado, sin mezclarlo con incidentes de red",
         fuente="Industria hotelera -- patrón de integración documentado"),

    # ── Metodología (siempre aplicable, cualquier dominio) ──
    dict(dominio="metodologia", patron="Cualquier falla nueva sin diagnóstico previo",
         causa_probable="—",
         recomendacion="Descartar primero la capa física (cable, puerto, energía) antes de sospechar de software o aplicaciones -- es la causa más común y la más rápida de verificar",
         fuente="Metodología CompTIA de 7 pasos (identificar → teorizar → probar → plan → implementar → verificar → documentar)"),
    dict(dominio="metodologia", patron="Un problema afecta a un solo usuario o equipo",
         causa_probable="—",
         recomendacion="Casi nunca es de red compartida -- enfocar el diagnóstico en ese punto específico primero",
         fuente="Metodología general de diagnóstico por capas"),
    dict(dominio="metodologia", patron="Un problema afecta a varios equipos a la vez, en la misma zona física",
         causa_probable="—",
         recomendacion="Casi siempre comparte una causa común (switch, energía, uplink) -- no tratar cada equipo por separado",
         fuente="Metodología general de diagnóstico por capas"),
    dict(dominio="metodologia", patron="Un sistema muestra estado 'conectado' o 'en línea'",
         causa_probable="—",
         recomendacion="No asumir que el flujo de datos real funciona -- verificar con una prueba funcional real cuando sea posible",
         fuente="Industria hotelera + metodología CompTIA (paso 3: probar la teoría)"),
    dict(dominio="metodologia", patron="Un equipo que fallaba parece haberse resuelto solo, sin ninguna acción tomada",
         causa_probable="—",
         recomendacion="Dar seguimiento igual -- puede repetirse y la causa real seguir sin resolverse",
         fuente="Metodología general de diagnóstico"),

    # ── Cableado y PoE (ampliación) ──
    dict(dominio="cableado", patron="Enlace certificado Cat6a con errores solo bajo alta temperatura ambiente",
         causa_probable="Degradación de las propiedades eléctricas del cable por calor excesivo en la ruta del tendido",
         recomendacion="Revisar si el cable pasa cerca de fuentes de calor (techos sin aislar, ductos) antes de sospechar del equipo",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Switch PoE reinicia solo al conectar varios equipos de golpe",
         causa_probable="Pico de demanda de energía (inrush current) al energizar varios puertos PoE simultáneamente supera la fuente",
         recomendacion="Conectar los equipos de forma escalonada y verificar la capacidad real de la fuente del switch",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="cableado", patron="Un solo hilo de un cable multipar (ej. telefonía) con ruido, el resto bien",
         causa_probable="Daño físico puntual o empalme defectuoso en ese par específico",
         recomendacion="Aislar y probar par por par antes de descartar todo el cable",
         fuente="CompTIA A+ Core 1 220-1201"),

    # ── Switching (ampliación) ──
    dict(dominio="switching", patron="Un puerto trunk deja de pasar UNA VLAN específica, las demás funcionan bien",
         causa_probable="Esa VLAN fue removida de la lista permitida en el trunk en uno de los dos extremos",
         recomendacion="Comparar la lista de VLANs permitidas en ambos extremos del trunk, no revisar solo uno",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", patron="Switch con uso de CPU alto sostenido sin tráfico aparentemente alto",
         causa_probable="Tormenta de broadcast/multicast de bajo volumen pero constante, o un proceso de control (STP recalculando) en loop",
         recomendacion="Revisar el detalle de qué proceso consume CPU en el switch, no solo el tráfico de datos",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="switching", patron="Dispositivos con IP fija dejan de comunicarse tras cambiar un switch por otro de otra marca",
         causa_probable="Configuración de VLAN/trunk no migrada correctamente al nuevo equipo",
         recomendacion="Verificar configuración de VLANs y trunk del switch nuevo contra el que reemplazó, no asumir plug-and-play",
         fuente="Comunidad técnica -- interoperabilidad entre marcas"),

    # ── WAN (ampliación) ──
    dict(dominio="wan", patron="VPN se conecta pero las aplicaciones internas no cargan datos grandes",
         causa_probable="Problema de MTU/fragmentación por el overhead de encapsulado VPN",
         recomendacion="Ajustar el MTU del túnel VPN antes de sospechar de las aplicaciones o el firewall",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", patron="Servicio expuesto a internet no es alcanzable pese a tener el puerto abierto en el router",
         causa_probable="El ISP entrega una IP de CGNAT, no una IP pública real",
         recomendacion="Confirmar con el ISP si la IP asignada es pública real antes de seguir revisando configuración local",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wan", patron="Llamadas de voz entrecortadas con velocidad de internet medida como 'buena'",
         causa_probable="Jitter alto o falta de QoS priorizando el tráfico de voz, no falta de ancho de banda",
         recomendacion="Medir jitter específicamente y revisar configuración de QoS antes de pedir más ancho de banda al proveedor",
         fuente="CompTIA Network+ N10-009"),

    # ── WiFi (ampliación) ──
    dict(dominio="wifi", patron="Portal cautivo no aparece en un dispositivo específico, en otros sí",
         causa_probable="Ese sistema operativo/navegador usa DNS-over-HTTPS o falla su detección de red con portal",
         recomendacion="Abrir manualmente un sitio HTTP simple para forzar la redirección, no asumir que el portal está roto",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="Dispositivos viejos no se conectan a una red configurada recientemente",
         causa_probable="La red quedó configurada solo en WPA3, incompatible con hardware antiguo",
         recomendacion="Usar modo mixto WPA2/WPA3 si hay dispositivos antiguos que deben coexistir",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="Cobertura débil en un pasillo largo pese a tener un AP potente en el centro",
         causa_probable="Un AP omnidireccional no es la mejor opción geométrica para espacios alargados",
         recomendacion="Evaluar antenas sectoriales orientadas o APs adicionales a lo largo del pasillo, no solo subir potencia",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="wifi", patron="Enlace inalámbrico punto a punto exterior se degrada progresivamente durante meses",
         causa_probable="Crecimiento vegetal o construcción nueva invadiendo la zona de Fresnel del enlace",
         recomendacion="Inspeccionar físicamente la línea entre ambos puntos, no solo revisar configuración",
         fuente="CompTIA Network+ N10-009"),

    # ── Hardware / almacenamiento ──
    dict(dominio="hardware", patron="Servidor con RAID 5 lento tras la falla y reemplazo de un disco",
         causa_probable="El proceso de reconstrucción (rebuild) de paridad consume recursos intensivamente mientras dura",
         recomendacion="Es esperado durante la reconstrucción; monitorear que termine y no ocurra una segunda falla en ese periodo",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="backup", patron="Backup incremental de varios días falla al intentar restaurar",
         causa_probable="Uno de los incrementales intermedios de la cadena está corrupto o incompleto",
         recomendacion="Verificar la integridad de toda la cadena periódicamente, no solo del backup más reciente",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="backup", patron="Nadie puede confirmar si el backup realmente sirve para restaurar",
         causa_probable="Nunca se ha hecho una prueba de restauración real, solo se confía en que 'el proceso terminó sin error'",
         recomendacion="Programar pruebas de restauración periódicas, no solo monitorear que el backup corra",
         fuente="CompTIA A+ Core 1 220-1201"),

    # ── Voz IP ──
    dict(dominio="voz_ip", patron="Llamada conecta y timbra pero no hay audio en ningún sentido",
         causa_probable="Tráfico RTP bloqueado por firewall o mal manejado por NAT, mientras SIP sí pasa",
         recomendacion="Revisar reglas de firewall/NAT específicas para el rango de puertos RTP, no solo el puerto SIP",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="voz_ip", patron="Mala calidad de llamadas solo cuando hay varias simultáneas",
         causa_probable="El códec de voz en uso (ej. G.711 sin comprimir) satura el enlace disponible con varias llamadas a la vez",
         recomendacion="Evaluar cambiar a un códec más eficiente (ej. G.729) para el enlace WAN disponible",
         fuente="CompTIA Network+ N10-009"),

    # ── Cámaras / CCTV ──
    dict(dominio="camaras_cctv", patron="Grabación con cuadros perdidos en el NVR pese a que cada cámara responde bien individualmente",
         causa_probable="Saturación del ancho de banda agregado hacia el NVR por la suma de todas las cámaras",
         recomendacion="Revisar el consumo total de banda del sistema completo, no cámara por cámara",
         fuente="Conocimiento técnico de sistemas CCTV/vigilancia IP"),
    dict(dominio="camaras_cctv", patron="Cámara nueva de otra marca conectada al NVR pero le faltan funciones avanzadas",
         causa_probable="Incompatibilidad de perfil ONVIF entre la cámara y el NVR (ambos 'ONVIF' pero de distinto nivel)",
         recomendacion="Verificar qué perfil ONVIF soporta cada equipo antes de asumir compatibilidad total",
         fuente="Conocimiento técnico de sistemas CCTV/vigilancia IP"),

    # ── Control de acceso ──
    dict(dominio="control_acceso", patron="Un usuario dado de baja en el sistema central todavía puede acceder por un lector específico",
         causa_probable="Ese lector opera en modo standalone y no ha sincronizado el cambio de permisos",
         recomendacion="Forzar sincronización de ese lector de inmediato -- es un riesgo de seguridad, tratarlo con prioridad",
         fuente="Conocimiento técnico de sistemas de control de acceso"),
    dict(dominio="control_acceso", patron="El biométrico rechaza frecuentemente a personal autorizado",
         causa_probable="Sensibilidad configurada muy estricta (baja tasa de falso acepto a costa de más falsos rechazos)",
         recomendacion="Ajustar sensibilidad con conocimiento del trade-off de seguridad, no solo por comodidad",
         fuente="Conocimiento técnico de sistemas de control de acceso"),

    # ── Bases de datos ──
    dict(dominio="bases_datos", patron="Varias estaciones distintas se congelan a la vez usando la misma aplicación",
         causa_probable="Bloqueo (lock) de base de datos sostenido por una transacción lenta o mal cerrada",
         recomendacion="Revisar transacciones activas y bloqueos en la base de datos antes de sospechar de la red",
         fuente="Buenas prácticas de administración de bases de datos, genérico"),
    dict(dominio="bases_datos", patron="Sistema que antes era rápido se ha ido poniendo lento con los meses",
         causa_probable="Crecimiento de datos sin mantenimiento de índices en la base de datos",
         recomendacion="Evaluar mantenimiento/reindexado de la base de datos antes de recomendar hardware nuevo",
         fuente="Buenas prácticas de administración de bases de datos, genérico"),

    # ── Linux ──
    dict(dominio="linux", patron="Un servicio que funcionaba bien no vuelve a arrancar tras un reinicio o corte de energía",
         causa_probable="El servicio nunca fue habilitado (enabled) para arranque automático, solo se inició manualmente antes",
         recomendacion="Verificar el estado de habilitación del servicio en el gestor de arranque, no solo su configuración",
         fuente="CompTIA A+ Core 2 220-1202 / administración de sistemas Linux"),
    dict(dominio="linux", patron="Un proceso funciona al probarlo manualmente pero falla al ejecutarse automáticamente",
         causa_probable="Diferencia de permisos entre la prueba manual (con privilegios elevados) y la ejecución automática real",
         recomendacion="Revisar con qué usuario/permisos corre el proceso automático, no repetir la prueba manual como diagnóstico",
         fuente="CompTIA A+ Core 2 220-1202 / administración de sistemas Linux"),

    # ── Nube / cloud ──
    dict(dominio="cloud", patron="Aplicación en la nube se siente lenta pese a tener buen ancho de banda medido",
         causa_probable="Latencia base hacia el servicio (distancia geográfica), no falta de capacidad",
         recomendacion="Medir latencia (RTT) hacia el servicio específico antes de invertir en más ancho de banda",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="cloud", patron="No se puede resolver un problema de un servicio en la nube desde el lado del cliente",
         causa_probable="El modelo de servicio (SaaS/PaaS) delega esa responsabilidad completamente al proveedor",
         recomendacion="Identificar el modelo de servicio antes de seguir invirtiendo tiempo local -- puede requerir ticket al proveedor",
         fuente="CompTIA A+ Core 1 220-1201"),

    # ── Monitoreo ──
    dict(dominio="monitoreo", patron="Equipo de red configurado con comunidad SNMP 'public' en producción",
         causa_probable="Configuración de fábrica nunca cambiada",
         recomendacion="Cambiar a una comunidad SNMP propia y restringir el acceso solo al servidor de monitoreo -- es un hallazgo de seguridad real",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="monitoreo", patron="Se silenciaron varias alertas por ser 'ruido' y luego pasó desapercibido un problema real",
         causa_probable="Ajuste de umbrales que redujo falsos positivos pero aumentó el riesgo de falsos negativos",
         recomendacion="Revisar cada umbral silenciado evaluando qué tan grave sería no enterarse del problema real, no solo la molestia del ruido",
         fuente="Metodología general de observabilidad de sistemas"),

    # ── Seguridad de endpoints ──
    dict(dominio="seguridad_endpoint", patron="Software de EDR/antivirus nuevo bloquea una aplicación de negocio legítima",
         causa_probable="Falso positivo por comportamiento no reconocido de una aplicación poco común",
         recomendacion="Crear una excepción específica para esa aplicación en vez de deshabilitar la protección por completo",
         fuente="CompTIA A+ Core 2 220-1202"),
    dict(dominio="seguridad_endpoint", patron="Los backups están siempre accesibles desde cualquier equipo de la red corporativa",
         causa_probable="Falta de aislamiento real entre backups y la red de producción",
         recomendacion="Evaluar backups offline/inmutables como protección ante ransomware, no solo backups conectados permanentemente",
         fuente="CompTIA A+ Core 2 220-1202"),

    # ── Direccionamiento IP ──
    dict(dominio="redes_ip", patron="Dos equipos con IPs numéricamente parecidas no logran comunicarse directamente",
         causa_probable="Están en subredes distintas según la máscara configurada, aunque las IPs 'se vean cerca'",
         recomendacion="Verificar la máscara de subred de ambos antes de asumir un problema de cableado o switch",
         fuente="CompTIA Network+ N10-009"),
    dict(dominio="redes_ip", patron="Un dispositivo con IP privada no tiene salida a internet mientras otros similares sí",
         causa_probable="Configuración incorrecta de gateway/NAT en ese dispositivo específico",
         recomendacion="Revisar la configuración de gateway de ese equipo puntual antes de sospechar de la red completa",
         fuente="CompTIA Network+ N10-009"),

    # ── Energía eléctrica ──
    dict(dominio="energia", patron="Servidor crítico con reinicios inexplicables coincidiendo con variaciones menores de voltaje",
         causa_probable="UPS tipo standby que no reacciona ante variaciones de voltaje, solo ante cortes totales",
         recomendacion="Evaluar un UPS online de doble conversión para equipos que no toleran ninguna variación",
         fuente="CompTIA A+ Core 1 220-1201"),
    dict(dominio="energia", patron="UPS que se apaga bajo una carga que en teoría debería soportar según su capacidad nominal",
         causa_probable="La capacidad nominal está en VA, no en watts reales -- la carga real puede exceder lo calculado",
         recomendacion="Recalcular la carga real en watts considerando el factor de potencia de los equipos conectados",
         fuente="CompTIA A+ Core 1 220-1201"),

    # ── PMS / hospitalidad (ampliación) ──
    dict(dominio="pms_integracion", patron="Sobreventas o disponibilidad desactualizada en plataformas externas de reserva",
         causa_probable="Falla silenciosa del channel manager, no del PMS principal",
         recomendacion="Diagnosticar el channel manager como sospechoso primario antes que el PMS",
         fuente="Industria hotelera -- patrón de integración documentado"),
    dict(dominio="pms_integracion", patron="La tarjeta de un huésped que ya hizo check-out todavía abre su habitación",
         causa_probable="Ventana normal de sincronización entre el PMS y el sistema de llaves electrónicas",
         recomendacion="Verificar el intervalo de sincronización configurado antes de tratarlo como falla de seguridad grave",
         fuente="Industria hotelera -- patrón de integración documentado"),

    # ── UniFi (marca real en Ópera: APs + algunos switches) ──
    dict(dominio="unifi", patron="AP o switch UniFi recién instalado no aparece en el panel de gestión",
         causa_probable="El equipo está encendido y conectado pero no ha sido adoptado por el Controller",
         recomendacion="Verificar el estado de adopción en el Controller antes de sospechar de un defecto de fábrica",
         fuente="Documentación oficial de Ubiquiti/UniFi"),
    dict(dominio="unifi", patron="AP UniFi da WiFi normal a los huéspedes pero aparece offline/desactualizado en el panel",
         causa_probable="El equipo no puede alcanzar la inform URL del Controller, aunque sigue operando con su última configuración",
         recomendacion="Revisar conectividad hacia el Controller, no reiniciar el AP asumiendo que falló",
         fuente="Documentación oficial de Ubiquiti/UniFi"),
    dict(dominio="unifi", patron="Un switch de otra marca (ej. Cisco) no aparece en la topología visual de UniFi",
         causa_probable="Es esperado -- UniFi solo gestiona/visualiza sus propios equipos, no switches de terceros aunque funcionen correctamente",
         recomendacion="Revisar la salud de ese switch por su propia interfaz de administración, no por el panel UniFi",
         fuente="Comunidad técnica -- interoperabilidad UniFi/Cisco documentada"),

    # ── MikroTik (marca real del gateway en Ópera) ──
    dict(dominio="mikrotik", patron="Una regla de firewall/NAT en MikroTik parece bien escrita pero no tiene efecto",
         causa_probable="Una regla anterior en el orden de la lista ya está interceptando ese tráfico",
         recomendacion="Revisar el orden completo de reglas, no solo la sintaxis de la regla nueva",
         fuente="Documentación oficial de MikroTik RouterOS"),
    dict(dominio="mikrotik", patron="No se puede entrar al MikroTik por Winbox",
         causa_probable="El servicio Winbox puede estar deshabilitado o bloqueado sin que el resto del equipo esté inaccesible",
         recomendacion="Probar acceso por SSH o interfaz web antes de asumir que el equipo está caído",
         fuente="Documentación oficial de MikroTik RouterOS"),
    dict(dominio="mikrotik", patron="Un bloqueo de IP configurado en MikroTik no impide que esa IP siga pasando tráfico",
         causa_probable="La regla de bloqueo está en la cadena 'input' en vez de 'forward' (o viceversa según el caso)",
         recomendacion="Verificar en qué cadena está la regla -- forward para tráfico que atraviesa la red, input para tráfico dirigido al router mismo",
         fuente="Documentación oficial de MikroTik RouterOS"),

    # ── Hikvision (marca real de NVR/cámaras en Ópera) ──
    dict(dominio="hikvision", patron="No se puede ver las cámaras desde fuera del hotel, pero localmente funcionan bien",
         causa_probable="Falla del servicio de nube/P2P (Hik-Connect) o de la salida a internet del NVR, no de las cámaras",
         recomendacion="Verificar el servicio de nube y la conectividad a internet del NVR antes de revisar cada cámara",
         fuente="Documentación técnica de sistemas Hikvision"),
    dict(dominio="hikvision", patron="Grabaciones de días anteriores desaparecen antes del tiempo de retención esperado",
         causa_probable="Una o más cámaras en modo detección de movimiento están grabando de más por falsos positivos (viento, sombras, insectos)",
         recomendacion="Revisar qué cámara consume más espacio de lo esperado antes de asumir falla del NVR o del disco",
         fuente="Documentación técnica de sistemas Hikvision"),

    # ── ZKTeco (marca real del control de acceso biométrico en Ópera) ──
    dict(dominio="zkteco", patron="Varios lectores de control de acceso fallan juntos, sin relación evidente por red",
         causa_probable="Problema físico en un punto compartido de una cadena RS485, afectando a todos los lectores posteriores",
         recomendacion="Tratarlos como un solo incidente de cadena, no como fallas individuales no relacionadas",
         fuente="Documentación técnica de sistemas de control de acceso ZKTeco"),
    dict(dominio="zkteco", patron="Aumento gradual de rechazos de huella a lo largo de varios meses en un lector de alto uso",
         causa_probable="Desgaste físico del sensor óptico por uso intensivo diario",
         recomendacion="Limpiar o reemplazar el sensor antes de recalibrar el software",
         fuente="Documentación técnica de sistemas de control de acceso ZKTeco"),

    # ── Ingenico (marca real de los datáfonos en Ópera) ──
    dict(dominio="ingenico", patron="Transacciones de tarjeta notablemente más lentas de lo habitual, sin error reportado",
         causa_probable="Fallback silencioso a un canal de respaldo (línea telefónica/GPRS) por un problema de red IP no evidente aún",
         recomendacion="Revisar la conectividad IP del datáfono aunque no reporte ningún error visible",
         fuente="Conocimiento general de terminales de pago electrónico"),
    dict(dominio="ingenico", patron="Datáfono funcionando bien técnicamente pero en la misma VLAN que equipos no relacionados con pagos",
         causa_probable="Falta de segmentación de red para el entorno de datos de tarjetas",
         recomendacion="Segmentar en una VLAN dedicada -- es un hallazgo de cumplimiento real, no depende de que algo falle primero",
         fuente="Normas de seguridad de datos de pago (PCI-DSS)"),

    # ── Impresoras inkjet comerciales (Epson WorkForce, real en recepción de Ópera) ──
    dict(dominio="impresoras_inkjet", patron="Impresión con rayas o colores faltantes tras varios días sin uso",
         causa_probable="Tinta seca en las boquillas del cabezal por inactividad prolongada",
         recomendacion="Ejecutar limpieza de cabezales antes de asumir una falla de hardware permanente",
         fuente="Documentación de impresoras Epson comerciales"),
    dict(dominio="impresoras_inkjet", patron="Impresora inkjet se niega a imprimir con código de error específico pese a tinta alta",
         causa_probable="Almohadilla/caja de mantenimiento interna saturada",
         recomendacion="Revisar el código de error específico -- casi siempre indica mantenimiento saturado, no falta de tinta",
         fuente="Documentación de impresoras Epson comerciales"),

    # ── Impresoras térmicas POS (Bixolon, real en Ópera) ──
    dict(dominio="impresoras_termicas_pos", patron="Alertas frecuentes de 'sin papel' con el rollo visiblemente con papel restante",
         causa_probable="Incompatibilidad del sensor óptico con el tipo/marca específica de papel en uso",
         recomendacion="Revisar el tipo de rollo antes de asumir falla del sensor",
         fuente="Documentación técnica de impresoras térmicas POS (Bixolon y equivalentes)"),
    dict(dominio="impresoras_termicas_pos", patron="Impresión correcta pero falla o atasco justo al cortar el papel",
         causa_probable="Desgaste o residuos acumulados en el mecanismo de corte automático",
         recomendacion="Limpiar/revisar el cortador específicamente, no la impresora completa",
         fuente="Documentación técnica de impresoras térmicas POS (Bixolon y equivalentes)"),
]


def seed_if_empty(aprobado_por: str = "") -> int:
    """Siembra la tabla SOLO si está vacía -- idempotente, seguro de llamar
    en cada arranque sin duplicar filas."""
    init_db()
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        count = con.execute("SELECT COUNT(*) FROM conocimiento_general").fetchone()[0]
        if count > 0:
            return 0
        for r in _SEED_RULES:
            con.execute(
                "INSERT INTO conocimiento_general "
                "(dominio, patron, causa_probable, recomendacion, fuente, aprobado_por) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["dominio"], r["patron"], r["causa_probable"], r["recomendacion"],
                 r["fuente"], aprobado_por),
            )
        con.commit()
        log.info("conocimiento_general: sembradas %d reglas iniciales", len(_SEED_RULES))
        return len(_SEED_RULES)
    finally:
        con.close()


def list_rules(dominio: str = "", limit: int = 200) -> list[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        if dominio:
            rows = con.execute(
                "SELECT * FROM conocimiento_general WHERE dominio=? ORDER BY id LIMIT ?",
                (dominio, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM conocimiento_general ORDER BY dominio, id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dominios() -> list[str]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        rows = con.execute(
            "SELECT DISTINCT dominio FROM conocimiento_general ORDER BY dominio"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def seed_teoria_if_empty(aprobado_por: str = "") -> int:
    """Siembra la tabla de teoría SOLO si está vacía -- idempotente."""
    init_db_teoria()
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        count = con.execute("SELECT COUNT(*) FROM conocimiento_teoria").fetchone()[0]
        if count > 0:
            return 0
        for t in _SEED_TEORIA:
            con.execute(
                "INSERT INTO conocimiento_teoria "
                "(dominio, concepto, explicacion, relevancia_diagnostica, fuente, aprobado_por) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["dominio"], t["concepto"], t["explicacion"],
                 t["relevancia_diagnostica"], t["fuente"], aprobado_por),
            )
        con.commit()
        log.info("conocimiento_teoria: sembrados %d conceptos iniciales", len(_SEED_TEORIA))
        return len(_SEED_TEORIA)
    finally:
        con.close()


def list_teoria(dominio: str = "", limit: int = 300) -> list[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        if dominio:
            rows = con.execute(
                "SELECT * FROM conocimiento_teoria WHERE dominio=? ORDER BY id LIMIT ?",
                (dominio, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM conocimiento_teoria ORDER BY dominio, id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dominios_teoria() -> list[str]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        rows = con.execute(
            "SELECT DISTINCT dominio FROM conocimiento_teoria ORDER BY dominio"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


# ── Fase 2 (sesión 81 cont., 6 sep 2026): conectar al razonamiento del cerebro ──
# Mapa palabra clave -> dominio, basado en los nombres REALES de equipos que
# ya existen en Ópera (ver infra_devices) -- "SW " para switches, "AP " para
# UniFi, "Bixolon"/"Hikvision"/"ZK"/"Ingenico" para las marcas confirmadas en
# el inventario real. Determinístico por diseño (código decide qué dominios
# aplican, no el LLM) -- mismo principio anti-alucinación que pattern_analysis.py.
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mikrotik":                 ("mikrotik",),
    "wan":                      ("mikrotik", "router", "gateway"),
    "switching":                ("sw ", "sw-", "sw1", "sw2", "sw3", "switch"),
    "cableado":                 ("sw ", "switch", "ap "),
    "unifi":                    ("ap ", "unifi"),
    "wifi":                     ("ap ",),
    "impresoras_termicas_pos":  ("bixolon", "pos"),
    "impresoras_inkjet":        ("epson", "wf-", "workforce"),
    "impresoras":               ("imp ", "impresora"),
    "hikvision":                ("hikvision", "nvr"),
    "camaras_cctv":             ("camara", "cámara", "nvr"),
    "zkteco":                   ("zk", "biometrico", "biométrico"),
    "control_acceso":           ("biometrico", "biométrico", "control de acceso"),
    "ingenico":                 ("ingenico", "terminal pago", "datafono", "datáfono"),
    "hardware":                 ("srv", "servidor"),
    "windows_ad":               ("srvad", "dominio"),
    "bases_datos":              ("srvzeus", "pms", "base de datos"),
    "pms_integracion":          ("pms", "zeus", "pos"),
}


def _matching_domains(entity_names: list[str]) -> set[str]:
    texto = " | ".join((n or "").lower() for n in entity_names)
    dominios_match = {
        dominio for dominio, kws in _DOMAIN_KEYWORDS.items()
        if any(kw in texto for kw in kws)
    }
    return dominios_match or {"metodologia"}


def matching_domains(entity_names: list[str]) -> list[str]:
    """Wrapper público -- para que brain.py guarde qué dominios se usaron en
    una conclusión y pueda retroalimentar la confianza cuando se confirme."""
    return sorted(_matching_domains(entity_names))


def registrar_confirmacion(dominios: list[str]) -> int:
    """Fase 4 (6 sep 2026): cerrar el ciclo de aprendizaje -- cuando un
    ticket que el cerebro abrió se cierra (se confirmó que la causa era
    correcta), sube veces_confirmado en las reglas de esos dominios. No es
    atribución perfecta (no sabemos cuál regla EXACTA usó el LLM, solo qué
    dominios se le ofrecieron), pero es una señal real y determinística,
    no una suposición."""
    if not dominios:
        return 0
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        placeholders = ",".join("?" * len(dominios))
        cur = con.execute(
            f"UPDATE conocimiento_general SET veces_confirmado = veces_confirmado + 1, "
            f"updated_at = datetime('now') WHERE dominio IN ({placeholders})",
            dominios,
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def registrar_refutacion(dominios: list[str]) -> int:
    """Contraparte de registrar_confirmacion -- para cuando se sepa que la
    causa que se dio NO era la correcta (ej. el ticket se reabre pronto)."""
    if not dominios:
        return 0
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        placeholders = ",".join("?" * len(dominios))
        cur = con.execute(
            f"UPDATE conocimiento_general SET veces_refutado = veces_refutado + 1, "
            f"updated_at = datetime('now') WHERE dominio IN ({placeholders})",
            dominios,
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def find_relevant(entity_names: list[str], max_reglas: int = 6, max_teoria: int = 4) -> tuple[list[dict], list[dict]]:
    """Reglas + teoría relevante para un grupo de entidades, por nombre.
    Determinístico (coincidencia de palabra clave), nunca decidido por el LLM."""
    dominios_match = _matching_domains(entity_names)
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        reglas: list[dict] = []
        teoria: list[dict] = []
        for d in dominios_match:
            reglas.extend(dict(r) for r in con.execute(
                "SELECT * FROM conocimiento_general WHERE dominio=? LIMIT 3", (d,)
            ).fetchall())
            teoria.extend(dict(r) for r in con.execute(
                "SELECT * FROM conocimiento_teoria WHERE dominio=? LIMIT 2", (d,)
            ).fetchall())
        return reglas[:max_reglas], teoria[:max_teoria]
    finally:
        con.close()


def format_for_prompt(entity_names: list[str]) -> str:
    """Bloque de texto compacto para inyectar en el prompt del cerebro --
    solo lo relevante a las entidades del cluster actual, no las 212 enteras."""
    reglas, teoria = find_relevant(entity_names)
    if not reglas and not teoria:
        return ""
    partes = ["Conocimiento técnico validado relevante (usar si aplica, no forzar si no encaja):"]
    for r in reglas:
        partes.append(
            f"- [regla/{r['dominio']}] {r['patron']} → {r['causa_probable']} → {r['recomendacion']}"
        )
    for t in teoria:
        partes.append(
            f"- [teoría/{t['dominio']}] {t['concepto']}: {t['relevancia_diagnostica']}"
        )
    return "\n".join(partes)


init_db()
init_db_teoria()
