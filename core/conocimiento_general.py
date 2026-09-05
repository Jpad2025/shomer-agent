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


init_db()
init_db_teoria()
