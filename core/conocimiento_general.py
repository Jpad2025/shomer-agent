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
             "(PoE++) tipo 3 llega a 60W/51W y tipo 4 a 90W en la fuente (~71.3W garantizados en "
             "el dispositivo), pensado para APs WiFi6 de alta "
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
         fuente="Metodología de troubleshooting de 7 pasos (estándar unificado de Shomer, CompTIA Network+ N10-009 — 5.1)"),

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
             "El PoE puede viajar sobre los mismos pares que llevan datos (modo A, pines 1-2 y "
             "3-6 -- funciona igual en 10/100 y Gigabit porque la alimentación DC no interfiere "
             "con la señal) o sobre los pares 'libres' en cableado 10/100 (modo B, pines 4-5 y "
             "7-8 -- no aplica en Gigabit puro porque ahí los 4 pares ya llevan datos). Si un "
             "inyector PoE y un switch/AP usan modos distintos de forma "
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
             "G.711 no comprime (mejor calidad; el codec corre a 64kbps, pero el ancho de banda "
             "real por llamada sube a ~80-87kbps al sumar el overhead de RTP/IP y capa 2) — "
             "ideal con ancho de banda de sobra. G.729 comprime mucho más (el codec corre a "
             "8kbps, pero el ancho de banda real por llamada con ese mismo overhead es de "
             "~24-31kbps, no 8kbps) a costa de algo de calidad y más uso de CPU para "
             "codificar/decodificar — preferible en enlaces WAN limitados, aunque el ahorro "
             "real ronda un tercio del ancho de banda de G.711, no un octavo. "
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
    dict(dominio="metodologia", concepto="Documentar no es opcional: por qué el paso 7 existe",
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
         fuente="Metodología de troubleshooting de 7 pasos (estándar unificado de Shomer, CompTIA Network+ N10-009 — 5.1)"),
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

    # ══════════════════════ SEGURIDAD — ARQUITECTURA (CompTIA Security+ SY0-701) ══════════════════════
    dict(dominio="seguridad_arquitectura", concepto="Defensa en profundidad: por qué una sola capa nunca basta",
         explicacion=(
             "Defensa en profundidad significa que ningún control de seguridad individual "
             "(firewall, antivirus, segmentación) debe ser el único obstáculo entre un atacante "
             "y el objetivo — se combinan varias capas independientes para que la falla de UNA "
             "no comprometa todo. En Shomer esto ya existe en la práctica: Hunter (IDS/firewall "
             "perimetral) + segmentación VLAN + autenticación de panel son capas distintas, no "
             "una sola."
         ),
         relevancia_diagnostica=(
             "Si se propone eliminar o debilitar un control 'porque ya hay otro' (ej. 'no hace "
             "falta VLAN separada porque el firewall ya bloquea'), es una señal de que se está "
             "perdiendo una capa de defensa en profundidad, no una simplificación segura."
         ),
         fuente="CompTIA Security+ SY0-701 — Security Architecture"),
    dict(dominio="seguridad_arquitectura", concepto="Zero Trust: nunca confiar solo por estar 'adentro' de la red",
         explicacion=(
             "El modelo tradicional asume que todo lo que está dentro del perímetro de red es "
             "confiable. Zero Trust asume lo contrario: cada solicitud se verifica "
             "explícitamente sin importar si viene de adentro o afuera de la red — relevante "
             "porque un atacante que ya logró entrar a la red de huéspedes no debería, solo por "
             "eso, tener camino libre hacia sistemas administrativos."
         ),
         relevancia_diagnostica=(
             "Un hallazgo de auditoría de red que dice 'tráfico interno no verificado entre "
             "segmentos' no es un tecnicismo — es la brecha exacta que Zero Trust busca cerrar; "
             "priorizarlo aunque el tráfico venga de 'dentro' de la red del hotel."
         ),
         fuente="CompTIA Security+ SY0-701 — Security Architecture"),
    dict(dominio="seguridad_arquitectura", concepto="Superficie de ataque y por qué cada servicio expuesto cuenta",
         explicacion=(
             "Cada puerto abierto, servicio expuesto o cuenta con acceso es una posible vía de "
             "entrada — reducir la superficie de ataque significa desactivar/cerrar todo lo que "
             "no se usa activamente, no solo proteger lo que sí se usa. Un servicio olvidado y "
             "sin actualizar, aunque nadie lo use, sigue siendo una puerta abierta."
         ),
         relevancia_diagnostica=(
             "Hallazgos de auditoría de red mostrando puertos abiertos de servicios que 'nadie "
             "recuerda para qué son' deben tratarse como riesgo real, no ignorarse por "
             "antigüedad — cerrarlos si no tienen un uso activo confirmado."
         ),
         fuente="CompTIA Security+ SY0-701 — Threats, Vulnerabilities and Mitigations"),

    # ══════════════════════ GESTIÓN DE VULNERABILIDADES (CompTIA CySA+ CS0-003) ══════════════════════
    dict(dominio="gestion_vulnerabilidades", concepto="CVSS: por qué la puntuación de severidad no basta sola",
         explicacion=(
             "El puntaje CVSS (0-10) mide la severidad TÉCNICA teórica de una vulnerabilidad, "
             "pero no considera el contexto real del sitio — una vulnerabilidad CVSS 9 en un "
             "equipo aislado sin acceso a internet puede ser menos urgente en la práctica que "
             "una CVSS 6 en un equipo expuesto y crítico para el negocio. Priorizar solo por "
             "puntaje, sin contexto, lleva a gastar esfuerzo en el orden equivocado."
         ),
         relevancia_diagnostica=(
             "Al revisar hallazgos de auditoría de red (`run_network_audit_scan`), priorizar "
             "por severidad Y exposición/criticidad real del equipo, no solo por la etiqueta "
             "'crítico/alto/medio/bajo' de forma aislada."
         ),
         fuente="CompTIA CySA+ CS0-003 — Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", concepto="Falsos positivos en escaneos automáticos de vulnerabilidades",
         explicacion=(
             "Un escaneo automático (como el de Tracker/Hunter contra los equipos de la red) "
             "puede reportar un servicio como 'vulnerable' basándose solo en la versión "
             "anunciada por el banner, sin confirmar si el parche de seguridad específico ya "
             "fue aplicado por separado (backport) — algunos fabricantes actualizan la "
             "seguridad sin cambiar el número de versión visible."
         ),
         relevancia_diagnostica=(
             "Un hallazgo de 'versión vulnerable' en un equipo de marca con soporte activo "
             "(ej. MikroTik, UniFi) merece verificación manual antes de escalarse como crítico "
             "-- puede ser un falso positivo por versión de banner desactualizada en el "
             "reporte."
         ),
         fuente="CompTIA CySA+ CS0-003 — Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", concepto="Ventana de exposición: el tiempo entre descubrir y corregir",
         explicacion=(
             "El riesgo real de una vulnerabilidad no es solo su severidad, sino cuánto tiempo "
             "queda expuesta sin corregir — un hallazgo de hace meses sin resolver representa "
             "más riesgo acumulado que uno nuevo de alta severidad recién descubierto, aunque "
             "el segundo 'se vea peor' en el reporte de hoy."
         ),
         relevancia_diagnostica=(
             "Al priorizar la lista de hallazgos, dar peso también a la ANTIGÜEDAD del "
             "hallazgo sin resolver, no solo a su severidad puntual del día de hoy."
         ),
         fuente="CompTIA CySA+ CS0-003 — Vulnerability Management"),

    # ══════════════════════ SIEM / ANÁLISIS DE LOGS (CompTIA CySA+ — directo a Hunter/Suricata/Wazuh) ══════════════════════
    dict(dominio="siem_analisis", concepto="Indicadores de Compromiso (IoC) vs ruido normal de internet",
         explicacion=(
             "Un IDS perimetral (como Suricata en Hunter) genera alertas por firmas conocidas "
             "de ataque — la mayoría de tráfico de internet hoy incluye escaneos automatizados "
             "constantes de bots que prueban puertos/vulnerabilidades masivamente sin ningún "
             "interés específico en un sitio ('ruido de fondo de internet'). Un IoC real "
             "(indicador de compromiso genuino) es evidencia de que algo YA tuvo éxito, no solo "
             "que alguien lo intentó."
         ),
         relevancia_diagnostica=(
             "Un bloqueo de una IP externa con firma de 'escaneo genérico' no es automáticamente "
             "un ataque dirigido — la mayoría es ruido de fondo de internet; reservar la "
             "urgencia real para señales de éxito (ej. tráfico saliente inusual DESPUÉS de una "
             "alerta, no solo la alerta de entrada en sí)."
         ),
         fuente="CompTIA CySA+ CS0-003 — Security Operations"),
    dict(dominio="siem_analisis", concepto="Correlación de eventos: por qué un evento aislado dice menos que un patrón",
         explicacion=(
             "Un SIEM maduro no mira eventos individuales en aislamiento — busca CADENAS: un "
             "escaneo de puertos seguido de un intento de login fallido seguido de tráfico "
             "saliente inusual, en ese orden y desde el mismo origen, es mucho más indicativo "
             "que cualquiera de esos tres eventos por separado."
         ),
         relevancia_diagnostica=(
             "Esto es exactamente el principio detrás de la correlación temporal que ya hace "
             "el cerebro de Shomer (`brain.py`) — agrupar eventos relacionados en el tiempo en "
             "vez de tratarlos aislados es aplicar este mismo principio de SIEM a la red del "
             "hotel, no solo a seguridad perimetral."
         ),
         fuente="CompTIA CySA+ CS0-003 — Security Operations"),
    dict(dominio="siem_analisis", concepto="Threat hunting: buscar activamente, no solo esperar la alerta",
         explicacion=(
             "El 'threat hunting' parte de una hipótesis ('¿podría haber algo que las reglas "
             "automáticas no detectan?') y busca activamente evidencia, en vez de esperar "
             "pasivamente a que una firma conocida dispare una alerta — útil precisamente para "
             "amenazas nuevas que aún no tienen firma."
         ),
         relevancia_diagnostica=(
             "Revisar periódicamente tráfico o accesos fuera de lo común AUNQUE ninguna alerta "
             "automática haya saltado, especialmente en sistemas críticos (pagos, dominio) — "
             "no depender solo de que Hunter/Suricata avise."
         ),
         fuente="CompTIA CySA+ CS0-003 — Security Operations"),

    # ══════════════════════ RESPUESTA A INCIDENTES (CompTIA Security+ / CySA+) ══════════════════════
    dict(dominio="respuesta_incidentes", concepto="Las fases formales de respuesta a incidentes",
         explicacion=(
             "Preparación (tener el plan ANTES de que pase algo) → Detección y análisis → "
             "Contención (aislar, sin necesariamente resolver aún) → Erradicación (eliminar la "
             "causa) → Recuperación (volver a operación normal) → Lecciones aprendidas. Saltarse "
             "'contención' para ir directo a 'arreglar' puede permitir que el problema se siga "
             "propagando mientras se investiga."
         ),
         relevancia_diagnostica=(
             "Ante un hallazgo de seguridad real (no falso positivo), la primera acción "
             "debería ser aislar/contener (ej. bloquear la IP, aislar el equipo) ANTES de "
             "investigar a fondo la causa — no al revés."
         ),
         fuente="CompTIA Security+ SY0-701 / CySA+ CS0-003 — Incident Response"),
    dict(dominio="respuesta_incidentes", concepto="Por qué el sistema de escalamiento de Shomer ya sigue este principio",
         explicacion=(
             "El módulo de escalamiento de incidentes (`incident_escalation.py`) agrupa "
             "eventos relacionados en una ventana de tiempo, pide confirmación al técnico, y "
             "si no hay respuesta escala a un coordinador — esto es, en esencia, el proceso "
             "formal de respuesta a incidentes aplicado a fallas de infraestructura, no solo a "
             "seguridad: detección, intento de confirmación humana, y escalamiento si no se "
             "resuelve a tiempo."
         ),
         relevancia_diagnostica=(
             "Cuando se diseñan nuevos flujos de alerta en Shomer, el patrón ya probado "
             "(detectar → agrupar → confirmar → escalar si no hay respuesta) es el punto de "
             "partida correcto, no hay que reinventar la metodología desde cero."
         ),
         fuente="CompTIA CySA+ CS0-003 — Incident Response, aplicado al diseño existente de Shomer"),

    # ══════════════════════ SERVER+ — ADMINISTRACIÓN Y ALTA DISPONIBILIDAD ══════════════════════
    dict(dominio="servidor_administracion", concepto="Clustering y alta disponibilidad: qué resuelve realmente",
         explicacion=(
             "Un clúster de servidores permite que si UNO falla, otro tome su lugar "
             "automáticamente (failover) — pero solo protege contra falla de HARDWARE/proceso, "
             "no contra errores de datos o de aplicación: si la base de datos se corrompe, el "
             "servidor de respaldo hereda la MISMA corrupción, un clúster no sustituye un "
             "backup real."
         ),
         relevancia_diagnostica=(
             "'Tenemos servidores redundantes' no es lo mismo que 'tenemos protección contra "
             "pérdida de datos' — son dos protecciones distintas para riesgos distintos (falla "
             "de hardware vs. corrupción/error de datos)."
         ),
         fuente="CompTIA Server+ SK0-005 — Server Administration"),
    dict(dominio="servidor_administracion", concepto="Almacenamiento SAN/NAS vs almacenamiento local del servidor",
         explicacion=(
             "Almacenamiento local vive dentro del servidor mismo — si el servidor falla "
             "físicamente, el almacenamiento puede fallar con él. SAN/NAS separa el "
             "almacenamiento en un equipo dedicado en la red, permitiendo que varios "
             "servidores lo compartan y que uno pueda fallar sin llevarse los datos — a cambio, "
             "ahora depende de la red para acceder a sus propios datos."
         ),
         relevancia_diagnostica=(
             "Un servidor con almacenamiento en SAN/NAS que 'se congela' o pierde acceso a "
             "datos puede tener el problema en la RED hacia el storage, no en el servidor "
             "mismo ni en el disco -- diagnosticar la conectividad de almacenamiento por "
             "separado."
         ),
         fuente="CompTIA Server+ SK0-005 — Server Hardware Installation and Management"),
    dict(dominio="servidor_administracion", concepto="Ventanas de mantenimiento y por qué existen formalmente",
         explicacion=(
             "Una ventana de mantenimiento es un periodo acordado de antemano donde se espera "
             "interrupción de servicio para aplicar cambios — su propósito es que una "
             "interrupción PLANEADA en horario de bajo impacto sea preferible a que el mismo "
             "cambio cause una interrupción NO planeada en horario crítico."
         ),
         relevancia_diagnostica=(
             "Cambios de configuración de servidores/red en horario operativo alto (check-in, "
             "check-out, comidas) sin ventana de mantenimiento acordada es un riesgo evitable, "
             "independientemente de qué tan seguro parezca el cambio en teoría."
         ),
         fuente="CompTIA Server+ SK0-005 — Server Administration"),

    # ══════════════════════ SERVER+ — DISASTER RECOVERY (más allá de backup básico) ══════════════════════
    dict(dominio="servidor_recuperacion_desastres", concepto="RTO y RPO: las dos preguntas que definen un plan de recuperación",
         explicacion=(
             "RPO (Recovery Point Objective) responde '¿cuántos datos podemos permitirnos "
             "perder?' (ej. si el último backup fue hace 24h, el RPO es 24h). RTO (Recovery "
             "Time Objective) responde '¿cuánto tiempo podemos estar caídos?' — un sistema "
             "crítico como el PMS necesita RPO/RTO mucho más ajustados que un archivo de "
             "reportes históricos, y el plan de backup debe diseñarse distinto para cada uno, "
             "no aplicar la misma frecuencia a todo por igual."
         ),
         relevancia_diagnostica=(
             "Antes de definir 'cada cuánto se hace backup' de un sistema, primero preguntar "
             "cuánta pérdida de datos y cuánto tiempo de caída tolera el negocio para ESE "
             "sistema específico -- no todos los sistemas necesitan el mismo nivel de "
             "protección."
         ),
         fuente="CompTIA Server+ SK0-005 — Security and Disaster Recovery"),
    dict(dominio="servidor_recuperacion_desastres", concepto="Sitio de recuperación frío, tibio y caliente",
         explicacion=(
             "Un sitio frío (cold site) es solo espacio/infraestructura básica, se necesita "
             "tiempo considerable para operar ahí. Un sitio tibio (warm site) tiene sistemas "
             "parcialmente configurados y datos no del todo actualizados. Un sitio caliente "
             "(hot site) es una réplica activa, lista para operar casi de inmediato -- cada "
             "nivel cuesta progresivamente más pero reduce el RTO real ante una pérdida total "
             "del sitio principal."
         ),
         relevancia_diagnostica=(
             "Para un sitio sin ningún plan de recuperación ante pérdida total (incendio, "
             "robo), la pregunta relevante no es 'cuál construir' sino 'cuál es aceptable "
             "dado el costo' -- incluso un plan frío bien documentado es mejor que ninguno."
         ),
         fuente="CompTIA Server+ SK0-005 — Security and Disaster Recovery"),

    # ══════════════════════ A+ CORE 1 (220-1201) — TEMARIO OFICIAL COMPLETO ══════════════════════
    # Trabajado con el documento oficial de objetivos (versión 2.0, 2024), no de memoria --
    # dominios: 1.0 Mobile Devices (13%), 2.0 Networking (23%), 3.0 Hardware (25%),
    # 4.0 Virtualization/Cloud (11%), 5.0 Hardware and Network Troubleshooting (28%).

    # ── 1.0 Dispositivos móviles (dominio completo, antes casi sin cubrir) ──
    dict(dominio="dispositivos_moviles", concepto="Componentes de hardware reemplazables en dispositivos móviles",
         explicacion=(
             "A diferencia de un PC de escritorio, en móviles/laptops los componentes "
             "reemplazables típicos son: batería, teclado, RAM (cuando es modular), "
             "disco (HDD/SSD), tarjetas inalámbricas, conector de antena WiFi, cámara/webcam y "
             "micrófono — cada uno con procedimientos y riesgos distintos (ej. la batería en "
             "equipos sellados requiere despegar adhesivos, riesgo de dañar la carcasa)."
         ),
         relevancia_diagnostica=(
             "Antes de diagnosticar un problema de conectividad WiFi en un laptop como 'falla "
             "de tarjeta', confirmar que el conector de antena esté bien asentado -- es un "
             "punto de falla común tras un servicio de mantenimiento previo."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 1.1 Mobile Devices"),
    dict(dominio="dispositivos_moviles", concepto="Métodos de conexión y accesorios de dispositivos móviles",
         explicacion=(
             "USB-C ha ido reemplazando microUSB/miniUSB por ser reversible y soportar más "
             "energía/datos. NFC permite comunicación de muy corto alcance (pagos, "
             "emparejamiento rápido). Tethering/hotspot comparte la conexión celular del "
             "móvil con otros dispositivos -- consume datos del plan y batería "
             "significativamente más rápido que el uso normal."
         ),
         relevancia_diagnostica=(
             "Un dispositivo usado como hotspot con batería agotándose mucho más rápido de lo "
             "normal no es una falla de batería -- es el consumo esperado de esa función, no "
             "hay que reemplazar nada."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 1.2 Mobile Devices"),
    dict(dominio="dispositivos_moviles", concepto="Gestión de dispositivos móviles (MDM): corporativo vs BYOD",
         explicacion=(
             "MDM permite aplicar configuraciones y políticas remotamente. En modalidad "
             "corporativa, la empresa controla el dispositivo completo. En BYOD (dispositivo "
             "propio del empleado), el MDM típicamente solo gestiona un contenedor separado "
             "de apps/datos corporativos, sin tocar el resto del teléfono personal -- son "
             "modelos de control muy distintos aunque ambos se llamen 'MDM'."
         ),
         relevancia_diagnostica=(
             "Al perder o dar de baja un dispositivo BYOD, un borrado remoto (`remote wipe`) "
             "mal configurado puede borrar el teléfono COMPLETO del empleado en vez de solo el "
             "contenedor corporativo -- verificar el modo de MDM configurado antes de emitir "
             "esa orden."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 1.3 Mobile Devices"),

    # ── 2.0 Redes — lo específico que faltaba de A+ Core 1 ──
    dict(dominio="redes_ip", concepto="Puertos TCP/UDP más comunes y su propósito",
         explicacion=(
             "Los puertos clave a reconocer: 20-21 FTP, 22 SSH, 23 Telnet (inseguro, sin "
             "cifrar), 25 SMTP (correo saliente), 53 DNS, 67/68 DHCP, 80 HTTP, 110 POP3, 143 "
             "IMAP, 389 LDAP (directorio), 443 HTTPS, 445 SMB/CIFS (compartición de archivos "
             "Windows), 3389 RDP (escritorio remoto). Cada uno tiene un propósito específico y "
             "bloquearlo sin saber para qué se usa puede romper un servicio sin síntoma obvio "
             "de 'por qué'."
         ),
         relevancia_diagnostica=(
             "Un hallazgo de auditoría marcando 'puerto 445 abierto' como riesgo debe "
             "evaluarse sabiendo que es compartición de archivos Windows -- cerrarlo sin más "
             "puede romper el acceso a carpetas compartidas legítimas del negocio."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 2.1 Networking"),
    dict(dominio="redes_ip", concepto="TCP vs UDP: confiable y ordenado vs rápido y sin garantías",
         explicacion=(
             "TCP confirma la entrega de cada paquete y los reordena si llegan desordenados "
             "-- ideal para datos que deben llegar completos (archivos, páginas web). UDP no "
             "confirma nada, es más rápido pero puede perder paquetes sin aviso -- se usa para "
             "voz/video en tiempo real, donde es preferible perder un paquete que esperar a "
             "que se reenvíe (eso generaría más retraso que el paquete perdido)."
         ),
         relevancia_diagnostica=(
             "Pérdida de paquetes en una app basada en UDP (voz, video) no genera errores "
             "visibles del protocolo -- se percibe como calidad degradada, no como una "
             "conexión que 'falla' de forma evidente."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 2.1 Networking"),
    dict(dominio="redes_ip", concepto="Tipos de red por alcance: PAN, LAN, MAN, WAN, SAN, WLAN",
         explicacion=(
             "PAN (personal, ej. Bluetooth entre un teléfono y audífonos), LAN (una ubicación), "
             "WLAN (LAN inalámbrica), MAN (una ciudad, poco común hoy), WAN (conecta sitios "
             "distintos, ej. entre sucursales), SAN (red dedicada solo para almacenamiento, "
             "separada del tráfico normal de datos) -- cada una implica tecnología y alcance "
             "distintos, no son sinónimos de 'la red'."
         ),
         relevancia_diagnostica=(
             "Un problema de rendimiento de almacenamiento en un entorno con SAN dedicada debe "
             "diagnosticarse en la red de almacenamiento específicamente, no en la LAN general "
             "-- son infraestructuras físicamente distintas aunque compartan el mismo edificio."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 2.7 Networking"),
    dict(dominio="redes_ip", concepto="Herramientas físicas de diagnóstico de red y para qué sirve cada una",
         explicacion=(
             "Crimper (poncha conectores RJ45), ponchadora/punchdown tool (fija cables a un "
             "patch panel), probador de cable (verifica continuidad pin por pin), certificador "
             "(mide parámetros reales de transmisión), tonificador/toner probe (encuentra "
             "físicamente un cable específico entre muchos siguiendo un tono audible), "
             "loopback plug (prueba un puerto sin necesidad de otro equipo al otro extremo), "
             "network tap (copia tráfico para análisis sin interrumpirlo)."
         ),
         relevancia_diagnostica=(
             "Para encontrar UN cable específico entre decenas sin etiquetar en un rack, la "
             "herramienta correcta es el tonificador (toner probe), no un simple probador de "
             "continuidad -- confundir estas herramientas hace perder tiempo real en campo."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 2.8 Networking"),

    # ── 3.0 Hardware — componentes físicos detallados ──
    dict(dominio="hardware", concepto="Tipos de pantalla: LCD (IPS/TN/VA) vs OLED vs Mini-LED",
         explicacion=(
             "TN es la más barata y rápida pero con peor ángulo de visión y color. IPS tiene "
             "mejor color/ángulo de visión pero es más lenta y cara. VA tiene mejor contraste "
             "que ambas. OLED no necesita retroiluminación (cada píxel emite su propia luz), "
             "logrando negros más profundos, pero es susceptible a 'quemado' de imagen "
             "estática prolongada (burn-in)."
         ),
         relevancia_diagnostica=(
             "Una marca fantasma persistente en una pantalla OLED que muestra contenido "
             "estático mucho tiempo (ej. un panel NOC con el mismo dashboard fijo) es burn-in, "
             "un desgaste real del panel, no una falla de configuración."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.1 Hardware"),
    dict(dominio="hardware", concepto="Tipos de conectores de fibra óptica: ST, SC, LC",
         explicacion=(
             "ST usa un mecanismo de giro/traba tipo bayoneta (más antiguo). SC usa un "
             "mecanismo de empuje-clic simple. LC es más pequeño (permite más densidad de "
             "puertos en el mismo espacio) y es el más común en instalaciones modernas de "
             "centro de datos. No son intercambiables sin un adaptador -- un cable con "
             "conector LC no entra físicamente en un puerto SC."
         ),
         relevancia_diagnostica=(
             "Al reemplazar un patch cord de fibra, confirmar el tipo de conector exacto (ST/"
             "SC/LC) del equipo antes de pedir el cable -- son físicamente distintos, no un "
             "detalle menor."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.2 Hardware"),
    dict(dominio="hardware", concepto="RAM: SODIMM vs DIMM, generaciones DDR, y ECC",
         explicacion=(
             "DIMM es el formato de escritorio/servidor; SODIMM es la versión compacta para "
             "laptops. Cada generación DDR (DDR4, DDR5, etc.) es físicamente incompatible con "
             "la anterior -- una ranura DDR4 no acepta un módulo DDR5 aunque ambos se vean "
             "similares. RAM ECC (error-correcting code) detecta y corrige errores de memoria "
             "menores automáticamente -- estándar en servidores críticos, no en equipos de "
             "escritorio comunes, y no es intercambiable con RAM no-ECC en la mayoría de "
             "placas."
         ),
         relevancia_diagnostica=(
             "Errores aleatorios/intermitentes de aplicaciones en un servidor sin RAM ECC son "
             "más difíciles de descartar como causa de memoria -- sin ECC, errores menores de "
             "memoria pueden pasar silenciosos en vez de corregirse solos."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.3 Hardware"),
    dict(dominio="hardware", concepto="RAID 0, 1, 5, 6 y 10: qué protege cada uno realmente",
         explicacion=(
             "RAID 0 reparte datos sin redundancia (más velocidad, cero protección -- la "
             "pérdida de UN disco pierde TODO). RAID 1 duplica en espejo. RAID 5 usa paridad "
             "distribuida, tolera 1 disco, pero la reconstrucción tras un fallo estresa los "
             "discos restantes. RAID 6 usa doble paridad, tolera 2 discos simultáneos -- más "
             "seguro que RAID 5 para arreglos grandes. RAID 10 combina espejo y striping "
             "(segmentación en bandas) -- mejor rendimiento Y tolerancia que RAID 5, a costa de "
             "usar el doble de capacidad total."
         ),
         relevancia_diagnostica=(
             "En un servidor con muchos discos (8+), RAID 6 es preferible a RAID 5 -- con "
             "arreglos grandes, la probabilidad de una SEGUNDA falla durante la reconstrucción "
             "de RAID 5 ya no es un caso extremo, es un riesgo real y documentado."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.4 Hardware"),
    dict(dominio="hardware", concepto="TPM y arranque seguro (Secure Boot)",
         explicacion=(
             "El Trusted Platform Module (TPM) es un chip dedicado que almacena claves "
             "criptográficas de forma aislada del sistema operativo -- necesario para cifrado "
             "de disco completo (ej. BitLocker) y Secure Boot, que verifica que el firmware/"
             "sistema operativo no haya sido alterado antes de arrancar. Sin TPM habilitado en "
             "BIOS/UEFI, algunas funciones de seguridad simplemente no están disponibles, no "
             "es un problema de configuración del sistema operativo."
         ),
         relevancia_diagnostica=(
             "Un equipo que no puede activar cifrado de disco completo pese a tener sistema "
             "operativo compatible -- verificar que TPM esté habilitado en BIOS/UEFI antes de "
             "sospechar de licencias o configuración de software."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.5 Hardware"),
    dict(dominio="hardware", concepto="Especificaciones de fuente de poder: voltaje, wattage y eficiencia",
         explicacion=(
             "Una fuente entrega distintos voltajes (3.3V, 5V, 12V) para distintos componentes "
             "simultáneamente -- el wattage nominal es el máximo TOTAL combinado, no por línea "
             "de voltaje individual. Una fuente 'redundante' permite que si una unidad falla, "
             "otra la reemplace sin apagar el equipo; una fuente 'modular' permite conectar "
             "solo los cables que se necesitan, reduciendo desorden y mejorando flujo de aire."
         ),
         relevancia_diagnostica=(
             "Reinicios aleatorios bajo carga alta (muchos discos/tarjetas agregadas después "
             "de la instalación original) pueden ser una fuente de poder que ya no alcanza el "
             "wattage real necesario -- recalcular la carga total, no asumir falla de "
             "componente individual."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.6 Hardware"),
    dict(dominio="impresoras", concepto="PCL vs PostScript: dos lenguajes de impresión distintos",
         explicacion=(
             "PCL (Printer Command Language) es más simple y rápido para documentos de texto "
             "estándar. PostScript maneja mejor gráficos complejos y es más consistente entre "
             "distintas impresoras -- un driver configurado con el lenguaje equivocado puede "
             "producir texto con errores de formato o símbolos incorrectos, sin que sea una "
             "falla de la impresora en sí."
         ),
         relevancia_diagnostica=(
             "Documentos con caracteres/símbolos corruptos o mal formateados desde UN "
             "programa específico, mientras otros imprimen bien -- revisar qué lenguaje de "
             "impresión (PCL/PostScript) espera ese programa vs. el configurado en el driver."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.7 Hardware"),
    dict(dominio="impresoras", concepto="Impresoras de impacto: todavía existen y fallan distinto",
         explicacion=(
             "Las impresoras de impacto (matriciales) usan una cinta entintada y agujas "
             "físicas -- todavía se usan para papel multiparte (copias sin papel carbón, "
             "común en algunos recibos/formularios legales). Sus fallas típicas son cinta "
             "gastada, cabezal de impresión desgastado y atascos de papel multiparte "
             "específicamente, no las mismas fallas que láser/inkjet/térmica."
         ),
         relevancia_diagnostica=(
             "Si un sitio todavía usa formularios multiparte con impresora de impacto, no "
             "asumir que sus fallas se resuelven con el mismo procedimiento que impresoras "
             "modernas -- es tecnología distinta con mantenimiento distinto (reemplazo de "
             "cinta, no de tóner/tinta)."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 3.8 Hardware"),

    # ── 4.0 Virtualización y nube — lo que faltaba ──
    dict(dominio="virtualizacion", concepto="Contenedores vs máquinas virtuales completas",
         explicacion=(
             "Una máquina virtual completa incluye su propio sistema operativo entero. Un "
             "contenedor comparte el kernel del sistema anfitrión y solo empaqueta la "
             "aplicación con sus dependencias -- mucho más liviano y rápido de iniciar, pero "
             "con menos aislamiento que una VM completa (un problema del kernel anfitrión "
             "afecta a todos los contenedores que corren sobre él)."
         ),
         relevancia_diagnostica=(
             "Un problema que afecta a TODOS los contenedores de un host a la vez, pero no a "
             "las máquinas virtuales completas en el mismo servidor físico, apunta al kernel/"
             "sistema anfitrión compartido, no a cada aplicación contenedorizada por separado."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 4.1 Virtualization and Cloud Computing"),
    dict(dominio="cloud", concepto="Elasticidad, multitenencia y utilización medida en la nube",
         explicacion=(
             "Elasticidad es la capacidad de escalar recursos automáticamente según demanda "
             "real (subir en horas pico, bajar después). Multitenencia significa que varios "
             "clientes distintos comparten la misma infraestructura física, aislados "
             "lógicamente entre sí. Utilización medida (metered) cobra por consumo real "
             "(ingreso/egreso de datos, cómputo usado), no una tarifa fija -- un pico de "
             "tráfico inesperado puede generar un costo inesperado sin que sea un error de "
             "facturación."
         ),
         relevancia_diagnostica=(
             "Un aumento inesperado en la factura de un servicio en la nube puede ser "
             "consumo real por un pico de tráfico legítimo (o un mal uso/ataque generando "
             "tráfico), no necesariamente un error de facturación del proveedor -- revisar "
             "métricas de uso real antes de disputar el cargo."
         ),
         fuente="CompTIA A+ Core 1 220-1201 — 4.2 Virtualization and Cloud Computing"),

    # ══════════════════════ NETWORK+ N10-009 — TEMARIO OFICIAL COMPLETO ══════════════════════
    # Trabajado con el documento oficial (objetivos v6.0, 2023) -- dominios: 1.0 Networking
    # Concepts (23%), 2.0 Network Implementation (20%), 3.0 Network Operations (19%),
    # 4.0 Network Security (14%), 5.0 Network Troubleshooting (24%).

    # ── 1.0 Conceptos de red ──
    dict(dominio="metodologia", concepto="El modelo OSI de 7 capas, formal y completo",
         explicacion=(
             "Física (cables, señales) → Enlace (MAC, switches) → Red (IP, routers) → "
             "Transporte (TCP/UDP, puertos) → Sesión (establece/mantiene conversaciones) → "
             "Presentación (formato/cifrado de datos) → Aplicación (lo que ve el usuario, "
             "HTTP/DNS/etc.). Cada capa depende de que la de abajo funcione -- un problema de "
             "capa 1 (cable) se manifiesta como fallas en TODAS las capas superiores, aunque "
             "el síntoma reportado sea 'la aplicación no carga' (capa 7)."
         ),
         relevancia_diagnostica=(
             "Cuando el síntoma es de capa alta (una app específica falla) pero TODO lo demás "
             "en ese equipo también falla, la causa real está más abajo en el modelo -- "
             "revisar de la capa física hacia arriba, no asumir que el problema vive donde se "
             "percibió."
         ),
         fuente="CompTIA Network+ N10-009 — 1.1 Networking Concepts"),
    dict(dominio="redes_ip", concepto="Dispositivos de red: IDS/IPS, balanceador de carga, proxy, NAS vs SAN",
         explicacion=(
             "Un IDS detecta y alerta; un IPS detecta y BLOQUEA automáticamente -- un IPS mal "
             "calibrado puede cortar tráfico legítimo por un falso positivo, un riesgo que un "
             "IDS no tiene. Un balanceador de carga reparte tráfico entre varios servidores "
             "para el mismo servicio. Un proxy intermedia conexiones (saliente: oculta "
             "clientes internos; entrante/reverso: oculta servidores reales). NAS comparte "
             "ARCHIVOS por red normal; SAN es una red dedicada solo para bloques de "
             "almacenamiento, separada del tráfico de datos común."
         ),
         relevancia_diagnostica=(
             "Tráfico legítimo bloqueado de forma inesperada en una red con IPS activo -- "
             "revisar reglas del IPS como sospechoso antes que firewall o el equipo destino, "
             "un IPS actúa automáticamente sin intervención humana en el momento."
         ),
         fuente="CompTIA Network+ N10-009 — 1.2 Networking Concepts"),
    dict(dominio="cloud", concepto="Conceptos de red en la nube: VPC, NAT gateway, y modelos de conectividad",
         explicacion=(
             "Una VPC (nube privada virtual) es una red aislada lógicamente dentro de la "
             "infraestructura de un proveedor de nube. Un NAT gateway en la nube cumple la "
             "misma función que un NAT tradicional pero como servicio administrado. 'Direct "
             "Connect' es una conexión dedicada y privada hacia el proveedor de nube, evitando "
             "internet público -- más cara pero más predecible en latencia/seguridad que una "
             "VPN sobre internet normal."
         ),
         relevancia_diagnostica=(
             "Latencia inconsistente hacia un servicio en la nube conectado por VPN sobre "
             "internet público (no Direct Connect) es esperable en cierto grado -- no siempre "
             "es un problema a resolver, puede ser la naturaleza del tipo de conexión elegida."
         ),
         fuente="CompTIA Network+ N10-009 — 1.3 Networking Concepts"),
    dict(dominio="redes_ip", concepto="Tipos de tráfico IP: unicast, multicast, anycast, broadcast",
         explicacion=(
             "Unicast va de un origen a un destino específico (la mayoría del tráfico normal). "
             "Broadcast va a TODOS los equipos de la red local. Multicast va a un GRUPO "
             "específico de receptores suscritos (ej. streaming de video interno). Anycast "
             "envía a 'el más cercano' de varios destinos posibles con la misma dirección "
             "(usado por DNS raíz y algunos CDN)."
         ),
         relevancia_diagnostica=(
             "Tráfico multicast que no llega a algunos receptores mientras unicast funciona "
             "perfecto entre los mismos equipos -- el problema suele ser configuración de "
             "IGMP/multicast en el switch, no la red en general."
         ),
         fuente="CompTIA Network+ N10-009 — 1.4 Networking Concepts"),
    dict(dominio="cableado", concepto="Transceptores SFP/QSFP y cable de cobre de conexión directa (DAC)",
         explicacion=(
             "SFP/QSFP son módulos intercambiables que permiten cambiar el tipo de conexión "
             "(cobre o fibra, y a qué distancia) sin cambiar el switch completo -- el switch "
             "define la velocidad máxima, el transceptor define el medio físico. DAC es un "
             "cable de cobre con transceptores SFP integrados en ambas puntas, más barato que "
             "fibra para distancias cortas dentro del mismo rack."
         ),
         relevancia_diagnostica=(
             "Un puerto que no sube tras cambiar de fibra a DAC (o viceversa) puede ser "
             "incompatibilidad del transceptor con la velocidad configurada en el puerto del "
             "switch, no un cable defectuoso."
         ),
         fuente="CompTIA Network+ N10-009 — 1.5 Networking Concepts"),
    dict(dominio="switching", concepto="Topologías de red: malla, estrella, spine-leaf, y modelo jerárquico de 3 capas",
         explicacion=(
             "Estrella/hub-and-spoke: todo pasa por un punto central (simple, pero ese punto "
             "es un solo punto de falla). Malla: cada nodo conectado a varios otros "
             "(redundante, complejo de gestionar). Spine-leaf: arquitectura moderna de centro "
             "de datos donde cada switch 'leaf' se conecta a TODOS los 'spine', nunca "
             "leaf-a-leaf directo -- predecible y escalable. El modelo jerárquico clásico de 3 "
             "capas (núcleo/distribución/acceso) organiza el tráfico en capas de "
             "responsabilidad distinta; 'core colapsado' combina núcleo y distribución en "
             "redes más pequeñas."
         ),
         relevancia_diagnostica=(
             "En una arquitectura spine-leaf, tráfico 'este-oeste' (entre servidores del mismo "
             "centro de datos) NO debería pasar por el mismo camino que tráfico 'norte-sur' "
             "(hacia/desde fuera) -- si un problema de rendimiento afecta solo un tipo de "
             "tráfico, ayuda a ubicar en qué parte de la topología está la causa."
         ),
         fuente="CompTIA Network+ N10-009 — 1.6 Networking Concepts"),
    dict(dominio="redes_ip", concepto="CIDR y VLSM: por qué las máscaras de subred no siempre son iguales",
         explicacion=(
             "CIDR permite notación flexible (ej. /24, /27) en vez de solo las clases A/B/C "
             "tradicionales. VLSM permite que DISTINTAS subredes dentro de la misma red usen "
             "máscaras de tamaño DISTINTO según cuántos hosts necesita cada una -- una subred "
             "de 4 servidores no necesita el mismo tamaño que una de 200 estaciones, y "
             "desperdiciar direcciones IP asignando el mismo tamaño a todas es un error de "
             "diseño común."
         ),
         relevancia_diagnostica=(
             "Antes de asumir que 'se acabaron las IPs disponibles' en una subred, verificar "
             "si el diseño usa VLSM correctamente -- a veces el problema es una subred "
             "sobredimensionada en otro lugar, no falta real de espacio de direcciones."
         ),
         fuente="CompTIA Network+ N10-009 — 1.7 Networking Concepts"),
    dict(dominio="seguridad_arquitectura", concepto="SASE/SSE: seguridad de red entregada desde la nube",
         explicacion=(
             "SASE combina funciones de red (SD-WAN) y seguridad (firewall, filtrado web, "
             "Zero Trust) en un solo servicio entregado desde la nube, en vez de equipos "
             "físicos en cada sitio. SSE (Security Service Edge) es el subconjunto de SASE "
             "que entrega SOLO la parte de seguridad (SWG, CASB, ZTNA, firewall como servicio), "
             "SIN el componente de red/SD-WAN -- tiene sentido cuando la organización ya cuenta "
             "con su propia WAN y solo necesita centralizar la seguridad en la nube, sin "
             "reemplazar la conectividad existente. Ambos modelos están pensados para "
             "organizaciones con muchos sitios pequeños o trabajadores remotos, donde no es "
             "práctico tener un firewall físico completo en cada ubicación."
         ),
         relevancia_diagnostica=(
             "Para un negocio con múltiples sitios pequeños (ej. una cadena hotelera con "
             "varios hoteles), evaluar SASE/SSE como alternativa a replicar hardware de "
             "seguridad completo en cada sitio individual -- puede simplificar gestión "
             "centralizada real."
         ),
         fuente="CompTIA Network+ N10-009 — 1.8 Networking Concepts"),

    # ── 2.0 Implementación de red ──
    dict(dominio="wan", concepto="Selección de ruta: distancia administrativa, prefijo y métrica",
         explicacion=(
             "El criterio que manda primero, sin importar el protocolo de origen, es el "
             "prefijo más específico (más largo, longest prefix match) -- el router siempre "
             "reenvía usando la ruta más específica disponible para el destino, aunque "
             "provenga de un protocolo con peor distancia administrativa. La distancia "
             "administrativa solo entra en juego cuando dos o más protocolos aprenden "
             "EXACTAMENTE el mismo prefijo/máscara -- ahí decide cuál protocolo 'confiar' más "
             "(una ruta estática manualmente configurada suele ganar sobre una aprendida "
             "dinámicamente). Y solo si compiten rutas del MISMO protocolo hacia ese mismo "
             "prefijo exacto, gana la de menor métrica (costo)."
         ),
         relevancia_diagnostica=(
             "Tráfico tomando una ruta 'inesperada' pese a que la ruta 'correcta' esté "
             "configurada -- revisar primero si existe una ruta más específica (prefijo más "
             "largo) compitiendo por ese destino; el prefijo más largo gana siempre, sin "
             "importar qué protocolo lo anunció ni su distancia administrativa."
         ),
         fuente="CompTIA Network+ N10-009 — 2.1 Network Implementation"),
    dict(dominio="wan", concepto="FHRP y IP virtual: redundancia de gateway sin que el cliente lo note",
         explicacion=(
             "Un First Hop Redundancy Protocol (ej. HSRP, VRRP) permite que dos routers "
             "compartan una IP virtual como gateway -- si el router activo falla, el otro "
             "toma la IP virtual automáticamente, sin que los equipos clientes necesiten "
             "cambiar su configuración de gateway."
         ),
         relevancia_diagnostica=(
             "Una breve interrupción de red (segundos) coincidiendo con la caída de un router "
             "de gateway, seguida de recuperación automática sin intervención, es el "
             "comportamiento esperado de FHRP funcionando correctamente -- no es una falla sin "
             "resolver."
         ),
         fuente="CompTIA Network+ N10-009 — 2.1 Network Implementation"),
    dict(dominio="switching", concepto="VLAN de voz y SVI: por qué el teléfono IP y la PC del mismo escritorio están en redes distintas",
         explicacion=(
             "Es común que un teléfono IP y la PC conectada a través de él compartan el mismo "
             "cable físico pero vivan en VLANs distintas (voz vs datos) -- el teléfono actúa "
             "como mini-switch, etiquetando su propio tráfico de voz por separado. Una SVI "
             "(interfaz virtual de switch) le da a una VLAN una dirección IP propia para "
             "enrutamiento entre VLANs sin necesitar un router físico aparte."
         ),
         relevancia_diagnostica=(
             "Un teléfono IP sin tono/registro mientras la PC del mismo puerto tiene red "
             "normal -- revisar la configuración de VLAN de voz en ese puerto específicamente, "
             "no asumir que el cable o el switch completo están mal."
         ),
         fuente="CompTIA Network+ N10-009 — 2.2 Network Implementation"),
    dict(dominio="wifi", concepto="SSID, BSSID y ESSID: nombres visibles vs identificadores reales de hardware",
         explicacion=(
             "El SSID es el nombre de red visible para los usuarios. El BSSID es la dirección "
             "MAC real del radio de UN access point específico. El ESSID identifica una red "
             "WiFi compuesta por VARIOS APs con el mismo SSID (roaming) -- dos APs pueden "
             "compartir el mismo SSID/ESSID pero cada uno tiene su propio BSSID único, útil "
             "para diagnosticar a cuál AP específico está conectado un cliente con problemas."
         ),
         relevancia_diagnostica=(
             "Un problema de WiFi reportado 'en la red X' con múltiples APs bajo el mismo "
             "nombre -- identificar el BSSID específico al que estaba conectado el cliente "
             "afectado, no tratar todos los APs de esa red como un solo equipo."
         ),
         fuente="CompTIA Network+ N10-009 — 2.3 Network Implementation"),
    dict(dominio="wifi", concepto="AP autónomo vs AP ligero (controlado)",
         explicacion=(
             "Un AP autónomo se configura y gestiona individualmente, cada uno por separado. "
             "Un AP ligero depende de un controlador central que le entrega su configuración "
             "-- si el controlador falla, un AP ligero puede seguir sirviendo clientes ya "
             "conectados con su última configuración, pero no acepta cambios ni, en algunos "
             "modelos, nuevas conexiones hasta que el controlador vuelva."
         ),
         relevancia_diagnostica=(
             "Varios APs ligeros dejando de aceptar nuevas conexiones a la vez, mientras los "
             "clientes ya conectados siguen bien, apunta al controlador central, no a cada AP "
             "individual."
         ),
         fuente="CompTIA Network+ N10-009 — 2.3 Network Implementation"),
    dict(dominio="hardware", concepto="IDF y MDF: la jerarquía física del cableado de un edificio",
         explicacion=(
             "El MDF (repartidor principal) es el punto central donde entra el servicio "
             "externo y se distribuye hacia los IDF (repartidores intermedios) de cada piso/"
             "ala del edificio -- cada IDF sirve una zona limitada, reduciendo la longitud "
             "máxima de cable de cobre necesaria (el límite de 100m aplica desde el IDF, no "
             "desde el MDF central)."
         ),
         relevancia_diagnostica=(
             "Múltiples fallas de red concentradas en una sola zona/piso del edificio, sin "
             "relación con el resto, apunta al IDF de esa zona específica, no al MDF central "
             "-- diagnosticar por jerarquía física, no por el edificio completo."
         ),
         fuente="CompTIA Network+ N10-009 — 2.4 Network Implementation"),

    # ── 3.0 Operaciones de red ──
    dict(dominio="gestion_documentacion", concepto="Gestión del ciclo de vida: fin de vida (EOL) vs fin de soporte (EOS)",
         explicacion=(
             "Fin de vida (EOL) significa que el fabricante ya no VENDE el producto. Fin de "
             "soporte (EOS) significa que el fabricante ya no da soporte NI actualizaciones de "
             "seguridad -- un equipo puede estar en EOL pero aún en soporte (todavía recibe "
             "parches), o ya en EOS (ya no recibe nada), que es el punto donde el riesgo real "
             "de seguridad se dispara."
         ),
         relevancia_diagnostica=(
             "Un equipo 'descontinuado' (EOL) no es automáticamente un riesgo de seguridad -- "
             "verificar específicamente si ya alcanzó EOS (sin soporte ni parches) antes de "
             "priorizar su reemplazo por ese motivo."
         ),
         fuente="CompTIA Network+ N10-009 — 3.1 Network Operations"),
    dict(dominio="gestion_documentacion", concepto="Gestión de cambios y configuración: por qué existen procesos formales",
         explicacion=(
             "Gestión de cambios rastrea QUÉ se va a cambiar, por qué, y su plan de reversión "
             "antes de aplicarlo -- reduce cambios no autorizados o mal coordinados. Gestión "
             "de configuración mantiene una configuración 'base/dorada' de referencia y "
             "respaldos de configuración -- permite restaurar rápido si un cambio sale mal, "
             "sin tener que reconstruir la configuración de memoria."
         ),
         relevancia_diagnostica=(
             "Ante una falla tras un cambio reciente sin plan de reversión documentado, el "
             "tiempo de resolución se alarga significativamente -- tener un respaldo de "
             "configuración previo al cambio es lo que permite revertir en minutos, no horas."
         ),
         fuente="CompTIA Network+ N10-009 — 3.1 Network Operations"),
    dict(dominio="monitoreo", concepto="SNMP traps vs consultas (polling), y qué es un MIB",
         explicacion=(
             "El monitoreo por consulta (polling) pregunta activamente el estado a intervalos "
             "regulares -- puede perderse un evento breve entre consultas. Un 'trap' es el "
             "equipo AVISANDO proactivamente ante un evento, sin esperar a que le pregunten -- "
             "más inmediato pero depende de que el equipo esté configurado para enviarlo. El "
             "MIB es la base de datos estructurada que define qué información específica se "
             "puede consultar/recibir de un equipo por SNMP."
         ),
         relevancia_diagnostica=(
             "Un evento breve de caída que el sistema de monitoreo por polling 'no vio' pero "
             "sí quedó registrado en el log del propio equipo -- evaluar si conviene "
             "complementar con traps SNMP para eventos que duran menos que el intervalo de "
             "consulta."
         ),
         fuente="CompTIA Network+ N10-009 — 3.2 Network Operations"),
    dict(dominio="dns_dhcp", concepto="Zonas DNS: primaria, secundaria, y directa vs inversa",
         explicacion=(
             "Una zona primaria es la copia editable/autoritativa de los registros de un "
             "dominio. Una secundaria es una copia de solo lectura sincronizada desde la "
             "primaria, para redundancia. Una zona 'directa' resuelve nombre→IP; una 'inversa' "
             "resuelve IP→nombre (registro PTR) -- muchos sistemas de correo rechazan mensajes "
             "de servidores sin PTR configurado correctamente, aunque el DNS directo esté "
             "perfecto."
         ),
         relevancia_diagnostica=(
             "Correo saliente rechazado o marcado como spam por destinatarios externos, con el "
             "DNS directo funcionando bien -- verificar que exista un registro PTR (DNS "
             "inverso) correcto para la IP del servidor de correo."
         ),
         fuente="CompTIA Network+ N10-009 — 3.4 Network Operations"),
    dict(dominio="dns_dhcp", concepto="DoH y DoT: cifrar las consultas DNS mismas",
         explicacion=(
             "DNS tradicional viaja sin cifrar -- cualquiera en la red puede ver qué dominios "
             "consulta un equipo. DNS over HTTPS (DoH) y DNS over TLS (DoT) cifran esas "
             "consultas, pero como consecuencia, un firewall/filtro de contenido tradicional "
             "que dependía de VER las consultas DNS para bloquear sitios deja de funcionar "
             "para el tráfico que use DoH/DoT."
         ),
         relevancia_diagnostica=(
             "Un filtro de contenido/parental que 'dejó de funcionar' para ciertos "
             "dispositivos o navegadores, sin ningún cambio en la configuración del filtro, "
             "puede deberse a que ese dispositivo empezó a usar DoH/DoT, evadiendo la "
             "visibilidad del filtro tradicional."
         ),
         fuente="CompTIA Network+ N10-009 — 3.4 Network Operations"),
    dict(dominio="acceso_remoto", concepto="VPN sitio a sitio vs cliente a sitio, y túnel dividido vs completo",
         explicacion=(
             "Sitio a sitio conecta dos redes completas entre sí de forma permanente (ej. dos "
             "oficinas). Cliente a sitio conecta un dispositivo individual remoto a la red "
             "central bajo demanda. Túnel completo (full tunnel) envía TODO el tráfico del "
             "cliente por la VPN, incluyendo su navegación normal de internet. Túnel dividido "
             "(split tunnel) solo envía por la VPN el tráfico dirigido a la red corporativa, "
             "el resto sale directo a internet -- más rápido pero con menos visibilidad/"
             "control corporativo sobre ese tráfico."
         ),
         relevancia_diagnostica=(
             "Navegación general de internet lenta mientras se está conectado a una VPN de "
             "túnel completo es un síntoma esperado (todo el tráfico da una vuelta extra por "
             "la red corporativa) -- no es necesariamente una falla de la VPN en sí."
         ),
         fuente="CompTIA Network+ N10-009 — 3.5 Network Operations"),
    dict(dominio="acceso_remoto", concepto="Jump box y gestión dentro de banda vs fuera de banda",
         explicacion=(
             "Un jump box/host es un punto de acceso intermedio obligatorio para llegar a "
             "sistemas críticos -- reduce la superficie de ataque a un solo punto vigilado, en "
             "vez de exponer cada sistema directamente. Gestión 'dentro de banda' usa la misma "
             "red de producción para administrar equipos; 'fuera de banda' usa una red o canal "
             "completamente separado (ej. un puerto de consola dedicado), permitiendo "
             "administrar un equipo incluso si su red de producción está caída."
         ),
         relevancia_diagnostica=(
             "Sin gestión fuera de banda, un problema de red grave puede dejar los equipos "
             "administrativamente inalcanzables justo cuando más se necesita entrar a "
             "diagnosticarlos -- es una inversión que se nota específicamente en el peor "
             "momento."
         ),
         fuente="CompTIA Network+ N10-009 — 3.5 Network Operations"),
    dict(dominio="servidor_recuperacion_desastres", concepto="MTTR y MTBF: qué tan rápido se repara vs qué tan seguido falla",
         explicacion=(
             "MTTR (tiempo medio de reparación) mide cuánto se tarda en recuperar el servicio "
             "tras una falla. MTBF (tiempo medio entre fallas) mide qué tan seguido ocurren "
             "fallas nuevas. Un sistema con MTBF alto (falla poco) pero MTTR alto (tarda mucho "
             "en repararse cuando sí falla) puede tener MÁS impacto acumulado de downtime que "
             "uno que falla más seguido pero se repara casi al instante."
         ),
         relevancia_diagnostica=(
             "Al evaluar la confiabilidad real de un sistema, considerar ambas métricas juntas "
             "-- un MTBF excelente no compensa un MTTR terrible si cuando falla, tarda días en "
             "repararse."
         ),
         fuente="CompTIA Network+ N10-009 — 3.3 Network Operations"),
    dict(dominio="servidor_recuperacion_desastres", concepto="Alta disponibilidad activo-activo vs activo-pasivo",
         explicacion=(
             "Activo-activo: ambos/todos los nodos procesan tráfico real simultáneamente, "
             "repartiendo la carga -- mejor uso de recursos, pero más complejo de sincronizar. "
             "Activo-pasivo: un nodo procesa todo mientras el otro espera sin hacer nada hasta "
             "que el activo falla -- más simple, pero el nodo pasivo es 'capacidad "
             "desperdiciada' la mayor parte del tiempo."
         ),
         relevancia_diagnostica=(
             "En un esquema activo-pasivo, verificar periódicamente que el nodo pasivo "
             "REALMENTE tomaría el control si se necesitara -- un nodo pasivo que nunca se "
             "prueba puede fallar en el momento exacto que se necesita, sin ninguna alerta "
             "previa."
         ),
         fuente="CompTIA Network+ N10-009 — 3.3 Network Operations"),

    # ── 4.0 Seguridad de red ──
    dict(dominio="seguridad_arquitectura", concepto="IAM y métodos de autenticación centralizada: RADIUS, LDAP, SAML, TACACS+",
         explicacion=(
             "RADIUS centraliza autenticación para acceso de red (WiFi empresarial, VPN). "
             "LDAP consulta un directorio de usuarios (ej. Active Directory). SAML permite "
             "inicio de sesión único entre organizaciones/servicios distintos (federación). "
             "TACACS+ es similar a RADIUS pero separa autenticación, autorización y auditoría "
             "en pasos independientes -- común para administrar equipos de red (routers/"
             "switches), no para acceso de usuarios finales."
         ),
         relevancia_diagnostica=(
             "Fallas de autenticación en el WiFi empresarial mientras el login al dominio "
             "Windows funciona bien -- son sistemas distintos (RADIUS vs LDAP/Kerberos) que "
             "pueden compartir la misma base de usuarios pero fallar independientemente."
         ),
         fuente="CompTIA Network+ N10-009 — 4.1 Network Security"),
    dict(dominio="seguridad_arquitectura", concepto="Honeypot/honeynet: tecnología de engaño como detección temprana",
         explicacion=(
             "Un honeypot es un sistema señuelo, deliberadamente vulnerable o atractivo, "
             "diseñado para atraer atacantes -- cualquier actividad ahí es, por definición, "
             "sospechosa (ningún usuario legítimo debería tocarlo nunca). Un honeynet es una "
             "red completa de señuelos. Sirven como alerta temprana de que hay un atacante "
             "activo en la red, antes de que llegue a sistemas reales."
         ),
         relevancia_diagnostica=(
             "Cualquier tráfico dirigido a un honeypot/honeynet debe tratarse como señal de "
             "compromiso real dentro de la red -- no hay 'falso positivo' posible en un "
             "sistema que nadie legítimo debería usar."
         ),
         fuente="CompTIA Network+ N10-009 — 4.1 Network Security"),
    dict(dominio="ataques_red", concepto="MAC flooding vs ARP spoofing: dos ataques de capa 2 distintos",
         explicacion=(
             "MAC flooding satura la tabla de direcciones MAC de un switch con miles de "
             "direcciones falsas -- cuando se llena, el switch puede empezar a inundar "
             "tráfico por todos los puertos (comportándose como un hub), permitiendo que un "
             "atacante vea tráfico que no debería. ARP spoofing/poisoning hace que otros "
             "equipos crean que el atacante ES la IP de otro dispositivo (ej. el gateway), "
             "redirigiendo tráfico sin necesidad de saturar nada."
         ),
         relevancia_diagnostica=(
             "Tráfico visible que no debería estar disponible en un puerto específico, sin "
             "señales de ARP spoofing (tablas ARP se ven normales), sugiere MAC flooding -- "
             "revisar el conteo de direcciones MAC aprendidas en ese switch."
         ),
         fuente="CompTIA Network+ N10-009 — 4.2 Network Security"),
    dict(dominio="ataques_red", concepto="Evil twin y AP/DHCP no autorizados (rogue)",
         explicacion=(
             "Un 'evil twin' es un access point falso que copia el nombre (SSID) de una red "
             "legítima para engañar a los dispositivos a conectarse a él en vez del real -- "
             "una vez conectado, el atacante puede interceptar todo el tráfico. Un DHCP/AP "
             "'rogue' no necesariamente es malicioso a propósito -- a veces es un router "
             "doméstico conectado por error, pero el efecto en la red es similarmente "
             "disruptivo."
         ),
         relevancia_diagnostica=(
             "Dispositivos conectándose intermitentemente a una red WiFi con el nombre "
             "correcto pero comportamiento distinto (señal en un lugar inesperado, sin "
             "internet real) -- sospechar de un evil twin o AP no autorizado, no de un "
             "problema de configuración del AP legítimo."
         ),
         fuente="CompTIA Network+ N10-009 — 4.2 Network Security"),
    dict(dominio="ataques_red", concepto="Ingeniería social: phishing, dumpster diving, shoulder surfing, tailgating",
         explicacion=(
             "Phishing engaña por mensaje/correo para obtener credenciales o acceso. Dumpster "
             "diving busca información sensible en la basura física (documentos impresos no "
             "destruidos). Shoulder surfing observa directamente por encima del hombro "
             "mientras alguien escribe una contraseña. Tailgating sigue físicamente a alguien "
             "autorizado a través de una puerta con control de acceso, sin usar credenciales "
             "propias -- todos son ataques que NINGÚN control técnico de red detiene, "
             "requieren procedimientos humanos."
         ),
         relevancia_diagnostica=(
             "Un incidente de acceso no autorizado sin ningún rastro técnico de intrusión de "
             "red (nada en logs de firewall/IDS) es candidato fuerte a ingeniería social o "
             "tailgating físico -- el control de acceso técnico no es la capa a revisar en ese "
             "caso."
         ),
         fuente="CompTIA Network+ N10-009 — 4.2 Network Security"),
    dict(dominio="seguridad_arquitectura", concepto="Endurecimiento de dispositivos: puertos/servicios innecesarios y contraseñas por defecto",
         explicacion=(
             "El endurecimiento básico de cualquier equipo de red empieza por desactivar "
             "servicios y puertos que no se usan activamente, y cambiar TODAS las contraseñas "
             "de fábrica -- estas dos acciones simples cierran la mayoría de los vectores de "
             "ataque más comunes y documentados, antes de considerar controles más avanzados."
         ),
         relevancia_diagnostica=(
             "Un hallazgo de auditoría de 'contraseña por defecto sin cambiar' en cualquier "
             "equipo de red (switch, cámara, router) debe tratarse como crítico inmediato, "
             "no como un detalle menor de higiene -- es la causa más común y más simple de "
             "explotar en incidentes reales documentados."
         ),
         fuente="CompTIA Network+ N10-009 — 4.3 Network Security"),
    dict(dominio="seguridad_arquitectura", concepto="802.1X y control de acceso a la red (NAC)",
         explicacion=(
             "802.1X exige autenticación ANTES de que un dispositivo pueda usar un puerto de "
             "red o WiFi, incluso antes de recibir una IP -- a diferencia del filtrado por MAC "
             "(fácil de falsificar), 802.1X verifica identidad real contra un servidor de "
             "autenticación (típicamente RADIUS) en cada conexión."
         ),
         relevancia_diagnostica=(
             "Un dispositivo nuevo que no logra conectarse a una red con 802.1X activo, pese a "
             "tener las credenciales de WiFi correctas, puede necesitar un certificado o "
             "configuración de autenticación específica que el filtrado simple por contraseña "
             "no requeriría -- es una capa adicional, no la misma autenticación de siempre."
         ),
         fuente="CompTIA Network+ N10-009 — 4.3 Network Security"),

    # ── 5.0 Troubleshooting de red — metodología formal completa ──
    dict(dominio="metodologia", concepto="Los 7 pasos de troubleshooting (estándar unificado de Shomer)",
         explicacion=(
             "1) Identificar el problema: recopilar información, preguntar a los usuarios, "
             "identificar síntomas, determinar qué cambió, intentar reproducir el problema. "
             "2) Teoría de causa probable: cuestionar lo obvio primero, elegir un enfoque "
             "(de arriba hacia abajo del modelo OSI, de abajo hacia arriba, o dividir y "
             "vencer). 3) Probar la teoría. 4) Plan de acción considerando efectos "
             "secundarios. 5) Implementar o escalar. 6) Verificar funcionalidad completa "
             "(no solo que 'parece resuelto'). 7) Documentar todo el proceso, no solo el "
             "resultado final. Shomer estandariza en esta versión de 7 pasos (la de "
             "CompTIA Network+ N10-009) en vez de la versión genérica de A+ que combina los "
             "pasos 4 y 5 en uno solo -- separar 'planear' de 'implementar o escalar' importa "
             "para un sistema que recomienda una acción pero no la ejecuta directamente."
         ),
         relevancia_diagnostica=(
             "El paso 'determinar qué cambió' antes de teorizar es el más saltado en la "
             "práctica y el más valioso -- la mayoría de fallas nuevas están relacionadas con "
             "un cambio reciente (configuración, actualización, equipo nuevo), preguntar esto "
             "primero ahorra mucho tiempo de diagnóstico especulativo."
         ),
         fuente="CompTIA Network+ N10-009 — 5.1 Network Troubleshooting"),
    dict(dominio="switching", concepto="Contadores de interfaz que indican problemas específicos: runts, giants, drops",
         explicacion=(
             "'Runts' son tramas más pequeñas de lo permitido (usualmente por colisión a "
             "medio enviar). 'Giants' son tramas más grandes de lo esperado (posible "
             "configuración de MTU/jumbo frame inconsistente). 'Drops' son paquetes "
             "descartados por saturación del buffer del puerto -- cada contador apunta a una "
             "causa distinta, no son intercambiables como 'errores genéricos de puerto'."
         ),
         relevancia_diagnostica=(
             "Contador de 'giants' creciendo en un puerto específico, mientras el resto de la "
             "red no reporta problemas, sugiere revisar configuración de MTU/jumbo frames de "
             "ESE segmento específicamente, no un problema general de la red."
         ),
         fuente="CompTIA Network+ N10-009 — 5.2 Network Troubleshooting"),
    dict(dominio="switching", concepto="Estados de puerto: error-disabled, administrativamente apagado, suspendido",
         explicacion=(
             "'Administrativamente apagado' significa que un humano lo desactivó a propósito "
             "(no es una falla). 'Error-disabled' es el switch apagándolo automáticamente por "
             "una condición de seguridad/error detectada (BPDU guard, port security, etc.). "
             "'Suspendido' suele referirse a un puerto en un grupo de agregación (LACP) que "
             "está arriba físicamente pero no participa activamente del grupo por alguna "
             "discordancia de configuración."
         ),
         relevancia_diagnostica=(
             "Antes de reactivar un puerto 'caído', diferenciar estos tres estados en el "
             "propio switch -- reactivar un puerto administrativamente apagado a propósito "
             "por otra persona puede reabrir algo que se cerró deliberadamente por una razón "
             "válida."
         ),
         fuente="CompTIA Network+ N10-009 — 5.2 Network Troubleshooting"),
    dict(dominio="switching", concepto="Problemas de STP: selección de root bridge y roles de puerto",
         explicacion=(
             "Si el switch equivocado gana la elección de root bridge (ej. un switch viejo y "
             "lento en el borde de la red, en vez del switch central rápido), TODO el tráfico "
             "puede terminar tomando rutas subóptimas más largas de lo necesario -- un "
             "problema de rendimiento generalizado que no es una falla de ningún equipo "
             "individual, es una elección de topología STP incorrecta."
         ),
         relevancia_diagnostica=(
             "Lentitud de red generalizada sin ningún equipo individual reportando fallas, en "
             "una red con múltiples switches -- verificar cuál switch es el root bridge de STP "
             "actualmente, puede no ser el que debería."
         ),
         fuente="CompTIA Network+ N10-009 — 5.3 Network Troubleshooting"),
    dict(dominio="dns_dhcp", concepto="Agotamiento del pool DHCP y su síntoma característico",
         explicacion=(
             "Cuando un ámbito DHCP se queda sin direcciones disponibles para asignar, los "
             "nuevos dispositivos que se conectan reciben una IP APIPA (169.254.x.x) "
             "autogenerada en vez de una IP real de la red -- el dispositivo 'tiene IP' pero "
             "no puede comunicarse con nada real de la red."
         ),
         relevancia_diagnostica=(
             "Un dispositivo nuevo con IP en el rango 169.254.x.x, sin acceso a nada de la "
             "red, es la firma clásica de agotamiento del pool DHCP (o de que el servidor "
             "DHCP no respondió a tiempo) -- no es un problema del dispositivo en sí."
         ),
         fuente="CompTIA Network+ N10-009 — 5.3 Network Troubleshooting"),
    dict(dominio="redes_ip", concepto="Direcciones IP duplicadas: síntoma intermitente y confuso",
         explicacion=(
             "Cuando dos equipos tienen la misma IP asignada manualmente por error, el "
             "comportamiento es intermitente y confuso -- a veces uno responde, a veces el "
             "otro, dependiendo de cuál actualizó su entrada ARP más recientemente en cada "
             "equipo de la red. Los sistemas operativos suelen alertar sobre esto, pero la "
             "alerta puede pasar desapercibida si nadie está mirando esa pantalla en ese "
             "momento."
         ),
         relevancia_diagnostica=(
             "Un equipo con conectividad 'aleatoria' (a veces funciona, a veces no, sin patrón "
             "claro) en una red con IPs estáticas configuradas manualmente, sospechar de "
             "conflicto de IP duplicada antes que de una falla de hardware."
         ),
         fuente="CompTIA Network+ N10-009 — 5.3 Network Troubleshooting"),
    dict(dominio="wifi", concepto="Desasociación de clientes y mala configuración de roaming",
         explicacion=(
             "Desasociación de clientes ocurre cuando un dispositivo pierde su conexión WiFi "
             "abruptamente (no por decisión del usuario) -- puede ser interferencia, señal "
             "débil, o el AP forzando la desconexión por umbrales mal configurados de RSSI "
             "(fuerza de señal mínima). Un roaming mal configurado hace que el dispositivo "
             "tarde demasiado en reconectarse al AP más cercano tras moverse, o nunca lo haga "
             "hasta perder la señal por completo del AP anterior."
         ),
         relevancia_diagnostica=(
             "Desconexiones frecuentes de WiFi mientras el usuario camina por el edificio, con "
             "buena señal general disponible en todas las zonas, apunta a mala configuración "
             "de roaming/umbral de desasociación, no a falta de cobertura real."
         ),
         fuente="CompTIA Network+ N10-009 — 5.4 Network Troubleshooting"),
    dict(dominio="metodologia", concepto="Herramientas de línea de comandos esenciales y para qué sirve cada una",
         explicacion=(
             "ping prueba conectividad básica. traceroute/tracert muestra la ruta salto por "
             "salto (ayuda a ubicar EN QUÉ PUNTO del camino falla algo). nslookup/dig "
             "consultan DNS directamente. tcpdump captura tráfico real para análisis "
             "profundo. netstat muestra conexiones activas del equipo local. arp muestra la "
             "tabla de direcciones MAC conocidas localmente. Cada herramienta responde una "
             "pregunta distinta -- usar ping cuando la pregunta real es 'dónde en la ruta se "
             "pierde' es perder tiempo, ahí corresponde traceroute."
         ),
         relevancia_diagnostica=(
             "Antes de escalar un problema de conectividad como 'la red está mal', correr "
             "traceroute para identificar el salto exacto donde empieza a fallar -- reduce "
             "drásticamente el tiempo de diagnóstico comparado con solo probar ping repetidas "
             "veces."
         ),
         fuente="CompTIA Network+ N10-009 — 5.5 Network Troubleshooting"),

    # ══════ A+ CORE 2 220-1202 — 1.0 SISTEMAS OPERATIVOS (28%) ══════
    dict(dominio="sistemas_operativos", concepto="Sistemas de archivos y sus diferencias prácticas",
         explicacion=(
             "NTFS (Windows) soporta permisos granulares, cifrado (EFS) y archivos grandes -- "
             "es el estándar en discos internos Windows. exFAT no tiene permisos ni journaling "
             "pero es compatible entre Windows/macOS/Linux, ideal para USBs compartidos entre "
             "sistemas distintos. FAT32 es aún más compatible pero limitado a archivos de 4GB "
             "máximo. ext4 es el estándar en Linux (journaling, sin límite práctico de tamaño). "
             "APFS es el de macOS moderno (snapshots, cifrado nativo)."
         ),
         relevancia_diagnostica=(
             "Un archivo de más de 4GB que 'no cabe' o falla al copiarse a un USB, sospechar "
             "de que el USB está formateado en FAT32 -- reformatear a exFAT resuelve sin "
             "perder compatibilidad multiplataforma."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 1.1 Operating Systems"),
    dict(dominio="sistemas_operativos", concepto="Ediciones de Windows y qué función depende de cuál se tenga",
         explicacion=(
             "Windows Home NO incluye BitLocker (con su panel de control, gestión granular y "
             "'BitLocker to go' para USBs), Group Policy Editor ni la capacidad de unirse a un "
             "dominio -- estas tres cosas son exclusivas de Pro/Enterprise/Education. Ojo con un "
             "matiz real: Windows Home SÍ puede tener 'Device Encryption' en equipos modernos "
             "compatibles (TPM 2.0 + Modern Standby) -- es una versión simplificada que usa la "
             "misma tecnología de cifrado por debajo, pero se activa automáticamente al iniciar "
             "sesión con cuenta Microsoft, resguarda la clave de recuperación en esa cuenta, y "
             "no permite configuración granular como BitLocker completo. Pro for Workstations "
             "agrega soporte para más RAM/CPUs y ReFS, pensado para estaciones de trabajo de "
             "alto rendimiento, no para uso general."
         ),
         relevancia_diagnostica=(
             "Si un equipo Windows Home muestra el disco 'cifrado' bajo Configuración > "
             "Privacidad y seguridad, no es BitLocker completo -- es Device Encryption "
             "automático ligado a la cuenta Microsoft del usuario. Para BitLocker con panel de "
             "control, unión a dominio, o Group Policy, verificar primero la edición instalada "
             "antes de sospechar de una falla de configuración o de red -- puede ser Home."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 1.3 Operating Systems"),
    dict(dominio="sistemas_operativos", concepto="Herramientas de administración de Windows (snap-ins de MMC)",
         explicacion=(
             "Visor de eventos (Event Viewer) registra errores/advertencias del sistema y "
             "aplicaciones -- primer lugar a revisar ante un fallo intermitente sin causa "
             "obvia. Administrador de dispositivos muestra hardware y sus controladores/errores "
             "(código amarillo = advertencia, código rojo = deshabilitado/fallando). "
             "Administración de discos permite particionar/formatear sin perder datos de otras "
             "particiones. Programador de tareas automatiza scripts/mantenimiento. "
             "Servicios (services.msc) muestra qué procesos de fondo están corriendo/detenidos "
             "y su tipo de inicio (automático/manual/deshabilitado)."
         ),
         relevancia_diagnostica=(
             "Ante 'la aplicación deja de funcionar sin mensaje de error claro', revisar el "
             "Visor de Eventos primero -- casi siempre hay un registro con el motivo real, "
             "ahorra tiempo comparado con reinstalar a ciegas."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 1.4 Operating Systems"),
    dict(dominio="sistemas_operativos", concepto="Comandos de línea de comandos de Windows esenciales",
         explicacion=(
             "sfc /scannow repara archivos de sistema corruptos. chkdsk revisa/repara errores "
             "del disco. gpupdate /force aplica cambios de política de grupo sin esperar el "
             "ciclo automático. gpresult /r muestra qué políticas se aplicaron realmente a un "
             "equipo (útil cuando una política 'no se aplica'). diskpart administra particiones "
             "a bajo nivel. net use conecta unidades de red. netstat -ano muestra conexiones "
             "activas con su PID, útil para identificar qué proceso usa un puerto sospechoso."
         ),
         relevancia_diagnostica=(
             "Una política de grupo que se configuró correctamente pero 'no se aplica' a un "
             "equipo específico, correr gpresult /r en ESE equipo revela si la política llegó "
             "y por qué, en vez de reconfigurar la política de nuevo sin diagnóstico."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 1.4 / 1.5 Operating Systems"),
    dict(dominio="windows_ad", concepto="Active Directory: unidades organizativas (OU) y objetos de política de grupo (GPO)",
         explicacion=(
             "Las OU agrupan equipos/usuarios para aplicar políticas distintas por área (ej. "
             "recepción vs administración). Un GPO vinculado a una OU aplica solo a los objetos "
             "de esa OU y sus sub-OUs -- no es global salvo que se vincule al dominio raíz. "
             "Las carpetas home y scripts de inicio de sesión también se configuran vía "
             "políticas ligadas al perfil de usuario en el DC."
         ),
         relevancia_diagnostica=(
             "Un usuario que se mueve de un área a otra (ej. de recepción a administración) y "
             "conserva permisos o restricciones del área anterior, sospechar de que su cuenta "
             "no se movió a la OU correcta en Active Directory -- no es una falla de red."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Operating Systems"),
    dict(dominio="sistemas_operativos", concepto="Comandos básicos de Linux para diagnóstico rápido",
         explicacion=(
             "ps aux lista procesos corriendo. top/htop muestra uso de CPU/RAM en vivo. df -h "
             "muestra espacio en disco por partición. grep busca texto dentro de archivos "
             "(muy usado sobre logs). chmod/chown administran permisos y dueño de archivos. "
             "systemctl status <servicio> muestra si un servicio está activo, fallando, o "
             "detenido, y sus últimas líneas de log."
         ),
         relevancia_diagnostica=(
             "Un servidor Linux que 'se puso lento' sin causa aparente, correr top/htop primero "
             "identifica en segundos si es CPU, RAM o un proceso específico descontrolado -- "
             "más rápido que revisar configuración a ciegas."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 1.10 Operating Systems / administración Linux"),

    # ══════ A+ CORE 2 220-1202 — 2.0 SEGURIDAD (28%) ══════
    dict(dominio="seguridad", concepto="Zero Trust, MFA, SSO y gestión de acceso privilegiado (PAM)",
         explicacion=(
             "Zero Trust asume que ningún dispositivo o usuario es confiable por defecto, "
             "incluso dentro de la red interna -- cada acceso se verifica explícitamente. MFA "
             "(autenticación multifactor) combina algo que sabes (contraseña) + algo que tienes "
             "(token/app) + a veces algo que eres (biometría). SSO (inicio de sesión único) "
             "permite autenticarse una vez para acceder a múltiples sistemas -- reduce fatiga "
             "de contraseñas pero también significa que una sola cuenta comprometida abre más "
             "puertas. PAM restringe y audita específicamente las cuentas con privilegios "
             "administrativos, que son el objetivo más valioso para un atacante."
         ),
         relevancia_diagnostica=(
             "Al diseñar accesos para un cliente nuevo, las cuentas administrativas de "
             "infraestructura (routers, switches, PMS) deben tener MFA y estar bajo un esquema "
             "PAM -- son las que, si se comprometen, dan control total de la operación."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.1 Security"),
    dict(dominio="seguridad_endpoint", concepto="BitLocker vs EFS: cifrado de disco completo vs cifrado de archivo",
         explicacion=(
             "BitLocker cifra el disco completo -- protege contra robo físico del equipo (si "
             "roban el disco, no pueden leer nada sin la clave de recuperación). EFS (Encrypting "
             "File System) cifra archivos/carpetas específicos y está ligado a la cuenta de "
             "usuario de Windows -- si se reinstala el perfil o se resetea la contraseña sin la "
             "clave de recuperación de EFS, los archivos cifrados quedan irrecuperables."
         ),
         relevancia_diagnostica=(
             "Antes de resetear la contraseña de un usuario o reconstruir su perfil de Windows, "
             "verificar si tiene archivos cifrados con EFS -- resetear sin exportar antes el "
             "certificado de EFS puede volver esos archivos permanentemente inaccesibles."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Security"),
    dict(dominio="seguridad_endpoint", concepto="Permisos NTFS vs permisos de recurso compartido (share): cuál gana",
         explicacion=(
             "Cuando un recurso se accede por red, aplican DOS capas de permisos: los del "
             "recurso compartido (share) y los de NTFS del archivo/carpeta subyacente. El "
             "resultado efectivo es el MÁS RESTRICTIVO de ambos -- si el share da 'control "
             "total' pero NTFS solo da 'lectura', el usuario solo puede leer. Accediendo "
             "localmente (no por red) solo aplican los permisos NTFS."
         ),
         relevancia_diagnostica=(
             "Un usuario que 'no puede escribir' en una carpeta compartida aunque el "
             "administrador jura que le dio permiso completo -- revisar AMBAS capas (share y "
             "NTFS), casi siempre una de las dos quedó más restrictiva que la otra."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Security"),
    dict(dominio="seguridad_endpoint", concepto="Taxonomía de malware y por qué importa distinguir el tipo",
         explicacion=(
             "Ransomware cifra archivos y exige pago. Keylogger captura pulsaciones de teclado "
             "silenciosamente (roba credenciales, no daña archivos). Rootkit se esconde a nivel "
             "de sistema operativo/kernel, difícil de detectar con antivirus normal. Spyware "
             "recopila información de uso sin consentimiento. Cryptominer usa CPU/GPU de la "
             "víctima para minar criptomonedas -- síntoma característico: ventiladores a tope y "
             "CPU alta constante sin razón aparente. Malware sin archivo (fileless) vive en "
             "memoria/PowerShell, no deja archivo en disco, por lo que escaneos tradicionales de "
             "archivos no lo detectan."
         ),
         relevancia_diagnostica=(
             "Un equipo con CPU al 100% constante, ventiladores siempre a máxima velocidad, sin "
             "ningún proceso pesado visible en Task Manager, sospechar de cryptominer o malware "
             "sin archivo -- requiere herramientas de detección de comportamiento, no solo "
             "escaneo de archivos."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.4 Security"),
    dict(dominio="seguridad", concepto="Proceso de eliminación de malware en pasos (metodología SOHO)",
         explicacion=(
             "1) Identificar y verificar los síntomas de malware. 2) Poner en cuarentena el "
             "sistema afectado (desconectar de la red). 3) Deshabilitar la restauración del "
             "sistema (System Restore) en Windows, para no reintroducir el malware desde un "
             "punto de restauración infectado. 4) Remediar el sistema afectado (actualizar el "
             "software antimalware, luego escanear y eliminar con las técnicas disponibles -- "
             "modo seguro, entorno de preinstalación). 5) Si la remediación no es confiable o "
             "la infección fue severa, reimagen/reinstalación completa del sistema -- la "
             "versión actual del objetivo oficial (220-1202 V15) reconoce esto como paso "
             "independiente, no como último recurso improvisado. 6) Programar escaneos y "
             "actualizar el software de seguridad. 7) Habilitar de nuevo System Restore y crear "
             "un punto limpio. 8) Educar al usuario final sobre cómo se infectó, para prevenir "
             "recurrencia. El orden importa -- deshabilitar restauración ANTES de remediar es "
             "lo que evita que el malware regrese desde un punto de restauración guardado."
         ),
         relevancia_diagnostica=(
             "Si un equipo se reinfecta poco después de haberse 'limpiado', sospechar que no se "
             "deshabilitó System Restore antes de remediar, y el malware volvió desde un punto "
             "de restauración infectado guardado previamente."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.6 Security"),
    dict(dominio="seguridad", concepto="Variantes de ingeniería social más allá del phishing genérico",
         explicacion=(
             "Vishing es phishing por llamada de voz. Smishing es phishing por SMS. Whaling es "
             "phishing dirigido específicamente a ejecutivos/gerencia (objetivo de alto valor, "
             "mensaje muy personalizado). Pretexting es inventar un escenario falso creíble para "
             "obtener información (ej. hacerse pasar por soporte técnico pidiendo la "
             "contraseña 'para verificar la cuenta'). Todas explotan confianza o urgencia, no "
             "una falla técnica -- por eso ninguna solución de software las previene por "
             "completo, se requiere capacitación del usuario."
         ),
         relevancia_diagnostica=(
             "Un empleado que reporta haber dado una contraseña por teléfono a alguien que "
             "'sonaba como soporte técnico de la empresa' es un caso de vishing/pretexting -- "
             "la respuesta correcta es cambiar esa credencial de inmediato y reforzar "
             "capacitación, no buscar una falla técnica que explique el incidente."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.5 Security"),
    dict(dominio="control_acceso", concepto="Medidas de seguridad física: capas complementarias, no sustitutas",
         explicacion=(
             "Badges/tarjetas de acceso, biometría, mantrap (esclusa de doble puerta que impide "
             "el 'tailgating' -- que alguien sin acceso entre pegado a alguien autorizado), "
             "cámaras, guardias y cerraduras físicas son capas independientes. Ninguna sustituye "
             "a las demás: un mantrap sin cámaras no deja evidencia de quién intentó colarse; "
             "cámaras sin control de acceso solo graban, no impiden la entrada."
         ),
         relevancia_diagnostica=(
             "Al evaluar la seguridad física de un cuarto de equipos/servidores en un hotel, "
             "revisar que exista control de acceso (no solo cerradura simple) Y registro "
             "(cámara o bitácora) -- una sola capa deja un punto ciego evidente ante auditoría."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.1 Security"),
    dict(dominio="dispositivos_moviles", concepto="Endurecimiento (hardening) de dispositivos móviles corporativos",
         explicacion=(
             "Requerir biometría o PIN fuerte para desbloqueo, mantener el sistema operativo "
             "actualizado, habilitar cifrado de almacenamiento, gestionar el dispositivo vía MDM "
             "(Mobile Device Management) para poder aplicar políticas remotas, y tener "
             "capacidad de borrado remoto (remote wipe) en caso de pérdida o robo."
         ),
         relevancia_diagnostica=(
             "Un dispositivo móvil corporativo perdido o robado sin capacidad de borrado remoto "
             "configurada representa una exposición real de datos -- verificar que el MDM esté "
             "activo ANTES de que ocurra un incidente, no después."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.8 Security"),
    dict(dominio="seguridad_endpoint", concepto="Métodos de destrucción de datos y cuándo usar cada uno",
         explicacion=(
             "Borrado seguro por software (sobrescritura múltiple) sirve para discos que se "
             "reutilizarán. Desmagnetización (degaussing) destruye discos mecánicos por completo "
             "pero NO funciona en SSD (no tienen componente magnético). Trituración física es el "
             "único método verdaderamente irreversible, requerido cuando el disco contiene "
             "información muy sensible y no se reutilizará. Un 'formateo rápido' NO destruye "
             "datos -- solo borra la tabla de referencia, los datos siguen recuperables."
         ),
         relevancia_diagnostica=(
             "Antes de dar de baja o revender un equipo que manejó datos de huéspedes/pagos, "
             "nunca confiar en un formateo simple -- requiere borrado seguro certificado o "
             "destrucción física, según la sensibilidad de los datos que manejó."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.9 Security"),
    dict(dominio="seguridad", concepto="Seguridad de red SOHO: lo mínimo que no debería faltar",
         explicacion=(
             "Cambiar credenciales por defecto del router/AP (la causa #1 de compromisos SOHO), "
             "deshabilitar puertos/servicios de administración no usados (ej. WPS, gestión "
             "remota desde WAN), considerar whitelisting de MAC para dispositivos críticos, "
             "mantener firmware actualizado, y segmentar redes de invitados de las "
             "administrativas."
         ),
         relevancia_diagnostica=(
             "Antes de dar por ‘seguro’ un router/AP recién instalado, verificar explícitamente "
             "que las credenciales por defecto se cambiaron -- es el hallazgo más común y más "
             "crítico en auditorías, y se olvida con facilidad en instalaciones apuradas."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 2.10 Security"),

    # ══════ A+ CORE 2 220-1202 — 4.0 PROCEDIMIENTOS OPERATIVOS (21%) ══════
    dict(dominio="backup", concepto="Esquema de rotación de backups GFS (abuelo-padre-hijo) y la regla 3-2-1",
         explicacion=(
             "GFS mantiene backups diarios (hijo), semanales (padre) y mensuales (abuelo), cada "
             "nivel con su propio tiempo de retención -- permite restaurar tanto un archivo "
             "borrado ayer como uno borrado hace dos meses, sin guardar un backup diario "
             "completo indefinidamente. La regla 3-2-1 complementa esto: 3 copias de los datos, "
             "en 2 tipos de medio distintos, con 1 copia fuera del sitio (offsite) -- para que "
             "un incendio o robo local no destruya también el backup."
         ),
         relevancia_diagnostica=(
             "Si todos los backups de un cliente están en un disco dentro del mismo cuarto que "
             "el servidor, eso viola la regla 3-2-1 (falta la copia offsite) -- un incendio o "
             "robo destruiría datos y backup a la vez, sin importar qué tan buena sea la "
             "rotación GFS interna."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.3 Operational Procedures"),
    dict(dominio="gestion_documentacion", concepto="Gestión de cambios (change management) formal",
         explicacion=(
             "Un cambio en producción (actualizar firmware, cambiar VLAN, reemplazar un switch "
             "core) debería pasar por: solicitud documentada, análisis de impacto/riesgo, "
             "aprobación, ventana de mantenimiento acordada, y -- crítico -- un plan de "
             "rollback definido ANTES de ejecutar el cambio, no improvisado si algo sale mal."
         ),
         relevancia_diagnostica=(
             "Antes de aplicar un cambio de red en horario de operación del hotel (no en "
             "ventana de mantenimiento), evaluar si el riesgo de interrupción justifica no "
             "esperar -- y siempre tener claro cómo revertir el cambio en menos de 5 minutos si "
             "algo falla."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.2 Operational Procedures"),
    dict(dominio="metodologia", concepto="Cadena de custodia y orden de volatilidad en respuesta a incidentes",
         explicacion=(
             "Cadena de custodia es el registro documentado de quién tuvo acceso a una "
             "evidencia digital y cuándo -- necesario si el incidente puede terminar en acción "
             "legal. Orden de volatilidad (RFC 3227) indica qué evidencia capturar primero "
             "porque se pierde más rápido: registros y caché de CPU primero (se pierden en "
             "nanosegundos), luego tablas de enrutamiento, caché ARP, tabla de procesos activos "
             "y estadísticas del kernel, luego el volcado completo de memoria RAM, luego "
             "sistemas de archivos temporales, y al final archivos en disco (lo más "
             "persistente)."
         ),
         relevancia_diagnostica=(
             "Ante un incidente de seguridad grave (ej. sospecha de intrusión activa), nunca "
             "apagar el equipo comprometido de inmediato -- eso destruye la evidencia más "
             "volátil (RAM, conexiones activas) antes de poder capturarla."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.6 Operational Procedures"),
    dict(dominio="metodologia", concepto="Comunicación profesional con el usuario final",
         explicacion=(
             "Evitar jerga técnica innecesaria, escuchar activamente sin interrumpir, no "
             "menospreciar el conocimiento del usuario ni culparlo, mantener la calma incluso "
             "ante frustración del cliente, y confirmar que el usuario entendió la solución "
             "antes de cerrar el caso -- no solo que el problema técnico se resolvió."
         ),
         relevancia_diagnostica=(
             "Un ticket técnicamente resuelto pero donde el usuario sigue confundido sobre qué "
             "pasó o qué hacer si se repite, no está realmente cerrado desde la perspectiva de "
             "servicio -- confirmar comprensión es parte del cierre, no un extra."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.7 Operational Procedures"),
    dict(dominio="metodologia", concepto="Fundamentos de scripting para automatización básica",
         explicacion=(
             "Variables, bucles y comillas correctas son la base de cualquier script en "
             "Bash/PowerShell/Python. Un riesgo real: correr un script encontrado en internet "
             "sin leerlo primero, o sin probarlo en un entorno aislado -- un script mal escrito "
             "puede borrar archivos, saturar un servicio, o modificar permisos masivamente sin "
             "posibilidad de deshacer el daño."
         ),
         relevancia_diagnostica=(
             "Antes de correr cualquier script de automatización nuevo contra un servidor de "
             "producción, probarlo primero en un entorno de prueba o al menos leerlo línea por "
             "línea -- el ahorro de tiempo de no revisarlo no compensa el riesgo de un error "
             "irreversible en producción."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.8 Operational Procedures"),
    dict(dominio="acceso_remoto", concepto="Tecnologías de acceso remoto y su tradeoff de seguridad",
         explicacion=(
             "RDP (Escritorio Remoto) da control total de una sesión Windows -- nunca debe "
             "exponerse directamente a internet sin VPN, es uno de los vectores de ataque más "
             "comunes cuando se deja abierto. VNC es similar pero multiplataforma, con cifrado "
             "más débil por defecto en muchas implementaciones. SSH da acceso a línea de "
             "comandos, cifrado por diseño, el estándar para administración remota de "
             "servidores Linux/red. Las herramientas de asistencia remota comercial (ej. "
             "AnyDesk, TeamViewer) facilitan soporte puntual pero requieren confiar en el "
             "proveedor del software como intermediario."
         ),
         relevancia_diagnostica=(
             "Un servidor con el puerto RDP (3389) expuesto directamente a internet sin VPN de "
             "por medio es una vulnerabilidad crítica inmediata, independientemente de qué tan "
             "fuerte sea la contraseña -- los ataques de fuerza bruta contra RDP expuesto son "
             "automatizados y constantes."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.9 Operational Procedures"),
    dict(dominio="metodologia", concepto="Limitaciones de la IA generativa aplicadas a soporte técnico",
         explicacion=(
             "CompTIA incorporó en A+ Core 2 V15 (2024) el reconocimiento explícito de que las "
             "herramientas de IA generativa usadas en soporte técnico tienen limitaciones "
             "reales: sesgo heredado de los datos de entrenamiento, alucinaciones (generar "
             "respuestas que suenan seguras pero son incorrectas), precisión variable según el "
             "tema, y riesgo de privacidad si se envía información sensible del cliente a un "
             "servicio de IA externo sin control sobre dónde queda esa información."
         ),
         relevancia_diagnostica=(
             "Este es exactamente el motivo de diseño detrás de las Fases 3 y 4 del cerebro de "
             "Shomer: el LLM propone una hipótesis (puede alucinar), pero el sistema la "
             "verifica en vivo contra el equipo real ANTES de concluir, y solo aprende de "
             "conclusiones confirmadas -- nunca se confía ciegamente en la salida del modelo "
             "de lenguaje, siguiendo exactamente esta precaución oficial de CompTIA."
         ),
         fuente="CompTIA A+ Core 2 220-1202 — 4.10 Operational Procedures (nuevo en V15, 2024)"),

    # ══════ SECURITY+ SY0-701 — 1.0 CONCEPTOS GENERALES DE SEGURIDAD (12%) ══════
    dict(dominio="seguridad", concepto="Categorías y tipos de controles de seguridad",
         explicacion=(
             "Categorías: técnico (implementado en sistemas, ej. firewall), gerencial "
             "(políticas y decisiones, ej. una política de contraseñas), operacional (procesos "
             "que ejecutan personas, ej. capacitación) y físico (barreras tangibles, ej. "
             "cerraduras). Tipos, independientes de la categoría: preventivo (evita que ocurra), "
             "disuasivo (desalienta sin impedir físicamente), detectivo (detecta después de que "
             "ocurre), correctivo (repara el daño), compensatorio (alternativa cuando el control "
             "ideal no es viable) y directivo (dicta un comportamiento requerido, ej. una "
             "política firmada). Un mismo control puede clasificarse en ambos ejes a la vez -- "
             "una cámara es técnica y detectiva."
         ),
         relevancia_diagnostica=(
             "Al documentar por qué existe un control de seguridad específico en un sitio, "
             "identificar su categoría Y su tipo ayuda a detectar huecos reales -- ej. tener "
             "solo controles detectivos (cámaras) sin ningún preventivo (cerraduras/control de "
             "acceso) en un cuarto de equipos es una brecha de diseño, no solo de ejecución."
         ),
         fuente="CompTIA Security+ SY0-701 — 1.1 General Security Concepts"),
    dict(dominio="seguridad", concepto="Zero Trust: arquitectura de plano de control y plano de datos",
         explicacion=(
             "El plano de control decide QUÉ se permite: identidad adaptativa (el nivel de "
             "confianza cambia según contexto -- hora, ubicación, dispositivo), reducción del "
             "alcance de amenaza (segmentar para que un compromiso no se propague), control de "
             "acceso basado en políticas, un Policy Administrator (traduce la decisión en "
             "configuración) y un Policy Engine (evalúa la política contra cada solicitud). El "
             "plano de datos EJECUTA esa decisión: zonas de confianza implícita (mínimas, "
             "idealmente ninguna), el sujeto/sistema que pide acceso, y el Policy Enforcement "
             "Point (el punto real donde se permite o bloquea el tráfico). Zero Trust no es un "
             "producto -- es rediseñar para que ningún acceso se conceda solo por estar 'dentro "
             "de la red'."
         ),
         relevancia_diagnostica=(
             "Al diseñar la red de un cliente nuevo, la pregunta de Zero Trust no es '¿está "
             "dentro del firewall perimetral?' sino '¿este sujeto específico, en este momento, "
             "está autorizado para ESTA acción específica?' -- un servidor PMS comprometido no "
             "debería poder alcanzar libremente cámaras o control de acceso solo por compartir "
             "VLAN."
         ),
         fuente="CompTIA Security+ SY0-701 — 1.2 General Security Concepts"),
    dict(dominio="seguridad", concepto="Tecnología de decepción y disrupción: honeypot, honeynet, honeyfile, honeytoken",
         explicacion=(
             "Honeypot es un sistema señuelo que simula ser un objetivo real para atraer y "
             "estudiar atacantes. Honeynet es una red completa de honeypots, simulando una "
             "infraestructura real. Honeyfile es un archivo señuelo (ej. 'contraseñas.xlsx') "
             "que, si se abre o copia, dispara una alerta -- nadie legítimo debería tocarlo. "
             "Honeytoken es una credencial o dato falso sembrado deliberadamente; su uso en "
             "cualquier sistema real es, por definición, evidencia de acceso no autorizado."
         ),
         relevancia_diagnostica=(
             "Sembrar un honeytoken (ej. una credencial falsa de 'administrador PMS' que no se "
             "usa en ningún sistema real) y alertar si alguna vez se intenta usar es una forma "
             "barata de detectar movimiento lateral de un atacante que ya está dentro de la red, "
             "sin depender solo de firmas de malware conocidas."
         ),
         fuente="CompTIA Security+ SY0-701 — 1.2 General Security Concepts"),
    dict(dominio="criptografia", concepto="PKI, cifrado simétrico vs asimétrico, y por qué se combinan en la práctica",
         explicacion=(
             "Cifrado simétrico usa la misma clave para cifrar y descifrar -- rápido, pero "
             "distribuir la clave de forma segura es el problema. Asimétrico usa un par "
             "clave pública/clave privada -- resuelve la distribución (la pública se comparte "
             "libremente) pero es mucho más lento computacionalmente. Por eso TLS/HTTPS usa "
             "asimétrico solo para negociar una clave de sesión, y luego cifra el tráfico real "
             "con simétrico -- lo mejor de ambos. La Infraestructura de Clave Pública (PKI) es "
             "el sistema de certificados, autoridades certificadoras (CA) y listas de "
             "revocación (CRL)/OCSP que permite confiar en que una clave pública realmente "
             "pertenece a quien dice ser."
         ),
         relevancia_diagnostica=(
             "Un navegador que marca un sitio interno como 'no seguro' o con certificado "
             "inválido, revisar primero si el certificado está autofirmado (self-signed, normal "
             "en sistemas internos pero requiere distribuir el certificado raíz a los clientes) "
             "antes de asumir un ataque de intermediario."
         ),
         fuente="CompTIA Security+ SY0-701 — 1.4 General Security Concepts"),
    dict(dominio="criptografia", concepto="Hashing, salting y por qué nunca se debe 'descifrar' una contraseña",
         explicacion=(
             "Una contraseña bien almacenada no se cifra (reversible), se hashea (una función "
             "de un solo sentido -- no existe forma matemática de revertirla). Salting agrega "
             "un valor aleatorio único por usuario antes de hashear, para que dos usuarios con "
             "la misma contraseña no produzcan el mismo hash -- esto derrota los ataques de "
             "tabla precalculada (rainbow tables). Key stretching (ej. PBKDF2, bcrypt) hace el "
             "hashing deliberadamente lento para encarecer los ataques de fuerza bruta."
         ),
         relevancia_diagnostica=(
             "Si un proveedor de software ofrece 'recuperar tu contraseña olvidada' mostrándola "
             "en texto plano por correo (en vez de forzar un reseteo), es una señal de que esa "
             "aplicación NO está hasheando contraseñas correctamente -- una alerta de seguridad "
             "seria sobre ese sistema, más allá del incidente puntual."
         ),
         fuente="CompTIA Security+ SY0-701 — 1.4 General Security Concepts"),

    # ══════ SECURITY+ SY0-701 — 2.0 AMENAZAS, VULNERABILIDADES Y MITIGACIONES (22%) ══════
    dict(dominio="seguridad", concepto="Actores de amenaza: quién ataca y por qué importa distinguirlos",
         explicacion=(
             "Nation-state (recursos casi ilimitados, objetivos geopolíticos, muy sofisticado). "
             "Unskilled attacker/'script kiddie' (usa herramientas de otros, poco sofisticado, "
             "pero puede causar daño real por volumen). Hacktivist (motivación ideológica). "
             "Insider threat (ya tiene acceso legítimo -- el control perimetral no sirve contra "
             "este). Organized crime (motivación financiera, buena organización). Shadow IT (no "
             "es un atacante externo -- es un empleado usando herramientas no autorizadas por TI, "
             "creando un riesgo no gestionado sin intención maliciosa)."
         ),
         relevancia_diagnostica=(
             "Ante cualquier incidente de seguridad, identificar primero si el vector fue "
             "externo o interno cambia toda la respuesta -- un insider threat requiere revisar "
             "accesos y permisos ya otorgados, no reforzar el perímetro que ya fue rodeado desde "
             "dentro."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.1 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="seguridad_endpoint", concepto="Taxonomía completa de ataques de malware y su diferencia clave",
         explicacion=(
             "Virus requiere que el usuario ejecute algo (un archivo, una macro) para "
             "propagarse. Worm (gusano) se autopropaga por la red SIN acción del usuario -- "
             "mucho más rápido y peligroso en redes planas sin segmentación. Logic bomb "
             "permanece inactivo hasta que se cumple una condición específica (una fecha, un "
             "evento) -- común en sabotaje de insiders que programan el ataque para después de "
             "irse de la empresa. Bloatware no es malicioso por diseño pero consume recursos "
             "innecesariamente y a veces abre superficie de ataque adicional preinstalada."
         ),
         relevancia_diagnostica=(
             "Un malware que se propaga a otros equipos de la red sin que ningún usuario haya "
             "abierto nada sospechoso apunta a un worm, no a un virus -- la respuesta correcta "
             "es segmentar/aislar la red inmediatamente, no solo educar a los usuarios sobre no "
             "abrir adjuntos."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="gestion_vulnerabilidades", concepto="Vulnerabilidades de aplicación: condiciones de carrera TOC/TOU",
         explicacion=(
             "Time-of-check a Time-of-use (TOC/TOU) es una condición de carrera donde un "
             "programa verifica una condición (ej. '¿tengo permiso para este archivo?') pero el "
             "estado cambia antes de que se use el resultado de esa verificación -- un atacante "
             "puede explotar esa ventana de tiempo entre el chequeo y el uso real. Memory "
             "injection y buffer overflow son otras vulnerabilidades de aplicación clásicas: "
             "escribir más datos de los que un espacio de memoria reservado puede contener, "
             "sobrescribiendo memoria adyacente que no debería tocarse."
         ),
         relevancia_diagnostica=(
             "Estas vulnerabilidades se corrigen en el código de la aplicación, no con "
             "configuración de red -- si un escaneo de vulnerabilidades marca una aplicación "
             "propia con hallazgos de este tipo, escalar al desarrollador del software, no "
             "intentar mitigar solo con firewall."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.3 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="gestion_vulnerabilidades", concepto="Vulnerabilidades específicas de virtualización y nube",
         explicacion=(
             "VM escape es cuando código malicioso dentro de una máquina virtual logra escapar "
             "y afectar al hipervisor o a otras VMs en el mismo host físico -- rompe el "
             "aislamiento que la virtualización promete. Resource reuse es cuando memoria/disco "
             "liberado por una VM se reasigna a otra sin borrarse completamente, filtrando datos "
             "residuales. Las vulnerabilidades cloud-specific incluyen configuraciones erróneas "
             "de buckets/contenedores de almacenamiento expuestos públicamente por error."
         ),
         relevancia_diagnostica=(
             "Antes de dar por seguro un entorno multi-tenant (varias VMs de distintos clientes "
             "en el mismo host físico), verificar el nivel de aislamiento del hipervisor -- un "
             "VM escape en ese contexto compromete a todos los clientes del host, no solo a uno."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.3 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="siem_analisis", concepto="Indicadores de actividad maliciosa que un SIEM debe vigilar",
         explicacion=(
             "Impossible travel: el mismo usuario autenticándose desde dos ubicaciones "
             "geográficamente imposibles de alcanzar en el tiempo transcurrido -- fuerte señal "
             "de credencial comprometida. Concurrent session usage: la misma cuenta con "
             "sesiones activas simultáneas desde dispositivos distintos. Out-of-cycle logging: "
             "actividad de logs fuera del patrón horario normal del sistema (ej. un servidor "
             "administrativo con actividad a las 3am sin mantenimiento programado). Resource "
             "consumption/inaccessibility: uso anómalo de CPU/red, o un recurso que se vuelve "
             "inaccesible sin explicación (posible ransomware cifrando en progreso)."
         ),
         relevancia_diagnostica=(
             "Un usuario que aparece autenticado desde dos países distintos con menos de una "
             "hora de diferencia (impossible travel) debe forzar revocación de sesión y cambio "
             "de credencial de inmediato -- no es un falso positivo típico, es de las señales "
             "más confiables de cuenta comprometida que existen."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="seguridad", concepto="Ataques de contraseña: spraying vs fuerza bruta, por qué spraying evade alertas",
         explicacion=(
             "Fuerza bruta prueba muchas contraseñas contra UNA cuenta -- fácil de detectar "
             "(dispara bloqueo de cuenta rápido). Password spraying prueba UNA contraseña común "
             "(ej. 'Verano2026!') contra MUCHAS cuentas distintas -- evade el bloqueo por "
             "intentos fallidos porque cada cuenta individual solo recibe uno o dos intentos, "
             "quedando por debajo del umbral de alerta normal."
         ),
         relevancia_diagnostica=(
             "Muchas cuentas distintas con UN intento fallido cada una, en una ventana de "
             "tiempo corta, es la firma de password spraying -- una política de bloqueo por "
             "cuenta individual no lo detiene; se necesita correlacionar intentos fallidos "
             "AGREGADOS a través de múltiples cuentas."
         ),
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),

    # ══════ SECURITY+ SY0-701 — 3.0 ARQUITECTURA DE SEGURIDAD (18%) ══════
    dict(dominio="seguridad_arquitectura", concepto="Dispositivos de red y su rol específico en la arquitectura de seguridad",
         explicacion=(
             "Jump server: único punto de entrada administrativo hacia una zona sensible -- "
             "todo acceso administrativo pasa por ahí, facilitando auditoría y reduciendo "
             "superficie de ataque. Proxy server: intermedia el tráfico saliente (o entrante), "
             "permite filtrado y ocultamiento del origen real. IPS actúa (bloquea) sobre tráfico "
             "malicioso detectado; IDS solo detecta y alerta, no bloquea -- la diferencia es "
             "crítica para entender qué esperar de cada uno. Screened subnet (antes llamada DMZ) "
             "aísla servicios expuestos a internet de la red interna."
         ),
         relevancia_diagnostica=(
             "Si un 'sistema de detección de intrusos' no bloqueó un ataque conocido, verificar "
             "primero si es un IDS (diseñado solo para alertar) y no un IPS -- no es una falla "
             "del sistema, es su diseño; el reclamo correcto sería '¿por qué no había un IPS "
             "aquí', no '¿por qué el IDS no bloqueó'."
         ),
         fuente="CompTIA Security+ SY0-701 — 3.2 Security Architecture"),
    dict(dominio="seguridad_arquitectura", concepto="Tipos de firewall: de Layer 4 simple a Next-Generation",
         explicacion=(
             "Firewall Layer 4 filtra por IP/puerto/protocolo únicamente -- no entiende el "
             "contenido del tráfico. Layer 7/WAF (Web Application Firewall) entiende el "
             "protocolo de aplicación (HTTP) y puede bloquear ataques específicos como SQL "
             "injection dentro del tráfico web permitido. NGFW (Next-Generation Firewall) "
             "combina inspección profunda de paquetes, prevención de intrusiones y control por "
             "aplicación (no solo puerto) en un solo dispositivo. UTM (Unified Threat "
             "Management) agrupa firewall + antivirus + filtrado web + más en un solo "
             "appliance, priorizando simplicidad sobre rendimiento máximo por función."
         ),
         relevancia_diagnostica=(
             "Un firewall que permite tráfico HTTPS hacia un servidor web pero no puede "
             "detectar un ataque de inyección SQL dentro de ese tráfico cifrado permitido, "
             "revisar si es solo Layer 4 -- necesitaría un WAF que inspeccione a nivel de "
             "aplicación, no una regla de puerto más estricta."
         ),
         fuente="CompTIA Security+ SY0-701 — 3.2 Security Architecture"),
    dict(dominio="seguridad_arquitectura", concepto="Clasificación de datos y sus estados (at rest / in transit / in use)",
         explicacion=(
             "Datos en reposo (at rest) están en almacenamiento -- se protegen con cifrado de "
             "disco. Datos en tránsito (in transit) viajan por la red -- se protegen con "
             "TLS/IPSec. Datos en uso (in use) están siendo procesados activamente en memoria -- "
             "el estado más difícil de proteger, requiere técnicas avanzadas como enclaves "
             "seguros o cifrado homomórfico en casos extremos, y es el estado donde más "
             "ataques de memoria (memory injection) ocurren. Las clasificaciones (pública, "
             "privada, confidencial, restringida, crítica) determinan QUÉ nivel de protección "
             "aplica en cada estado."
         ),
         relevancia_diagnostica=(
             "Cifrar el disco de un servidor (datos en reposo) no protege nada si la aplicación "
             "que corre ahí transmite esos mismos datos sin TLS hacia otro sistema -- proteger "
             "un solo estado de los tres deja los otros dos expuestos."
         ),
         fuente="CompTIA Security+ SY0-701 — 3.3 Security Architecture"),
    dict(dominio="servidor_recuperacion_desastres", concepto="Sitios de recuperación: hot, warm y cold",
         explicacion=(
             "Sitio hot: réplica completa y activa, failover casi instantáneo, el más caro de "
             "mantener. Sitio warm: infraestructura parcialmente lista (hardware presente, "
             "datos no completamente sincronizados), failover de horas. Sitio cold: solo el "
             "espacio físico y conectividad básica, sin equipo preinstalado -- failover de días, "
             "el más barato. La elección depende del RTO (Recovery Time Objective) que el "
             "negocio realmente necesita, no del presupuesto disponible por sí solo."
         ),
         relevancia_diagnostica=(
             "Antes de recomendar un sitio de recuperación cold por costo, verificar cuál es el "
             "RTO real que el cliente necesita -- una operación hotelera que no puede tolerar "
             "más de unas horas sin sistema PMS necesita al menos un sitio warm, un cold "
             "dejaría la operación parada días."
         ),
         fuente="CompTIA Security+ SY0-701 — 3.4 Security Architecture"),

    # ══════ SECURITY+ SY0-701 — 4.0 OPERACIONES DE SEGURIDAD (28%) ══════
    dict(dominio="seguridad_endpoint", concepto="Objetivos de hardening por tipo de dispositivo",
         explicacion=(
             "El hardening no es genérico -- cada tipo de dispositivo tiene su propio conjunto "
             "de pasos: móviles (MDM, cifrado, biometría), estaciones de trabajo (deshabilitar "
             "autorun, cuentas por defecto), switches/routers (deshabilitar puertos no usados, "
             "cambiar credenciales, deshabilitar protocolos de gestión inseguros como Telnet), "
             "infraestructura cloud (IAM restrictivo, buckets privados por defecto), servidores "
             "(mínimo software instalado, parches al día), sistemas ICS/SCADA (a menudo NO "
             "soportan parches sin downtime de producción, requieren controles compensatorios "
             "como segmentación estricta en vez de parchado directo)."
         ),
         relevancia_diagnostica=(
             "Un sistema ICS/SCADA o un controlador de acceso biométrico antiguo que 'no se "
             "puede parchar' sin apagar la operación no es una excusa para dejarlo expuesto -- "
             "la respuesta correcta es aislarlo en su propia VLAN sin acceso directo a internet "
             "ni a sistemas administrativos, un control compensatorio en vez del parche directo."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.1 Security Operations"),
    dict(dominio="gestion_vulnerabilidades", concepto="Ciclo completo de gestión de vulnerabilidades: identificación hasta validación",
         explicacion=(
             "Identificación: escaneo automatizado, análisis estático (revisa código sin "
             "ejecutarlo) vs dinámico (prueba la aplicación corriendo), threat feeds (OSINT, "
             "feeds propietarios, dark web), pentesting, programas de bug bounty. Análisis: "
             "confirmar que no es falso positivo/negativo, priorizar con CVSS (puntaje de "
             "severidad técnica) Y factor de exposición real (¿está expuesto a internet? ¿es "
             "crítico para el negocio?). Respuesta: parchar, transferir vía seguro, segmentar, "
             "aplicar control compensatorio, o documentar una excepción/exención formal si no "
             "se puede remediar. Validación: re-escanear para confirmar que el hallazgo "
             "realmente se cerró, no solo asumirlo."
         ),
         relevancia_diagnostica=(
             "Un hallazgo de vulnerabilidad crítica (CVSS alto) en un equipo aislado sin "
             "exposición real a internet ni a sistemas críticos debe priorizarse MÁS BAJO que "
             "un hallazgo de severidad media en un sistema expuesto y crítico -- CVSS solo, sin "
             "contexto de exposición, produce priorización equivocada."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.3 Security Operations"),
    dict(dominio="control_acceso", concepto="Modelos de control de acceso: MAC, DAC, RBAC, basado en reglas y en atributos",
         explicacion=(
             "MAC (Mandatory): el sistema, no el dueño del recurso, decide el acceso según "
             "etiquetas de clasificación -- rígido, usado en entornos de alta seguridad. DAC "
             "(Discretionary): el dueño del recurso decide quién accede -- flexible pero "
             "propenso a permisos otorgados sin control central (el modelo típico de carpetas "
             "compartidas de Windows). RBAC (Role-based): el acceso se asigna por rol/puesto, "
             "no por persona individual -- escala mejor que asignar permisos uno por uno. "
             "Basado en reglas: condiciones explícitas (ej. 'solo en horario laboral'). Basado "
             "en atributos (ABAC): combina múltiples atributos del sujeto/recurso/contexto en "
             "tiempo real -- el más flexible pero también el más complejo de auditar."
         ),
         relevancia_diagnostica=(
             "Un hotel con alta rotación de personal de recepción debería usar RBAC (asignar el "
             "rol 'recepción' con sus permisos ya definidos) en vez de DAC (dar permisos "
             "individuales a cada persona nueva) -- reduce drásticamente el riesgo de que un "
             "permiso quede mal configurado u olvidado al dar de alta o baja a alguien."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.6 Security Operations"),
    dict(dominio="control_acceso", concepto="Gestión de acceso privilegiado (PAM): just-in-time, vaulting y credenciales efímeras",
         explicacion=(
             "Password vaulting almacena credenciales privilegiadas en una bóveda central, "
             "nunca memorizadas ni escritas por humanos -- se solicitan al momento de usarlas. "
             "Just-in-time permissions otorgan privilegio elevado solo por el tiempo necesario "
             "para una tarea específica, expirando automáticamente después -- elimina cuentas "
             "'siempre administradoras' que son el objetivo más valioso de un atacante. "
             "Credenciales efímeras se generan para un solo uso o sesión y no persisten."
         ),
         relevancia_diagnostica=(
             "Una cuenta de administrador de dominio que se usa 'por comodidad' para tareas "
             "diarias rutinarias, en vez de solo cuando se necesita privilegio elevado, es "
             "exactamente el antipatrón que PAM/just-in-time busca eliminar -- cada sesión con "
             "esa cuenta activa amplía la ventana de daño si se compromete."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.6 Security Operations"),
    dict(dominio="respuesta_incidentes", concepto="Las 7 fases del proceso formal de respuesta a incidentes",
         explicacion=(
             "1) Preparación (antes de que pase algo: playbooks, herramientas, contactos "
             "listos). 2) Detección (identificar que algo anómalo está ocurriendo). 3) Análisis "
             "(confirmar que es un incidente real y entender su alcance). 4) Contención (limitar "
             "el daño sin necesariamente eliminar la causa aún -- aislar, no apagar de golpe). "
             "5) Erradicación (eliminar la causa raíz -- el malware, la cuenta comprometida). "
             "6) Recuperación (restaurar operación normal, con monitoreo reforzado por si "
             "vuelve). 7) Lecciones aprendidas (documentar qué falló y ajustar el playbook para "
             "la próxima vez -- el paso que más se omite bajo presión, y el que más valor deja "
             "a largo plazo)."
         ),
         relevancia_diagnostica=(
             "Si un incidente se cierra sin una sesión formal de lecciones aprendidas, el mismo "
             "tipo de incidente tiende a repetirse -- ese paso no es burocracia, es la única "
             "fase que convierte un incidente costoso en una mejora real y reutilizable del "
             "sistema."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.8 Security Operations"),
    dict(dominio="respuesta_incidentes", concepto="Forense digital: legal hold, cadena de custodia y e-discovery",
         explicacion=(
             "Legal hold es la instrucción formal de preservar evidencia (no borrar, no "
             "sobrescribir logs) porque puede ser relevante en un proceso legal, incluso antes "
             "de que se inicie formalmente. E-discovery es el proceso de identificar, recolectar "
             "y producir evidencia digital para un proceso legal. Estos conceptos importan aún "
             "en incidentes que parecen puramente técnicos -- borrar logs 'para liberar espacio' "
             "durante una investigación activa puede destruir evidencia legalmente relevante."
         ),
         relevancia_diagnostica=(
             "Ante cualquier incidente que involucre posible robo de datos de huéspedes o "
             "fraude con tarjetas de pago, tratar los logs y evidencia como si un legal hold ya "
             "estuviera activo -- preservar todo, documentar cadena de custodia, incluso si "
             "aún no está claro si habrá proceso legal formal."
         ),
         fuente="CompTIA Security+ SY0-701 — 4.8 Security Operations"),

    # ══════ SECURITY+ SY0-701 — 5.0 GESTIÓN Y SUPERVISIÓN DEL PROGRAMA DE SEGURIDAD (20%) ══════
    dict(dominio="gestion_riesgo", concepto="Análisis de riesgo cuantitativo: SLE, ARO y ALE",
         explicacion=(
             "SLE (Single Loss Expectancy) = valor del activo × factor de exposición -- cuánto "
             "se pierde en UN incidente. ARO (Annualized Rate of Occurrence) = cuántas veces se "
             "espera que ocurra ese incidente por año. ALE (Annualized Loss Expectancy) = SLE × "
             "ARO -- la pérdida anual esperada, la cifra que realmente justifica (o no) el gasto "
             "en un control de seguridad. Si el ALE de un riesgo es menor que el costo del "
             "control que lo mitigaría, transferir o aceptar el riesgo puede ser más racional "
             "que mitigarlo."
         ),
         relevancia_diagnostica=(
             "Antes de invertir en un control de seguridad costoso, calcular su ALE evitado -- "
             "si un control cuesta más por año de lo que la pérdida anual esperada del riesgo "
             "que mitiga, la decisión correcta puede ser transferir el riesgo (seguro) en vez de "
             "mitigarlo directamente."
         ),
         fuente="CompTIA Security+ SY0-701 — 5.2 Security Program Management and Oversight"),
    dict(dominio="gestion_riesgo", concepto="Estrategias de gestión de riesgo: transferir, aceptar, evitar, mitigar",
         explicacion=(
             "Transferir mueve el impacto financiero a un tercero (seguro cibernético, "
             "outsourcing) sin eliminar el riesgo técnico. Aceptar reconoce el riesgo y decide "
             "no actuar (por exención -- decisión de negocio informada -- o excepción -- "
             "temporal, con plan de remediar después). Evitar elimina la actividad que genera "
             "el riesgo por completo (ej. no ofrecer cierto servicio). Mitigar reduce la "
             "probabilidad o el impacto sin eliminarlo del todo (la estrategia más común, ej. "
             "parchar, segmentar)."
         ),
         relevancia_diagnostica=(
             "Cuando un cliente decide conscientemente NO remediar una vulnerabilidad de bajo "
             "impacto real por costo/complejidad, documentar esa decisión como una ACEPTACIÓN "
             "formal de riesgo con exención -- no dejarla como un hallazgo abierto sin dueño ni "
             "decisión explícita."
         ),
         fuente="CompTIA Security+ SY0-701 — 5.2 Security Program Management and Oversight"),
    dict(dominio="gobernanza_cumplimiento", concepto="Tipos de acuerdo con terceros: SLA, MOU, MSA, NDA, BPA",
         explicacion=(
             "SLA (Service-Level Agreement) define métricas de servicio medibles (tiempo de "
             "respuesta, disponibilidad) con consecuencias si no se cumplen. MOU (Memorandum of "
             "Understanding) expresa intención de colaborar, generalmente sin obligaciones "
             "legales estrictas. MSA (Master Service Agreement) establece términos generales "
             "reutilizables para múltiples proyectos futuros con el mismo proveedor. NDA "
             "(Non-Disclosure Agreement) protege información confidencial compartida. BPA "
             "(Business Partners Agreement) formaliza una relación de sociedad de negocio, "
             "incluyendo reparto de responsabilidades y ganancias."
         ),
         relevancia_diagnostica=(
             "Al contratar un proveedor externo con acceso a sistemas del cliente (ej. un "
             "integrador de PMS), verificar que exista NDA firmado ANTES de dar acceso a datos "
             "sensibles, y un SLA con métricas reales -- un MOU de buena voluntad no da ninguna "
             "obligación exigible si el proveedor falla."
         ),
         fuente="CompTIA Security+ SY0-701 — 5.3 Security Program Management and Oversight"),
    dict(dominio="gobernanza_cumplimiento", concepto="Penetration testing: entornos conocido, parcialmente conocido y desconocido",
         explicacion=(
             "Entorno conocido (antes 'white box'): el equipo de pentest tiene información "
             "completa de la infraestructura de antemano -- más rápido, prueba profundidad. "
             "Entorno parcialmente conocido ('gray box'): información limitada, simula un "
             "insider con algo de acceso. Entorno desconocido ('black box'): sin información "
             "previa, simula un atacante externo real -- más lento y realista, pero puede dejar "
             "áreas sin probar por falta de tiempo. Reconocimiento pasivo recolecta información "
             "sin tocar directamente el objetivo (OSINT); activo sí interactúa (escaneo de "
             "puertos) y puede ser detectado."
         ),
         relevancia_diagnostica=(
             "Al contratar un pentest para validar controles nuevos recién implementados, un "
             "entorno conocido da resultados más completos en el tiempo disponible; para "
             "validar qué tan realista es la defensa contra un atacante real, un entorno "
             "desconocido es más representativo -- elegir según qué pregunta se quiere "
             "responder, no por costumbre."
         ),
         fuente="CompTIA Security+ SY0-701 — 5.5 Security Program Management and Oversight"),
    dict(dominio="seguridad", concepto="Reconocimiento de comportamiento anómalo como parte de la concientización de seguridad",
         explicacion=(
             "No todo comportamiento anómalo es malicioso -- puede ser riesgoso (un empleado "
             "conectando su propio USB sin saber el riesgo), inesperado (acceso a un sistema "
             "fuera de su horario habitual sin mala intención) o no intencional (un error "
             "genuino, como enviar un correo al destinatario equivocado). El objetivo de "
             "capacitar en reconocimiento de comportamiento anómalo es que cada empleado pueda "
             "identificar y reportar estas señales en sí mismo y en otros, no solo que TI las "
             "detecte después con herramientas."
         ),
         relevancia_diagnostica=(
             "Un programa de concientización de seguridad que solo entrena 'no hagas clic en "
             "enlaces sospechosos' pero no explica CÓMO reportar cuando algo salió mal, pierde "
             "la mitad del valor -- reportar rápido un error genuino (ej. haber dado clic sin "
             "querer) reduce el daño mucho más que ocultar el error por miedo."
         ),
         fuente="CompTIA Security+ SY0-701 — 5.6 Security Program Management and Oversight"),

    # ══════ SERVER+ SK0-005 — 1.0 HARDWARE DE SERVIDOR (18%) ══════
    dict(dominio="almacenamiento", concepto="Niveles de RAID: qué protege cada uno y de qué NO protege",
         explicacion=(
             "RAID 0 (striping) mejora rendimiento pero NO ofrece redundancia -- si falla un "
             "disco, se pierde todo. RAID 1 (mirroring) duplica datos en dos discos, tolera "
             "fallo de uno. RAID 5 distribuye paridad entre discos, tolera fallo de UNO sin "
             "perder datos, con buen balance costo/capacidad. RAID 6 añade una segunda paridad, "
             "tolera fallo de DOS discos simultáneos -- más seguro pero con más overhead de "
             "escritura. RAID 10 combina mirroring + striping, alto rendimiento Y redundancia, "
             "pero usa la mitad de la capacidad total. JBOD no es RAID real -- simplemente junta "
             "discos sin redundancia ni distribución, cada disco es independiente. Ningún nivel "
             "de RAID sustituye un backup real: protege contra falla de disco, no contra "
             "borrado accidental, ransomware, o corrupción a nivel de sistema de archivos."
         ),
         relevancia_diagnostica=(
             "Un cliente que dice 'no necesito backups, tengo RAID 5' tiene un malentendido "
             "peligroso -- RAID protege contra falla física de un disco, pero un ransomware que "
             "cifra los archivos los cifra igual en todos los discos del arreglo RAID "
             "simultáneamente. Aclarar esta diferencia antes de que ocurra un incidente."
         ),
         fuente="CompTIA Server+ SK0-005 — 1.2 Server Hardware Installation and Management"),
    dict(dominio="almacenamiento", concepto="Almacenamiento compartido: NAS vs SAN y sus protocolos",
         explicacion=(
             "NAS (Network Attached Storage) opera a nivel de ARCHIVO -- se accede vía NFS "
             "(Linux/Unix) o CIFS/SMB (Windows), aparece como una carpeta de red compartida. SAN "
             "(Storage Area Network) opera a nivel de BLOQUE -- el servidor ve el almacenamiento "
             "como si fuera un disco local propio, vía iSCSI (sobre red IP normal) o Fibre "
             "Channel (red dedicada de alto rendimiento) o FCoE (Fibre Channel encapsulado en "
             "Ethernet). SAN típicamente da mejor rendimiento y es lo que usan bases de datos "
             "exigentes; NAS es más simple de administrar para archivos compartidos comunes."
         ),
         relevancia_diagnostica=(
             "Una base de datos con problemas de rendimiento de I/O corriendo sobre "
             "almacenamiento NAS (a nivel de archivo, con overhead de protocolo de red de "
             "archivos) es candidata a migrar a SAN/iSCSI (a nivel de bloque) si el presupuesto "
             "lo permite -- el tipo de almacenamiento compartido elegido tiene impacto real de "
             "rendimiento, no es solo una decisión de capacidad."
         ),
         fuente="CompTIA Server+ SK0-005 — 1.2 Server Hardware Installation and Management"),
    dict(dominio="servidor_administracion", concepto="Gestión fuera de banda (out-of-band): administrar un servidor que no responde",
         explicacion=(
             "La gestión fuera de banda (ej. iDRAC de Dell, iLO de HP, IPMI genérico) da acceso "
             "administrativo a un servidor a través de un canal INDEPENDIENTE del sistema "
             "operativo y de la red de datos principal -- funciona incluso si el SO está "
             "colgado, no arranca, o la red principal está caída, porque corre en un chip "
             "dedicado con su propia conexión de red. Permite encender/apagar remotamente, ver "
             "la consola como si se estuviera frente al servidor, y hasta montar medios de "
             "instalación remotamente (IP KVM)."
         ),
         relevancia_diagnostica=(
             "Un servidor que no responde ni a ping ni a RDP/SSH no necesariamente requiere "
             "presencia física inmediata -- si tiene gestión fuera de banda configurada (iDRAC/"
             "iLO), se puede diagnosticar y hasta reiniciar remotamente sin depender de que la "
             "red principal o el SO estén funcionando."
         ),
         fuente="CompTIA Server+ SK0-005 — 1.3 Server Hardware Installation and Management"),

    # ══════ SERVER+ SK0-005 — 2.0 ADMINISTRACIÓN DE SERVIDORES (30%) ══════
    dict(dominio="servidor_administracion", concepto="Tipos de instalación de sistema operativo de servidor",
         explicacion=(
             "Instalación GUI (interfaz gráfica completa) vs Core (Windows Server Core, sin "
             "GUI, menor superficie de ataque y menos recursos, administración por línea de "
             "comandos/PowerShell remoto). Bare metal instala directamente sobre hardware físico "
             "sin capa de virtualización. Instalación desatendida (unattended) usa un archivo de "
             "respuestas (answer file) para automatizar sin intervención humana, útil para "
             "desplegar muchos servidores idénticos -- distinto de slipstreaming, que es integrar "
             "actualizaciones o service packs directamente en el medio de instalación ANTES de "
             "desplegarlo (ambas técnicas se combinan en la práctica, pero no son lo mismo). "
             "Imaging/cloning despliega una plantilla "
             "preconfigurada en vez de instalar desde cero cada vez -- P2V (physical to virtual) "
             "convierte un servidor físico existente en una máquina virtual."
         ),
         relevancia_diagnostica=(
             "Un servidor Windows Core que 'no tiene escritorio' no está roto -- es la "
             "instalación por diseño, pensada para reducir superficie de ataque; la "
             "administración correcta es remota (PowerShell, RSAT), no buscar cómo 'activar' "
             "una interfaz gráfica que deliberadamente no está instalada."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.1 Server Administration"),
    dict(dominio="servidor_administracion", concepto="Sistemas de archivos y particionado en entornos de servidor",
         explicacion=(
             "GPT (GUID Partition Table) reemplaza al MBR (Master Boot Record) más antiguo -- "
             "soporta discos mayores a 2TB y más de 4 particiones primarias, es el estándar "
             "actual. ext4 es el sistema de archivos Linux más común. ReFS (Resilient File "
             "System) es la evolución de NTFS orientada a resiliencia de datos en Windows "
             "Server. VMFS es específico de VMware para almacenar máquinas virtuales. ZFS "
             "(usado en soluciones de almacenamiento avanzadas) integra volúmenes, snapshots y "
             "verificación de integridad de datos en un solo sistema."
         ),
         relevancia_diagnostica=(
             "Un disco de más de 2TB que no se puede inicializar completamente en Windows "
             "Server, verificar si está particionado como MBR (limitado a 2TB) en vez de GPT -- "
             "requiere reconvertir el esquema de partición, no es una falla del disco."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.1 Server Administration"),
    dict(dominio="servidor_administracion", concepto="Clustering: active-active vs active-passive, failover y heartbeat",
         explicacion=(
             "Active-active: todos los nodos del clúster procesan carga simultáneamente -- "
             "mejor uso de recursos, pero más complejo de sincronizar. Active-passive: un nodo "
             "procesa mientras otro(s) permanecen en espera, listos para tomar el control "
             "(failover) si el activo falla -- más simple, con capacidad de reserva sin uso "
             "mientras todo funciona bien. Heartbeat es la señal periódica entre nodos que "
             "confirma 'sigo vivo' -- cuando el heartbeat deja de recibirse, el clúster asume "
             "que ese nodo falló y dispara el failover. Failback es el proceso de regresar la "
             "carga al nodo original una vez que se recupera, idealmente de forma controlada y "
             "no automática para evitar oscilar entre nodos."
         ),
         relevancia_diagnostica=(
             "Un failover que se dispara sin que el nodo activo realmente haya fallado "
             "(un 'false failover') suele apuntar a un problema de red específicamente en el "
             "canal de heartbeat -- el nodo pasivo dejó de recibir la señal no porque el activo "
             "murió, sino porque el enlace de heartbeat se cayó."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.4 Server Administration"),
    dict(dominio="virtualizacion", concepto="Redes virtuales: bridged vs NAT, vNICs y virtual switches",
         explicacion=(
             "Modo bridged (direct access) conecta la VM directamente a la red física como si "
             "fuera un equipo más -- obtiene su propia IP de la red real, visible por otros "
             "equipos. Modo NAT esconde la VM detrás de la IP del host -- la VM tiene acceso "
             "saliente pero no es directamente alcanzable desde la red externa, similar a como "
             "un router NAT protege una LAN doméstica. Un virtual switch es la capa de software "
             "que conecta las vNICs (tarjetas de red virtuales) de las VMs entre sí y con la red "
             "física, replicando lo que haría un switch físico."
         ),
         relevancia_diagnostica=(
             "Una VM que 'no es alcanzable desde otros equipos de la red' pero sí tiene salida a "
             "internet, revisar primero si su adaptador de red está en modo NAT en vez de "
             "bridged -- es la causa más común de ese síntoma exacto, no un problema de firewall "
             "o de la red física."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.5 Server Administration"),
    dict(dominio="gestion_documentacion", concepto="Gestión de activos y ciclo de vida en entornos de servidor",
         explicacion=(
             "El ciclo de vida completo de un activo va de adquisición → uso → fin de vida → "
             "disposición/reciclaje, y cada etapa debe documentarse (marca, modelo, número de "
             "serie, etiqueta de activo). Las métricas de negocio asociadas -- MTBF (tiempo "
             "medio entre fallas, mide confiabilidad esperada), MTTR (tiempo medio de "
             "reparación, mide qué tan rápido se recupera), RPO (cuánto dato se puede permitir "
             "perder) y RTO (cuánto tiempo de inactividad se puede tolerar) -- deben estar "
             "documentadas ANTES de un incidente, no improvisadas durante uno."
         ),
         relevancia_diagnostica=(
             "Si al ocurrir una falla de servidor nadie sabe cuál es el RTO acordado con el "
             "cliente, la respuesta de emergencia se vuelve reactiva y sin prioridad clara -- "
             "documentar RPO/RTO por sistema crítico antes de que se necesiten es lo que permite "
             "priorizar correctamente bajo presión."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.7 Server Administration"),
    dict(dominio="servidor_administracion", concepto="Modelos de licenciamiento de software de servidor",
         explicacion=(
             "Per-core/per-socket licencia según hardware físico disponible (común en bases de "
             "datos empresariales). Per-instance licencia cada instalación individual sin "
             "importar el hardware. Per-concurrent-user licencia según usuarios simultáneos, no "
             "totales. 'True up' es el proceso de reconciliar el uso real contra lo licenciado "
             "-- crecer sin hacer true-up periódico expone a incumplimiento de licencia "
             "descubierto en una auditoría, con penalizaciones retroactivas."
         ),
         relevancia_diagnostica=(
             "Antes de agregar núcleos de CPU o instancias virtuales adicionales a un servidor "
             "con licenciamiento per-core/per-socket, verificar el modelo de licencia actual -- "
             "escalar hardware sin ajustar la licencia es una de las causas más comunes de "
             "incumplimiento accidental descubierto meses después."
         ),
         fuente="CompTIA Server+ SK0-005 — 2.8 Server Administration"),

    # ══════ SERVER+ SK0-005 — 3.0 SEGURIDAD Y RECUPERACIÓN DE DESASTRES (24%) ══════
    dict(dominio="control_acceso", concepto="Modelos de permisos específicos de administración de servidores",
         explicacion=(
             "Basado en rol (role-based): permisos ligados al puesto/función. Basado en regla "
             "(rule-based): condiciones explícitas del sistema (ej. horario). Basado en alcance "
             "(scope-based): limita la administración a un subconjunto específico de recursos "
             "(ej. un administrador que solo puede gestionar servidores de un sitio, no de "
             "todos). Segregación de funciones (segregation of duties) asegura que ninguna "
             "persona sola tenga control de principio a fin de un proceso crítico -- ej. quien "
             "aprueba un cambio no debería ser la misma persona que lo ejecuta sin supervisión. "
             "Delegación permite otorgar un subconjunto específico de permisos administrativos "
             "sin dar control total."
         ),
         relevancia_diagnostica=(
             "En una operación con un solo administrador de sistemas para todos los sitios de "
             "un cliente, la segregación de funciones es difícil de implementar por diseño -- "
             "documentar esa limitación explícitamente como riesgo aceptado es mejor que "
             "pretender que existe un control que en la práctica no puede sostenerse con una "
             "sola persona."
         ),
         fuente="CompTIA Server+ SK0-005 — 3.3 Security and Disaster Recovery"),
    dict(dominio="seguridad", concepto="Integridad de dos personas y separación de roles como mitigación",
         explicacion=(
             "Two-person integrity requiere que dos personas actúen juntas para completar una "
             "acción crítica -- ej. dividir una clave de cifrado en dos mitades, cada una en "
             "poder de una persona distinta, de forma que ninguna por sí sola pueda descifrar "
             "el dato protegido. Es una mitigación específicamente contra el insider threat: "
             "ningún control técnico perimetral detiene a alguien que ya tiene acceso legítimo, "
             "pero exigir una segunda persona para las acciones más sensibles sí reduce ese "
             "riesgo."
         ),
         relevancia_diagnostica=(
             "Para las acciones más sensibles de un cliente (ej. borrar backups completos, "
             "cambiar credenciales maestras de PMS), considerar si vale la pena exigir "
             "aprobación/ejecución de dos personas -- especialmente en clientes donde una sola "
             "persona tiene acceso administrativo total sin ningún control cruzado."
         ),
         fuente="CompTIA Server+ SK0-005 — 3.4 Security and Disaster Recovery"),
    dict(dominio="seguridad_endpoint", concepto="Decomisionamiento correcto de un servidor: más que apagarlo",
         explicacion=(
             "Antes de dar de baja un servidor: verificar que realmente ya no está en uso (no "
             "solo asumirlo), documentar el cambio en gestión de activos y de cambios, y decidir "
             "el método de destrucción de medios según la sensibilidad de los datos que manejó "
             "-- disk wiping (sobrescritura, reutilizable), degaussing (destruye magnéticamente, "
             "no sirve en SSD), shredding/crushing/incineration (físico, irreversible, para "
             "datos muy sensibles). También hay que atender el cableado (remediar cable "
             "eléctrico y de red que quedó suelto) y decidir si el hardware se recicla "
             "internamente, se dona, o se recicla externamente."
         ),
         relevancia_diagnostica=(
             "Apagar y desconectar un servidor sin verificar primero que ningún otro sistema "
             "dependía de él (ej. un servicio de autenticación, un recurso compartido usado por "
             "otro sistema) puede causar una falla en cascada inesperada -- verificar "
             "dependencias es un paso obligatorio antes del decomisionamiento, no opcional."
         ),
         fuente="CompTIA Server+ SK0-005 — 3.6 Security and Disaster Recovery"),
    dict(dominio="backup", concepto="Métodos de backup: full, incremental, differential y synthetic full",
         explicacion=(
             "Full respalda todo cada vez -- más lento y pesado, pero la restauración es "
             "simple (un solo set). Incremental respalda solo lo que cambió desde el ÚLTIMO "
             "backup (sea full o incremental) -- rápido de hacer, pero restaurar requiere el "
             "último full MÁS todos los incrementales en orden. Differential respalda todo lo "
             "que cambió desde el ÚLTIMO FULL (no desde el último differential) -- restaurar "
             "requiere solo el full más el último differential, más simple que incremental pero "
             "cada differential crece con el tiempo. Synthetic full combina un full antiguo con "
             "los incrementales posteriores para CREAR un nuevo full sin tener que volver a leer "
             "todos los datos de origen -- ahorra tiempo de ventana de backup en sistemas "
             "grandes."
         ),
         relevancia_diagnostica=(
             "Una restauración que tarda mucho más de lo esperado en un esquema incremental, "
             "revisar cuántos incrementales hay que aplicar en cadena desde el último full -- "
             "si la cadena es muy larga (muchos días sin full nuevo), considerar cambiar a "
             "differential o hacer full con más frecuencia."
         ),
         fuente="CompTIA Server+ SK0-005 — 3.7 Security and Disaster Recovery"),
    dict(dominio="servidor_recuperacion_desastres", concepto="Replicación: síncrona vs asíncrona para recuperación de desastres",
         explicacion=(
             "Replicación síncrona confirma la escritura en AMBOS sitios (primario y "
             "secundario) antes de considerar la transacción completa -- cero pérdida de datos "
             "posible (RPO cercano a cero), pero requiere baja latencia entre sitios, limitando "
             "la distancia geográfica práctica. Replicación asíncrona confirma la escritura "
             "localmente y envía la copia al sitio secundario con un pequeño retraso -- permite "
             "mayor distancia geográfica (mejor para desastres regionales) pero con RPO mayor a "
             "cero (se puede perder los últimos segundos/minutos de transacciones no replicadas "
             "aún)."
         ),
         relevancia_diagnostica=(
             "Un sitio de recuperación geográficamente distante (para sobrevivir un desastre "
             "regional real) generalmente NO puede usar replicación síncrona por la latencia -- "
             "si el cliente exige RPO cero Y recuperación ante desastre regional, esas dos "
             "exigencias están en tensión y requieren una conversación explícita de trade-offs."
         ),
         fuente="CompTIA Server+ SK0-005 — 3.8 Security and Disaster Recovery"),

    # ══════ SERVER+ SK0-005 — 4.0 TROUBLESHOOTING (28%) ══════
    dict(dominio="servidor_administracion", concepto="Metodología oficial de troubleshooting de servidor en 8 pasos",
         explicacion=(
             "1) Identificar el problema y su alcance (preguntar a usuarios, revisar qué cambió "
             "recientemente, recolectar logs, replicar si es posible, respaldar antes de tocar "
             "nada). 2) Establecer una teoría de causa probable, cuestionando lo obvio primero. "
             "3) Probar la teoría -- si no se confirma, volver al paso 2 con una teoría nueva, "
             "no forzar la teoría original. 4) Establecer un plan de acción, notificando a "
             "usuarios afectados. 5) Implementar la solución UN CAMBIO A LA VEZ, confirmando "
             "cada uno antes del siguiente -- si no resuelve, revertir ese cambio específico "
             "antes de probar otro. 6) Verificar funcionalidad completa del sistema, no solo el "
             "síntoma original. 7) Análisis de causa raíz. 8) Documentar hallazgos, acciones y "
             "resultado durante todo el proceso, no solo al final."
         ),
         relevancia_diagnostica=(
             "Cambiar dos o más cosas a la vez para 'ahorrar tiempo' al diagnosticar un servidor "
             "es la forma más común de terminar sin saber cuál cambio realmente resolvió el "
             "problema (o cuál lo empeoró) -- un cambio a la vez es más lento por incidente pero "
             "genera conocimiento reutilizable para la próxima vez."
         ),
         fuente="CompTIA Server+ SK0-005 — 4.1 Troubleshooting"),
    dict(dominio="almacenamiento", concepto="Fallas de RAID: reconstrucción de arreglo y sus riesgos",
         explicacion=(
             "Cuando un disco de un arreglo RAID falla y se reemplaza, el arreglo entra en "
             "'rebuild' (reconstrucción) -- reconstruye los datos del disco nuevo a partir de "
             "la paridad/espejo de los discos restantes. Durante ese proceso, el arreglo NO "
             "tiene redundancia completa (en RAID 5, un segundo fallo durante el rebuild pierde "
             "todo el arreglo). Discos de la misma edad/lote comprados juntos tienen mayor "
             "probabilidad de fallar en ventanas de tiempo cercanas, por eso un segundo fallo "
             "durante el rebuild no es tan raro como parece."
         ),
         relevancia_diagnostica=(
             "Durante la reconstrucción de un arreglo RAID 5 tras reemplazar un disco fallado, "
             "tratar el sistema como temporalmente SIN redundancia -- es el momento de mayor "
             "riesgo, no de menor, aunque visualmente 'ya se está arreglando'."
         ),
         fuente="CompTIA Server+ SK0-005 — 4.3 Troubleshooting"),
    dict(dominio="servidor_administracion", concepto="Desincronización de reloj (clock skew) y sus efectos en autenticación de servidor",
         explicacion=(
             "Muchos protocolos de autenticación (Kerberos en particular) rechazan solicitudes "
             "si el reloj del cliente y el servidor difieren más de un umbral configurado "
             "(típicamente 5 minutos) -- es una protección contra ataques de repetición "
             "(replay), no un error del protocolo. Un servidor sin sincronización NTP correcta "
             "puede fallar autenticaciones de dominio de forma intermitente y confusa, "
             "especialmente después de mantenimiento, cambios de zona horaria, o baterías CMOS "
             "agotadas que reinician el reloj al arrancar."
         ),
         relevancia_diagnostica=(
             "Fallas de autenticación de dominio intermitentes en un servidor, sin cambio de "
             "credenciales ni de política, revisar primero la hora del sistema contra un "
             "servidor NTP confiable -- clock skew es una causa mucho más común de lo que "
             "parece y se descarta en segundos verificando el reloj."
         ),
         fuente="CompTIA Server+ SK0-005 — 4.4 Troubleshooting"),

    # ══════ CySA+ CS0-003 — 1.0 OPERACIONES DE SEGURIDAD (33%) ══════
    dict(dominio="siem_analisis", concepto="Indicadores de actividad maliciosa relacionados con red, host y aplicación",
         explicacion=(
             "Relacionados con red: beaconing (un equipo comprometido 'llama a casa' a "
             "intervalos regulares hacia un servidor de C2, patrón muy detectable en tráfico "
             "agregado por su regularidad), comunicación peer-to-peer irregular (equipos que no "
             "deberían hablar entre sí directamente lo hacen), dispositivos no autorizados "
             "(rogue devices), escaneos/barridos de red. Relacionados con host: consumo anómalo "
             "de CPU/memoria/disco, cambios no autorizados en registro/sistema de archivos, "
             "tareas programadas no autorizadas, escalamiento de privilegios no autorizado. "
             "Relacionados con aplicación: creación inesperada de cuentas nuevas, salida "
             "inesperada, comunicación saliente inesperada, interrupción de servicio."
         ),
         relevancia_diagnostica=(
             "Un equipo que envía tráfico saliente pequeño pero MUY regular (ej. exactamente "
             "cada 60 segundos) hacia la misma IP externa es la firma clásica de beaconing de "
             "malware con C2 -- la regularidad exacta del intervalo es más sospechosa que el "
             "volumen de datos transferido."
         ),
         fuente="CompTIA CySA+ CS0-003 — 1.2 Security Operations"),
    dict(dominio="siem_analisis", concepto="Herramientas y técnicas para determinar actividad maliciosa",
         explicacion=(
             "Captura de paquetes (Wireshark para análisis visual, tcpdump para captura desde "
             "línea de comandos en servidores sin GUI). Reputación de DNS/IP (WHOIS para "
             "identificar dueño de un dominio/IP, AbuseIPDB para consultar si una IP ya fue "
             "reportada como maliciosa). Análisis de archivos (hashing para identificar un "
             "archivo de forma única y compararlo contra bases de malware conocido, VirusTotal "
             "para escanear contra decenas de motores antivirus a la vez). Sandboxing (Joe "
             "Sandbox, Cuckoo Sandbox) ejecuta un archivo sospechoso en un entorno aislado para "
             "observar su comportamiento real sin arriesgar el sistema productivo. Análisis de "
             "correo: encabezados, DKIM/DMARC/SPF (verifican que el remitente sea legítimo), "
             "enlaces embebidos."
         ),
         relevancia_diagnostica=(
             "Antes de abrir o ejecutar un archivo adjunto sospechoso para 'ver qué hace', "
             "calcular su hash y consultarlo en VirusTotal, o ejecutarlo en un sandbox aislado -- "
             "nunca en el equipo real de producción, sin importar qué tan urgente parezca "
             "confirmar si es malicioso."
         ),
         fuente="CompTIA CySA+ CS0-003 — 1.3 Security Operations"),
    dict(dominio="inteligencia_amenazas", concepto="Inteligencia de amenazas: niveles de confianza y fuentes de recolección",
         explicacion=(
             "Los niveles de confianza de un dato de inteligencia se evalúan en tres ejes: "
             "oportunidad/vigencia (timeliness -- una IP maliciosa de hace 2 años puede ya no "
             "serlo), relevancia (¿aplica a mi industria/geografía/stack tecnológico?) y "
             "precisión (accuracy -- ¿la fuente tiene historial de falsos positivos?). Fuentes "
             "abiertas (OSINT): redes sociales, blogs/foros, boletines gubernamentales, "
             "CERT/CSIRT, deep/dark web. Fuentes cerradas: feeds pagos, organizaciones de "
             "intercambio de información (ISACs por industria), fuentes internas propias (el "
             "historial de incidentes reales de la organización es, a menudo, la fuente más "
             "relevante y menos aprovechada)."
         ),
         relevancia_diagnostica=(
             "Un feed de inteligencia de amenazas genérico (no específico de la industria "
             "hotelera/hospitalidad) puede generar muchas alertas irrelevantes para Shomer -- "
             "priorizar fuentes con relevancia real (ataques a PMS, POS, sistemas de hotelería) "
             "sobre volumen bruto de indicadores genéricos."
         ),
         fuente="CompTIA CySA+ CS0-003 — 1.4 Security Operations"),
    dict(dominio="inteligencia_amenazas", concepto="Threat hunting: búsqueda proactiva, no reactiva",
         explicacion=(
             "A diferencia de la respuesta a incidentes (reactiva, algo ya disparó una alerta), "
             "el threat hunting es proactivo: un analista busca activamente evidencia de "
             "compromiso que las herramientas automatizadas NO detectaron todavía, partiendo de "
             "una hipótesis (ej. '¿hay indicadores de esta técnica de ataque específica en "
             "nuestros logs?'). Se enfoca en configuraciones/desconfiguraciones sospechosas, "
             "redes aisladas (que en teoría no deberían tener tráfico inusual, por lo que "
             "cualquier anomalía ahí es más significativa), y activos/procesos críticos del "
             "negocio. La defensa activa incluye técnicas como honeypots para atraer y estudiar "
             "atacantes deliberadamente."
         ),
         relevancia_diagnostica=(
             "Los sistemas ICS/SCADA o de control de acceso biométrico, que en teoría no "
             "deberían generar tráfico de red inusual bajo ningún escenario normal, son "
             "candidatos ideales de threat hunting -- CUALQUIER anomalía ahí es mucho más "
             "significativa que la misma anomalía en una red de usuarios general."
         ),
         fuente="CompTIA CySA+ CS0-003 — 1.4 Security Operations"),
    dict(dominio="siem_analisis", concepto="SOAR y la importancia de la automatización en operaciones de seguridad",
         explicacion=(
             "SOAR (Security Orchestration, Automation, and Response) automatiza tareas "
             "repetibles que no requieren juicio humano (ej. enriquecer una alerta con datos de "
             "un feed de reputación de IP automáticamente, en vez de que un analista lo busque "
             "manualmente cada vez). El objetivo NO es eliminar analistas humanos -- es liberar "
             "su tiempo de tareas mecánicas para que se enfoquen en decisiones que sí requieren "
             "criterio. 'Single pane of glass' significa integrar múltiples herramientas de "
             "seguridad en una sola vista consolidada, en vez de que el analista tenga que "
             "revisar 5 consolas distintas para entender un solo incidente."
         ),
         relevancia_diagnostica=(
             "Antes de automatizar una tarea de seguridad, confirmar que sea genuinamente "
             "repetible y no requiera juicio humano caso por caso -- automatizar prematuramente "
             "una decisión que en realidad necesita contexto humano (ej. '¿esta cuenta "
             "comprometida se bloquea automáticamente?') puede causar más daño que el problema "
             "que intenta resolver."
         ),
         fuente="CompTIA CySA+ CS0-003 — 1.5 Security Operations"),

    # ══════ CySA+ CS0-003 — 2.0 GESTIÓN DE VULNERABILIDADES (30%) ══════
    dict(dominio="gestion_vulnerabilidades", concepto="Tipos de escaneo de vulnerabilidades y cuándo usar cada uno",
         explicacion=(
             "Credenciado vs no credenciado: un escaneo credenciado inicia sesión en el sistema "
             "objetivo, viendo mucho más detalle (parches faltantes reales, configuración "
             "interna) que uno no credenciado, que solo ve lo expuesto externamente -- un "
             "escaneo no credenciado subestima sistemáticamente el riesgo real. Pasivo vs "
             "activo: pasivo solo observa tráfico sin interactuar (más seguro para sistemas "
             "frágiles), activo envía tráfico de prueba directamente (más completo pero puede "
             "afectar sistemas sensibles, especialmente OT/ICS/SCADA que a veces no toleran "
             "tráfico de escaneo agresivo sin caerse). Estático vs dinámico: estático analiza "
             "código sin ejecutarlo, dinámico prueba la aplicación corriendo (incluye fuzzing -- "
             "enviar entradas malformadas deliberadamente para ver qué rompe)."
         ),
         relevancia_diagnostica=(
             "Antes de correr un escaneo ACTIVO contra un sistema ICS/SCADA o un controlador "
             "biométrico antiguo, verificar primero si el fabricante garantiza que tolera "
             "tráfico de escaneo agresivo -- muchos de estos sistemas de infraestructura "
             "crítica se han caído por escaneos de vulnerabilidad mal planificados, un daño "
             "peor que la vulnerabilidad que se buscaba encontrar."
         ),
         fuente="CompTIA CySA+ CS0-003 — 2.1 Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", concepto="CVSS en profundidad: qué compone el puntaje más allá del número final",
         explicacion=(
             "El puntaje CVSS se compone de: vector de ataque (¿se explota por red, local, "
             "acceso físico?), complejidad del ataque (¿requiere condiciones especiales o es "
             "trivial?), privilegios requeridos (¿el atacante ya necesita acceso previo?), "
             "interacción del usuario (¿la víctima debe hacer algo, como abrir un archivo?), "
             "alcance (¿el impacto se queda contenido o afecta otros componentes?), e impacto en "
             "confidencialidad/integridad/disponibilidad por separado. Dos vulnerabilidades con "
             "el MISMO puntaje final pueden tener perfiles de riesgo completamente distintos -- "
             "una explotable remotamente sin autenticación es mucho más urgente que una que "
             "requiere acceso físico previo, aunque el número final sea idéntico."
         ),
         relevancia_diagnostica=(
             "Al priorizar dos hallazgos con el mismo puntaje CVSS numérico, desglosar el "
             "vector de ataque y los privilegios requeridos de cada uno -- el que se explota "
             "remotamente sin credenciales previas siempre debe priorizarse primero, "
             "independientemente de que el número final coincida."
         ),
         fuente="CompTIA CySA+ CS0-003 — 2.3 Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", concepto="Categorías de vulnerabilidad de aplicación web más allá de SQLi/XSS",
         explicacion=(
             "SSRF (Server-Side Request Forgery): el atacante engaña al SERVIDOR para que haga "
             "solicitudes a recursos internos que el atacante no podría alcanzar directamente. "
             "LFI/RFI (Local/Remote File Inclusion): la aplicación incluye un archivo local o "
             "remoto controlado por el atacante en su ejecución. Broken access control: la "
             "aplicación no verifica correctamente que un usuario tenga permiso para el recurso "
             "que solicita (ej. cambiar un ID en la URL y acceder a datos de otro usuario). "
             "Insecure design: la vulnerabilidad no es un bug de implementación sino una falla "
             "conceptual en cómo se diseñó la funcionalidad desde el inicio -- no se arregla con "
             "un parche simple, requiere rediseño."
         ),
         relevancia_diagnostica=(
             "Un sistema de reservas o PMS donde cambiar un número de ID en la URL permite ver "
             "la reserva de otro huésped es un caso clásico de broken access control -- un "
             "hallazgo grave que a menudo pasa desapercibido en escaneos automáticos porque "
             "requiere entender la LÓGICA de negocio, no solo patrones de ataque genéricos."
         ),
         fuente="CompTIA CySA+ CS0-003 — 2.4 Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", concepto="Prácticas de codificación segura como mitigación en la fuente",
         explicacion=(
             "Validación de entrada (nunca confiar en datos que vienen del usuario/cliente sin "
             "verificar). Codificación de salida (output encoding, previene que datos se "
             "interpreten como código en el contexto donde se muestran -- la causa raíz de "
             "XSS). Gestión de sesión segura (tokens que expiran, no predecibles). Consultas "
             "parametrizadas (previenen inyección SQL separando el código de consulta de los "
             "datos del usuario, en vez de concatenar strings directamente). El modelado de "
             "amenazas (threat modeling) se hace ANTES de escribir código, identificando qué "
             "podría salir mal en el diseño mismo, no después de encontrarlo en producción."
         ),
         relevancia_diagnostica=(
             "Al evaluar una integración de software personalizada para un cliente (ej. un "
             "conector propio entre PMS y un sistema de terceros), preguntar explícitamente si "
             "usa consultas parametrizadas -- concatenar strings para construir consultas SQL "
             "sigue siendo, años después, una de las causas más comunes de brechas serias."
         ),
         fuente="CompTIA CySA+ CS0-003 — 2.5 Vulnerability Management"),

    # ══════ CySA+ CS0-003 — 3.0 GESTIÓN DE RESPUESTA A INCIDENTES (20%) ══════
    dict(dominio="respuesta_incidentes", concepto="Cyber kill chain: las 7 fases de un ataque desde la perspectiva del atacante",
         explicacion=(
             "1) Reconocimiento (el atacante investiga el objetivo). 2) Weaponization "
             "(prepara el arma, ej. un documento con malware embebido). 3) Entrega (delivery -- "
             "envía el arma, ej. vía phishing). 4) Explotación (el arma se ejecuta, explota una "
             "vulnerabilidad). 5) Instalación (establece persistencia en el sistema "
             "comprometido). 6) Comando y Control -- C2 (establece un canal de comunicación con "
             "el atacante). 7) Acciones sobre objetivos (el atacante finalmente hace lo que "
             "buscaba -- exfiltrar datos, cifrar para ransomware, etc.). La utilidad práctica: "
             "interrumpir CUALQUIER fase detiene el ataque completo -- no hay que esperar a "
             "detectarlo en la fase final."
         ),
         relevancia_diagnostica=(
             "Detectar tráfico de C2 (fase 6) es más valioso que detectar solo en la fase final "
             "(exfiltración, fase 7) -- interrumpir en la fase de C2 evita que el atacante "
             "siquiera llegue a ejecutar sus acciones finales, mientras que detectar en fase 7 "
             "significa que el daño ya ocurrió."
         ),
         fuente="CompTIA CySA+ CS0-003 — 3.1 Incident Response and Management"),
    dict(dominio="respuesta_incidentes", concepto="MITRE ATT&CK y Diamond Model: dos formas complementarias de analizar un ataque",
         explicacion=(
             "MITRE ATT&CK es una matriz pública y muy detallada de tácticas y técnicas de "
             "atacantes reales observadas -- funciona como un vocabulario común para describir "
             "exactamente QUÉ técnica se usó (ej. 'T1055 Process Injection'), permitiendo "
             "comparar contra grupos de amenaza conocidos que usan esas técnicas. El Diamond "
             "Model analiza un incidente desde 4 vértices conectados: adversario, víctima, "
             "infraestructura (qué usó el atacante -- servidores C2, dominios) y capacidad (qué "
             "herramientas/malware usó) -- ayuda a entender las RELACIONES entre esos elementos, "
             "no solo listarlos por separado."
         ),
         relevancia_diagnostica=(
             "Al documentar un incidente real de Shomer, mapear la técnica observada a un "
             "identificador de MITRE ATT&CK (cuando aplique) permite comparar patrones entre "
             "distintos hoteles del futuro roadmap multi-cliente -- un vocabulario común hace "
             "posible detectar si el mismo grupo de amenaza está atacando a varios clientes."
         ),
         fuente="CompTIA CySA+ CS0-003 — 3.1 Incident Response and Management"),
    dict(dominio="respuesta_incidentes", concepto="Contención, erradicación y recuperación: por qué el orden importa",
         explicacion=(
             "Contención limita el DAÑO sin necesariamente eliminar la causa aún -- aislar de "
             "la red, no necesariamente apagar (apagar puede destruir evidencia volátil en "
             "memoria). Erradicación elimina la causa raíz real (el malware, la cuenta "
             "comprometida, la vulnerabilidad explotada) -- hacerlo antes de contener "
             "adecuadamente arriesga que el atacante note la respuesta y acelere su ataque o "
             "borre evidencia. Recuperación restaura la operación normal, generalmente vía "
             "re-imaging (reinstalar desde cero, no solo 'limpiar' el sistema comprometido, "
             "porque no se puede confiar completamente en un sistema que estuvo bajo control de "
             "un atacante) con monitoreo reforzado posterior."
         ),
         relevancia_diagnostica=(
             "Un sistema comprometido que se 'limpia' de malware sin re-imaging completo, "
             "confiando en que el antivirus eliminó todo, es un riesgo -- si el atacante "
             "estableció persistencia con técnicas que el antivirus no detectó (ej. una cuenta "
             "de puerta trasera creada, no solo un archivo malicioso), reconectarlo sin "
             "reinstalar desde cero puede permitir que el atacante regrese."
         ),
         fuente="CompTIA CySA+ CS0-003 — 3.2 Incident Response and Management"),

    # ══════ CySA+ CS0-003 — 4.0 REPORTES Y COMUNICACIÓN (17%) ══════
    dict(dominio="reportes_comunicacion", concepto="Inhibidores comunes a la remediación de vulnerabilidades",
         explicacion=(
             "No toda vulnerabilidad se puede remediar de inmediato, y reconocerlo explícitamente "
             "es parte de una gestión honesta: sistemas legacy que no soportan el parche "
             "disponible, sistemas propietarios donde solo el fabricante puede modificar el "
             "código, riesgo de interrumpir un proceso de negocio crítico, degradación de "
             "funcionalidad si se aplica el parche, o restricciones contractuales (SLA/MOU con "
             "un proveedor que limita cuándo se puede intervenir un sistema). Documentar estos "
             "inhibidores explícitamente -- con dueño y fecha de revisión -- es mejor que dejar "
             "la vulnerabilidad como un hallazgo abierto sin explicación."
         ),
         relevancia_diagnostica=(
             "Un sistema de control de acceso biométrico antiguo cuyo fabricante ya no existe "
             "(no hay a quién pedir un parche) es un inhibidor legítimo de remediación directa "
             "-- la respuesta correcta es documentarlo como excepción con control compensatorio "
             "(aislamiento de red), no dejarlo como una tarea pendiente indefinida sin "
             "explicación ni plan alterno."
         ),
         fuente="CompTIA CySA+ CS0-003 — 4.1 Reporting and Communication"),
    dict(dominio="reportes_comunicacion", concepto="Métricas clave de respuesta a incidentes: MTTD, MTTR, MTTRemediate",
         explicacion=(
             "Mean Time to Detect (MTTD): cuánto tiempo pasa entre que ocurre un incidente y se "
             "detecta -- mide qué tan buena es la visibilidad/monitoreo. Mean Time to Respond: "
             "desde que se detecta hasta que se empieza a actuar -- mide la eficiencia del "
             "proceso de escalamiento. Mean Time to Remediate: desde que se actúa hasta que el "
             "problema está realmente resuelto -- mide la capacidad de ejecución real. Un "
             "sistema con excelente MTTD pero mal MTTR tiene un problema de PROCESO "
             "(detecta rápido pero reacciona lento), no de tecnología de detección."
         ),
         relevancia_diagnostica=(
             "Si Shomer detecta un problema (MTTD bajo, gracias al monitoreo y al cerebro) pero "
             "tarda mucho en escalar o actuar sobre él (MTTR alto), el cuello de botella está en "
             "el proceso de respuesta humana o en la falta de automatización de la acción, no en "
             "la capacidad de detección -- son dos métricas distintas que requieren mejoras "
             "distintas."
         ),
         fuente="CompTIA CySA+ CS0-003 — 4.2 Reporting and Communication"),
    dict(dominio="reportes_comunicacion", concepto="Estructura de un reporte de respuesta a incidentes para distintas audiencias",
         explicacion=(
             "Un reporte de incidente completo incluye: resumen ejecutivo (para quien no tiene "
             "tiempo ni contexto técnico -- qué pasó, impacto, en 3-4 líneas), el qué/quién/"
             "cuándo/dónde/por qué detallado, línea de tiempo, alcance real, evidencia "
             "recolectada, y recomendaciones concretas. Las comunicaciones se ramifican por "
             "audiencia: legal (si hay implicaciones de cumplimiento/contractuales), relaciones "
             "públicas (si hay impacto a clientes/medios), reguladores (si la ley exige "
             "notificación, ej. brecha de datos de huéspedes), y autoridades si aplica. Cada "
             "audiencia necesita un nivel de detalle y lenguaje distinto del mismo incidente."
         ),
         relevancia_diagnostica=(
             "Un mismo incidente de seguridad en un hotel (ej. exposición de datos de tarjetas) "
             "requiere un reporte técnico detallado para el equipo de TI Y un resumen ejecutivo "
             "sin jerga para la gerencia del hotel Y posiblemente una notificación regulatoria "
             "formal -- preparar solo una versión técnica y esperar que sirva para las tres "
             "audiencias es un error común que retrasa la respuesta correcta a cada una."
         ),
         fuente="CompTIA CySA+ CS0-003 — 4.2 Reporting and Communication"),
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
         fuente="Metodología de troubleshooting de 7 pasos (estándar unificado de Shomer: identificar → teorizar → probar → plan de acción → implementar o escalar → verificar → documentar; CompTIA Network+ N10-009 — 5.1)"),
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

    # ── Seguridad — arquitectura ──
    dict(dominio="seguridad_arquitectura", patron="Se propone quitar o debilitar un control de seguridad porque 'ya hay otro que cubre lo mismo'",
         causa_probable="Pérdida de una capa de defensa en profundidad, no una simplificación segura",
         recomendacion="Mantener capas independientes -- la falla de un control no debe dejar el sistema sin ninguna protección",
         fuente="CompTIA Security+ SY0-701 — Security Architecture"),
    dict(dominio="seguridad_arquitectura", patron="Hallazgo de auditoría muestra un puerto/servicio abierto que nadie recuerda para qué es",
         causa_probable="Servicio olvidado que amplía la superficie de ataque sin ningún uso activo real",
         recomendacion="Cerrar el servicio si no se confirma un uso activo, no dejarlo abierto por costumbre",
         fuente="CompTIA Security+ SY0-701 — Threats, Vulnerabilities and Mitigations"),

    # ── Gestión de vulnerabilidades ──
    dict(dominio="gestion_vulnerabilidades", patron="Hallazgo de auditoría marcado como severidad alta en un equipo aislado sin exposición real",
         causa_probable="El puntaje de severidad técnica no considera el contexto real de exposición del equipo",
         recomendacion="Priorizar combinando severidad Y exposición/criticidad real, no solo la etiqueta de severidad aislada",
         fuente="CompTIA CySA+ CS0-003 — Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", patron="Escaneo automático marca como vulnerable un equipo de marca con soporte activo y parches recientes",
         causa_probable="Posible falso positivo por versión de banner desactualizada en el reporte, sin reflejar parches de seguridad aplicados",
         recomendacion="Verificar manualmente antes de escalar como crítico en equipos con historial de actualizaciones activas",
         fuente="CompTIA CySA+ CS0-003 — Vulnerability Management"),

    # ── SIEM / análisis (Hunter) ──
    dict(dominio="siem_analisis", patron="Bloqueo de IP externa con firma de escaneo genérico, sin actividad posterior",
         causa_probable="Ruido de fondo normal de internet (bots escaneando masivamente), no un ataque dirigido",
         recomendacion="No escalar como urgente salvo que haya señales de éxito posteriores (tráfico saliente inusual, no solo el intento de entrada)",
         fuente="CompTIA CySA+ CS0-003 — Security Operations"),
    dict(dominio="siem_analisis", patron="Ningún sistema crítico (pagos, dominio) ha sido revisado manualmente en mucho tiempo, sin alertas activas",
         causa_probable="Dependencia exclusiva de alertas automáticas, sin revisión activa (threat hunting) de amenazas sin firma conocida",
         recomendacion="Programar revisión periódica manual de sistemas críticos, no depender solo de que el IDS avise",
         fuente="CompTIA CySA+ CS0-003 — Security Operations"),

    # ── Respuesta a incidentes ──
    dict(dominio="respuesta_incidentes", patron="Ante un hallazgo de seguridad real, se empieza a investigar la causa antes de aislar el problema",
         causa_probable="Orden invertido del proceso formal de respuesta a incidentes -- se salta la fase de contención",
         recomendacion="Contener/aislar primero (bloquear IP, aislar equipo), investigar la causa raíz después",
         fuente="CompTIA Security+ SY0-701 / CySA+ CS0-003 — Incident Response"),

    # ── Server+ administración ──
    dict(dominio="servidor_administracion", patron="Servidor con storage en SAN/NAS se congela o pierde acceso a datos, el servidor mismo responde bien",
         causa_probable="Problema de conectividad de red hacia el almacenamiento compartido, no del servidor ni del disco",
         recomendacion="Diagnosticar la red hacia el storage por separado del servidor",
         fuente="CompTIA Server+ SK0-005 — Server Hardware Installation and Management"),
    dict(dominio="servidor_administracion", patron="Cambio de configuración de servidor programado en horario operativo alto (check-in/check-out)",
         causa_probable="Falta de ventana de mantenimiento acordada para el cambio",
         recomendacion="Reprogramar a horario de bajo impacto, aunque el cambio parezca seguro en teoría",
         fuente="CompTIA Server+ SK0-005 — Server Administration"),

    # ── Recuperación ante desastres ──
    dict(dominio="servidor_recuperacion_desastres", patron="Se define la frecuencia de backup de un sistema sin haber definido antes cuánta pérdida de datos es tolerable",
         causa_probable="Falta de definición de RPO/RTO antes de diseñar la estrategia de respaldo",
         recomendacion="Definir primero cuánta pérdida de datos y cuánto tiempo de caída tolera el negocio para ese sistema específico",
         fuente="CompTIA Server+ SK0-005 — Security and Disaster Recovery"),

    # ══════════════════════ A+ CORE 1 — 5.0 TROUBLESHOOTING (28% del examen, temario oficial) ══════════════════════
    # ── 5.1 Motherboard, RAM, CPU y energía ──
    dict(dominio="hardware", patron="Pitidos (POST beeps) al encender, antes de que cargue el sistema operativo",
         causa_probable="Falla de hardware detectada por el BIOS antes de iniciar el SO -- RAM, video u otro componente crítico",
         recomendacion="Contar el patrón de pitidos y consultarlo contra el manual del fabricante de la placa -- cada patrón indica un componente distinto",
         fuente="CompTIA A+ Core 1 220-1201 — 5.1 Troubleshooting"),
    dict(dominio="hardware", patron="Equipo no enciende, sin luces ni ventiladores (no power)",
         causa_probable="Fuente de poder, cable de energía, o el propio botón de encendido -- no necesariamente la placa o el CPU",
         recomendacion="Descartar fuente/cable/botón (lo más barato y rápido de probar) antes de sospechar de componentes internos costosos",
         fuente="CompTIA A+ Core 1 220-1201 — 5.1 Troubleshooting"),
    dict(dominio="hardware", patron="Olor a quemado o hinchazón visible en un capacitor de la placa",
         causa_probable="Falla eléctrica real del componente, riesgo de daño mayor o incendio si se sigue usando",
         recomendacion="Apagar y desconectar de inmediato -- no es un síntoma para 'seguir usando hasta que falle del todo'",
         fuente="CompTIA A+ Core 1 220-1201 — 5.1 Troubleshooting"),
    dict(dominio="hardware", patron="Fecha/hora del sistema incorrecta cada vez que se reinicia el equipo",
         causa_probable="Batería CMOS agotada -- no guarda la configuración de reloj sin energía externa",
         recomendacion="Reemplazar la batería CMOS -- es una pieza barata, no un problema de software ni de red (aunque puede causar fallas de autenticación por desincronización horaria)",
         fuente="CompTIA A+ Core 1 220-1201 — 5.1 Troubleshooting"),

    # ── 5.2 Discos y RAID ──
    dict(dominio="hardware", patron="Ruido de clic o rechinido proveniente de un disco duro mecánico",
         causa_probable="Falla mecánica real del disco, posible falla inminente o ya en curso",
         recomendacion="Respaldar los datos de inmediato antes de cualquier otro diagnóstico -- el ruido mecánico es una señal tardía, no temprana",
         fuente="CompTIA A+ Core 1 220-1201 — 5.2 Troubleshooting"),
    dict(dominio="hardware", patron="Un arreglo RAID aparece como incompleto o falta un disco del arreglo",
         causa_probable="Un disco individual falló o se desconectó, el arreglo sigue funcionando en modo degradado (si el nivel de RAID lo permite)",
         recomendacion="Identificar y reemplazar el disco específico fallido cuanto antes -- en modo degradado ya no hay tolerancia a una segunda falla",
         fuente="CompTIA A+ Core 1 220-1201 — 5.2 Troubleshooting"),
    dict(dominio="hardware", patron="Tiempos de lectura/escritura mucho más largos de lo normal, sin error explícito",
         causa_probable="Disco degradándose (posible predecesor de falla) o arreglo RAID reconstruyendo en segundo plano",
         recomendacion="Revisar el estado SMART del disco y si hay una reconstrucción de RAID en curso antes de asumir un problema de software",
         fuente="CompTIA A+ Core 1 220-1201 — 5.2 Troubleshooting"),

    # ── 5.3 Video, proyectores y pantallas ──
    dict(dominio="hardware", patron="Imagen borrosa o distorsionada en un monitor o proyector",
         causa_probable="Cable de video de mala calidad/dañado, resolución mal configurada, o fuente de entrada incorrecta",
         recomendacion="Verificar primero la fuente de entrada y el cable físico antes de sospechar del panel/proyector en sí",
         fuente="CompTIA A+ Core 1 220-1201 — 5.3 Troubleshooting"),
    dict(dominio="hardware", patron="Apagado intermitente de un proyector durante el uso",
         causa_probable="Sobrecalentamiento (filtro de aire obstruido) o lámpara llegando al fin de su vida útil",
         recomendacion="Revisar limpieza del filtro de aire y horas de uso de la lámpara antes de asumir falla electrónica",
         fuente="CompTIA A+ Core 1 220-1201 — 5.3 Troubleshooting"),

    # ── 5.4 Dispositivos móviles ──
    dict(dominio="dispositivos_moviles", patron="Batería de dispositivo móvil visiblemente hinchada",
         causa_probable="Degradación química de la batería -- riesgo real de seguridad, no solo pérdida de autonomía",
         recomendacion="Dejar de usar el dispositivo y reemplazar la batería de inmediato -- no es un problema estético",
         fuente="CompTIA A+ Core 1 220-1201 — 5.4 Troubleshooting"),
    dict(dominio="dispositivos_moviles", patron="Dispositivo móvil se recarga muy lento o de forma inconsistente",
         causa_probable="Cable/puerto de carga dañado, o el cargador no entrega la potencia que el dispositivo espera",
         recomendacion="Probar con un cable y cargador distintos, conocidos como buenos, antes de sospechar de la batería",
         fuente="CompTIA A+ Core 1 220-1201 — 5.4 Troubleshooting"),

    # ── 5.5 Red (síntomas específicos que faltaban) ──
    dict(dominio="redes_ip", patron="Un puerto de switch sube y baja repetidamente (port flapping)",
         causa_probable="Cable defectuoso, problema de dúplex, o el dispositivo conectado tiene una NIC fallando",
         recomendacion="Revisar el cable físico primero (causa más común y más barata de descartar) antes que configuración",
         fuente="CompTIA A+ Core 1 220-1201 — 5.5 Troubleshooting"),
    dict(dominio="redes_ip", patron="Fallas de autenticación de red intermitentes sin cambio de credenciales",
         causa_probable="Desincronización de reloj del equipo (afecta protocolos como Kerberos) o certificado próximo a vencer",
         recomendacion="Verificar hora del sistema y vigencia de certificados antes de sospechar de la contraseña o el servidor de autenticación",
         fuente="CompTIA A+ Core 1 220-1201 — 5.5 Troubleshooting"),

    # ── 5.6 Impresoras (síntomas específicos que faltaban) ──
    dict(dominio="impresoras", patron="Imágenes duplicadas o 'eco' desplazadas en la impresión láser",
         causa_probable="Tambor de imagen (unidad de imagen) desgastado o dañado",
         recomendacion="Reemplazar la unidad de imagen -- no se resuelve con más tóner ni limpieza superficial",
         fuente="CompTIA A+ Core 1 220-1201 — 5.6 Troubleshooting"),
    dict(dominio="impresoras", patron="Puntos o manchas (speckling) repetidos en el papel impreso",
         causa_probable="Tóner derramado internamente o unidad de fusión contaminada",
         recomendacion="Revisar/limpiar la unidad de fusión antes de reemplazar el cartucho de tóner completo",
         fuente="CompTIA A+ Core 1 220-1201 — 5.6 Troubleshooting"),
    dict(dominio="impresoras", patron="Atasco de grapado o perforado en un finalizador de impresora multifunción",
         causa_probable="Problema específico del módulo de acabado (finisher), no del motor de impresión principal",
         recomendacion="Aislar el diagnóstico al módulo de acabado -- reiniciar la impresora completa no resuelve un atasco mecánico ahí",
         fuente="CompTIA A+ Core 1 220-1201 — 5.6 Troubleshooting"),
    dict(dominio="impresoras", patron="Impresora no reconoce una bandeja de papel específica",
         causa_probable="Sensor de la bandeja sucio/dañado o la bandeja no está completamente asentada",
         recomendacion="Reasentar físicamente la bandeja y limpiar el sensor antes de sospechar de una falla electrónica mayor",
         fuente="CompTIA A+ Core 1 220-1201 — 5.6 Troubleshooting"),

    # ══════════════════════ NETWORK+ N10-009 — 5.0 NETWORK TROUBLESHOOTING (24%) ══════════════════════
    dict(dominio="cableado", patron="Contadores de error CRC crecientes en una interfaz específica",
         causa_probable="Cable dañado, conector mal terminado, o un par dividido (split pair) -- un error de ponchado que pasa la prueba de continuidad básica pero rompe la cancelación de ruido del par trenzado",
         recomendacion="Revisar la terminación del cable con un certificador (no solo un tester de continuidad) para descartar pares divididos, antes de sospechar del equipo",
         fuente="CompTIA Network+ N10-009 — 5.2 Network Troubleshooting"),
    dict(dominio="cableado", patron="Un equipo PoE no enciende y el switch reporta presupuesto de energía excedido",
         causa_probable="El switch ya alcanzó su límite total de potencia PoE con los equipos ya conectados",
         recomendacion="Redistribuir equipos entre switches o verificar si el estándar PoE configurado coincide con lo que requiere el equipo nuevo",
         fuente="CompTIA Network+ N10-009 — 5.2 Network Troubleshooting"),
    dict(dominio="switching", patron="Toda la red se vuelve lenta después de conectar un cable redundante entre dos switches",
         causa_probable="Loop de red -- spanning tree recalculando, o STP deshabilitado en ese segmento",
         recomendacion="Verificar que spanning tree esté activo y funcionando en ambos switches antes de dejar el enlace redundante conectado",
         fuente="CompTIA Network+ N10-009 — 5.3 Network Troubleshooting"),
    dict(dominio="redes_ip", patron="Dispositivo nuevo conectado a la red recibe una IP en el rango 169.254.x.x",
         causa_probable="No pudo contactar a un servidor DHCP (pool agotado, servidor caído, o problema de VLAN)",
         recomendacion="Verificar disponibilidad del servidor DHCP y espacio libre en su ámbito antes de revisar el dispositivo mismo",
         fuente="CompTIA Network+ N10-009 — 5.3 Network Troubleshooting"),
    dict(dominio="wan", patron="Aplicación crítica (voz, video) con cortes mientras la velocidad medida de internet es buena",
         causa_probable="Jitter o pérdida de paquetes puntual, no falta de ancho de banda total",
         recomendacion="Medir jitter y pérdida de paquetes específicamente, no solo velocidad de descarga/subida",
         fuente="CompTIA Network+ N10-009 — 5.4 Network Troubleshooting"),

    # ══════ A+ CORE 2 220-1202 — 2.0 SEGURIDAD (síntomas y causas) ══════
    dict(dominio="seguridad_endpoint", patron="CPU al 100% de forma constante sin ningún proceso pesado visible en el administrador de tareas",
         causa_probable="Cryptominer o malware sin archivo (fileless) ejecutándose en memoria/PowerShell",
         recomendacion="Usar una herramienta de detección de comportamiento (no solo escaneo de archivos) y revisar procesos de PowerShell/WMI activos",
         fuente="CompTIA A+ Core 2 220-1202 — 2.4 Security"),
    dict(dominio="seguridad_endpoint", patron="El equipo se reinfecta poco después de haberse limpiado de malware",
         causa_probable="No se deshabilitó System Restore antes de remediar, el malware volvió desde un punto de restauración guardado",
         recomendacion="Deshabilitar System Restore, remediar de nuevo, y solo entonces rehabilitarlo con un punto limpio",
         fuente="CompTIA A+ Core 2 220-1202 — 2.6 Security"),
    dict(dominio="seguridad_endpoint", patron="Archivos con extensión desconocida y una nota de rescate en el escritorio o carpetas",
         causa_probable="Infección de ransomware activa o reciente",
         recomendacion="Aislar el equipo de la red inmediatamente (desconectar cable/WiFi), NO pagar el rescate, restaurar desde el backup más reciente verificado",
         fuente="CompTIA A+ Core 2 220-1202 — 2.6 Security"),
    dict(dominio="seguridad_endpoint", patron="Un usuario no puede escribir en una carpeta compartida aunque el administrador confirma que le dio permiso total",
         causa_probable="Los permisos NTFS de la carpeta son más restrictivos que los del recurso compartido (share), y el más restrictivo gana",
         recomendacion="Revisar ambas capas de permisos (share y NTFS) por separado -- casi siempre una quedó más restrictiva que la otra",
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Security"),
    dict(dominio="seguridad_endpoint", patron="Archivos cifrados con EFS quedan inaccesibles tras resetear la contraseña o reconstruir el perfil de un usuario",
         causa_probable="El certificado de cifrado EFS no se exportó/respaldó antes del reseteo, y estaba ligado a la cuenta anterior",
         recomendacion="Siempre exportar el certificado EFS del usuario ANTES de resetear su contraseña o reconstruir su perfil",
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Security"),
    dict(dominio="seguridad", patron="Un empleado reporta haber dado una contraseña por teléfono a alguien que sonaba como soporte técnico interno",
         causa_probable="Ataque de vishing/pretexting -- ingeniería social por voz, no una falla técnica",
         recomendacion="Cambiar esa credencial de inmediato y reforzar capacitación -- no hay solución de software que prevenga esto por sí sola",
         fuente="CompTIA A+ Core 2 220-1202 — 2.5 Security"),
    dict(dominio="seguridad", patron="Un router o AP recién instalado sigue usando el usuario/contraseña de fábrica",
         causa_probable="Paso de endurecimiento básico omitido durante la instalación",
         recomendacion="Cambiar credenciales por defecto de inmediato -- es el hallazgo de seguridad más común y más crítico en instalaciones apuradas",
         fuente="CompTIA A+ Core 2 220-1202 — 2.10 Security"),
    dict(dominio="dispositivos_moviles", patron="Un dispositivo móvil corporativo se pierde o es robado y no tiene MDM configurado",
         causa_probable="Falta de gestión de dispositivos móviles (MDM) implementada preventivamente",
         recomendacion="Sin MDM no hay borrado remoto posible -- documentar como brecha de datos potencial y priorizar MDM en todos los dispositivos restantes",
         fuente="CompTIA A+ Core 2 220-1202 — 2.8 Security"),

    # ══════ A+ CORE 2 220-1202 — 1.0 / 3.0 SISTEMAS OPERATIVOS Y TROUBLESHOOTING ══════
    dict(dominio="sistemas_operativos", patron="Un equipo Windows no tiene la opción de BitLocker ni de unirse a un dominio en el menú",
         causa_probable="La edición instalada es Windows Home, que no incluye BitLocker, Group Policy Editor ni unión a dominio",
         recomendacion="Verificar la edición de Windows antes de sospechar de una falla de configuración o de red",
         fuente="CompTIA A+ Core 2 220-1202 — 1.3 Operating Systems"),
    dict(dominio="sistemas_operativos", patron="Una política de grupo (GPO) configurada correctamente no se aplica a un equipo específico",
         causa_probable="El equipo no está en la OU correcta de Active Directory, o el GPO está vinculado a la OU equivocada",
         recomendacion="Correr gpresult /r en ese equipo para ver qué políticas llegaron realmente, antes de reconfigurar el GPO de nuevo",
         fuente="CompTIA A+ Core 2 220-1202 — 2.2 Operating Systems"),
    dict(dominio="sistemas_operativos", patron="Una aplicación deja de funcionar sin ningún mensaje de error visible al usuario",
         causa_probable="Fallo registrado a nivel de sistema, no visible en la interfaz de la aplicación",
         recomendacion="Revisar el Visor de Eventos de Windows primero -- casi siempre hay un registro del motivo real antes de reinstalar a ciegas",
         fuente="CompTIA A+ Core 2 220-1202 — 1.4 Operating Systems"),
    dict(dominio="sistemas_operativos", patron="Windows falla repetidamente al instalar una actualización acumulativa",
         causa_probable="Espacio en disco insuficiente o componente WinSxS corrupto",
         recomendacion="Verificar espacio libre en disco y correr sfc /scannow / DISM antes de reintentar la actualización repetidamente sin diagnóstico",
         fuente="CompTIA A+ Core 2 220-1202 — 1.6 Operating Systems"),
    dict(dominio="sistemas_operativos", patron="Windows muestra pantalla azul (BSOD) justo después de instalar una actualización o controlador reciente",
         causa_probable="Incompatibilidad del controlador/actualización reciente con el hardware o software instalado",
         recomendacion="Arrancar en modo seguro y desinstalar el controlador/actualización más reciente antes de investigar otras causas de hardware",
         fuente="CompTIA A+ Core 2 220-1202 — 3.1 Software Troubleshooting"),
    dict(dominio="sistemas_operativos", patron="Un servicio de Windows que funcionaba bien no vuelve a iniciar tras un reinicio o corte de energía",
         causa_probable="El servicio quedó en estado de inicio 'Manual' o 'Deshabilitado' tras el corte, en vez de 'Automático'",
         recomendacion="Verificar el tipo de inicio del servicio en services.msc antes de sospechar de corrupción de archivos del servicio",
         fuente="CompTIA A+ Core 2 220-1202 — 3.1 Software Troubleshooting"),
    dict(dominio="dispositivos_moviles", patron="Un dispositivo móvil no logra autenticarse en una red WiFi corporativa que antes sí funcionaba",
         causa_probable="Certificado de red o perfil WiFi corrupto/vencido en el dispositivo",
         recomendacion="Olvidar y volver a configurar el perfil de red en el dispositivo antes de sospechar del AP o del servidor RADIUS",
         fuente="CompTIA A+ Core 2 220-1202 — 3.2 Software Troubleshooting"),
    dict(dominio="dispositivos_moviles", patron="La batería de un dispositivo móvil corporativo se agota mucho más rápido de lo normal",
         causa_probable="Aplicaciones en segundo plano sin restricción o el GPS/ubicación siempre activo",
         recomendacion="Revisar uso de batería por app antes de asumir que la batería física está degradada",
         fuente="CompTIA A+ Core 2 220-1202 — 3.2 Software Troubleshooting"),

    # ══════ A+ CORE 2 220-1202 — 4.0 PROCEDIMIENTOS OPERATIVOS ══════
    dict(dominio="backup", patron="Todos los backups de un sitio están guardados en un disco dentro del mismo cuarto que el servidor",
         causa_probable="Violación de la regla 3-2-1 -- falta la copia offsite",
         recomendacion="Configurar al menos una copia de backup fuera del sitio (nube o ubicación física distinta) antes de considerar el esquema completo",
         fuente="CompTIA A+ Core 2 220-1202 — 4.3 Operational Procedures"),
    dict(dominio="acceso_remoto", patron="El puerto de Escritorio Remoto (3389) de un servidor está expuesto directamente a internet",
         causa_probable="Configuración de acceso remoto sin VPN de por medio",
         recomendacion="Cerrar la exposición directa de RDP a internet y requerir VPN antes de permitir el acceso remoto -- es un vector de ataque automatizado constante",
         fuente="CompTIA A+ Core 2 220-1202 — 4.9 Operational Procedures"),

    # ══════ SECURITY+ SY0-701 — REGLAS DIAGNÓSTICAS (síntomas y causas) ══════
    dict(dominio="siem_analisis", patron="El mismo usuario aparece autenticado desde dos ubicaciones geográficamente imposibles en poco tiempo",
         causa_probable="Credencial comprometida (impossible travel), no un error de geolocalización",
         recomendacion="Revocar todas las sesiones activas de esa cuenta y forzar cambio de credencial de inmediato -- una de las señales más confiables de compromiso",
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="siem_analisis", patron="Muchas cuentas distintas registran exactamente un intento fallido de inicio de sesión cada una en poco tiempo",
         causa_probable="Ataque de password spraying -- diseñado para evadir el bloqueo por intentos fallidos de cuenta individual",
         recomendacion="Correlacionar intentos fallidos AGREGADOS entre cuentas, no solo por cuenta individual, y forzar cambio de contraseñas comunes/débiles",
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="seguridad_endpoint", patron="Un malware se propaga a otros equipos de la red sin que ningún usuario haya abierto un archivo o adjunto",
         causa_probable="Worm (gusano) autopropagándose por la red, no un virus que requiere acción del usuario",
         recomendacion="Segmentar/aislar la red inmediatamente -- la respuesta a un worm es contención de red, no solo capacitación de usuarios",
         fuente="CompTIA Security+ SY0-701 — 2.4 Threats, Vulnerabilities, and Mitigations"),
    dict(dominio="respuesta_incidentes", patron="Un incidente de seguridad se cierra y resuelve sin ninguna sesión de revisión posterior",
         causa_probable="Fase de 'lecciones aprendidas' omitida por presión de tiempo",
         recomendacion="Agendar una revisión formal aunque sea breve -- sin esa fase el mismo tipo de incidente tiende a repetirse por la misma causa raíz no corregida",
         fuente="CompTIA Security+ SY0-701 — 4.8 Security Operations"),
    dict(dominio="control_acceso", patron="Una cuenta de administrador de dominio se usa rutinariamente para tareas diarias que no requieren privilegio elevado",
         causa_probable="Falta de esquema PAM/just-in-time -- privilegio permanente en vez de temporal",
         recomendacion="Migrar a permisos just-in-time que expiren automáticamente, reservando la cuenta privilegiada solo para cuando realmente se necesite",
         fuente="CompTIA Security+ SY0-701 — 4.6 Security Operations"),
    dict(dominio="gestion_vulnerabilidades", patron="Un sistema ICS/SCADA o controlador biométrico antiguo no puede parcharse sin detener la operación",
         causa_probable="Limitación real del equipo/fabricante, no negligencia de mantenimiento",
         recomendacion="Aplicar un control compensatorio (aislamiento en VLAN dedicada, sin acceso directo a internet ni sistemas administrativos) en vez de dejarlo expuesto sin parche ni mitigación",
         fuente="CompTIA Security+ SY0-701 — 4.1 Security Operations"),
    dict(dominio="gestion_riesgo", patron="Un cliente decide no remediar una vulnerabilidad de bajo impacto real por costo o complejidad",
         causa_probable="Decisión de negocio válida de aceptación de riesgo, no un hallazgo ignorado",
         recomendacion="Documentar formalmente como aceptación de riesgo con exención (dueño, fecha, justificación) -- no dejarlo como un hallazgo abierto sin decisión registrada",
         fuente="CompTIA Security+ SY0-701 — 5.2 Security Program Management and Oversight"),

    # ══════ SERVER+ SK0-005 — REGLAS DIAGNÓSTICAS ══════
    dict(dominio="almacenamiento", patron="Un cliente asume que no necesita backups porque tiene RAID 5 configurado",
         causa_probable="Malentendido sobre qué protege RAID -- solo falla física de disco, no borrado/ransomware/corrupción lógica",
         recomendacion="Aclarar la diferencia y establecer un esquema de backup real independiente del RAID antes de que ocurra un incidente",
         fuente="CompTIA Server+ SK0-005 — 1.2 Server Hardware Installation and Management"),
    dict(dominio="almacenamiento", patron="Un disco de más de 2TB no se puede inicializar completamente en un servidor Windows",
         causa_probable="El disco está particionado como MBR, que tiene un límite de 2TB",
         recomendacion="Reconvertir el esquema de partición a GPT -- no es una falla física del disco",
         fuente="CompTIA Server+ SK0-005 — 2.1 Server Administration"),
    dict(dominio="virtualizacion", patron="Una máquina virtual tiene salida a internet pero no es alcanzable desde otros equipos de la red",
         causa_probable="El adaptador de red de la VM está en modo NAT en vez de bridged",
         recomendacion="Cambiar el adaptador de red a modo bridged si la VM necesita ser alcanzable directamente desde la red física",
         fuente="CompTIA Server+ SK0-005 — 2.5 Server Administration"),
    dict(dominio="servidor_administracion", patron="Un failover de clúster se dispara sin que el nodo activo realmente haya dejado de funcionar",
         causa_probable="El canal de heartbeat entre nodos se interrumpió (problema de red), no una falla real del nodo activo",
         recomendacion="Revisar específicamente la conectividad del enlace de heartbeat antes de asumir que el nodo activo falló",
         fuente="CompTIA Server+ SK0-005 — 2.4 Server Administration"),
    dict(dominio="servidor_administracion", patron="Escalar núcleos de CPU o instancias virtuales en un servidor con licenciamiento per-core/per-socket",
         causa_probable="Riesgo de incumplimiento de licencia si no se ajusta el licenciamiento al mismo tiempo que el hardware",
         recomendacion="Verificar y ajustar el modelo de licencia ANTES de escalar hardware, no descubrirlo en una auditoría posterior",
         fuente="CompTIA Server+ SK0-005 — 2.8 Server Administration"),
    dict(dominio="almacenamiento", patron="Un arreglo RAID 5 está en proceso de reconstrucción (rebuild) tras reemplazar un disco fallado",
         causa_probable="Estado normal de recuperación, pero el arreglo queda temporalmente SIN redundancia durante el proceso",
         recomendacion="Tratar el sistema como de alto riesgo durante el rebuild -- un segundo fallo de disco en esa ventana pierde el arreglo completo",
         fuente="CompTIA Server+ SK0-005 — 4.3 Troubleshooting"),
    dict(dominio="servidor_administracion", patron="Fallas de autenticación de dominio intermitentes en un servidor sin cambio de credenciales ni política",
         causa_probable="Desincronización de reloj (clock skew) -- Kerberos rechaza autenticaciones fuera del umbral de tiempo permitido",
         recomendacion="Verificar la hora del sistema contra un servidor NTP confiable antes de investigar causas más complejas",
         fuente="CompTIA Server+ SK0-005 — 4.4 Troubleshooting"),
    dict(dominio="servidor_administracion", patron="Un servidor Windows Core no tiene interfaz gráfica de escritorio disponible",
         causa_probable="Comportamiento esperado de esa instalación -- Server Core se instala deliberadamente sin GUI",
         recomendacion="Administrar remotamente vía PowerShell/RSAT en vez de buscar cómo habilitar una interfaz gráfica que no está instalada por diseño",
         fuente="CompTIA Server+ SK0-005 — 2.1 Server Administration"),

    # ══════ CySA+ CS0-003 — REGLAS DIAGNÓSTICAS ══════
    dict(dominio="siem_analisis", patron="Un equipo envía tráfico saliente pequeño pero a intervalos muy regulares hacia la misma IP externa",
         causa_probable="Beaconing -- malware con C2 'llamando a casa' periódicamente",
         recomendacion="Aislar el equipo y analizar la IP destino en herramientas de reputación (WHOIS/AbuseIPDB) antes de descartarlo como tráfico normal",
         fuente="CompTIA CySA+ CS0-003 — 1.2 Security Operations"),
    dict(dominio="gestion_vulnerabilidades", patron="Un escaneo de vulnerabilidades no credenciado reporta un sistema como de bajo riesgo",
         causa_probable="El escaneo no credenciado solo ve lo expuesto externamente, subestimando el riesgo real interno",
         recomendacion="Repetir el escaneo en modo credenciado antes de confiar en una evaluación de bajo riesgo basada solo en vista externa",
         fuente="CompTIA CySA+ CS0-003 — 2.1 Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", patron="Un sistema ICS/SCADA se cae o se comporta erráticamente durante un escaneo de vulnerabilidades",
         causa_probable="Escaneo activo agresivo no tolerado por el equipo de infraestructura crítica",
         recomendacion="Usar escaneo pasivo en sistemas OT/ICS/SCADA, o confirmar con el fabricante que el equipo tolera escaneo activo antes de repetirlo",
         fuente="CompTIA CySA+ CS0-003 — 2.1 Vulnerability Management"),
    dict(dominio="gestion_vulnerabilidades", patron="Cambiar un número de ID en la URL de un sistema de reservas permite ver datos de otro huésped",
         causa_probable="Broken access control -- la aplicación no verifica permiso del usuario sobre el recurso solicitado",
         recomendacion="Reportar como hallazgo crítico al desarrollador del sistema -- requiere corrección en la lógica de autorización, no configuración de red",
         fuente="CompTIA CySA+ CS0-003 — 2.4 Vulnerability Management"),
    dict(dominio="respuesta_incidentes", patron="Un sistema comprometido se 'limpia' de malware pero se reconecta sin reinstalación completa",
         causa_probable="Confianza indebida en que el antivirus eliminó toda persistencia del atacante (ej. cuentas de puerta trasera no detectadas)",
         recomendacion="Re-imaging completo (reinstalar desde cero) en vez de solo limpiar -- no se puede confiar en un sistema que estuvo bajo control de un atacante",
         fuente="CompTIA CySA+ CS0-003 — 3.2 Incident Response and Management"),
    dict(dominio="reportes_comunicacion", patron="Una vulnerabilidad lleva mucho tiempo abierta sin remediar y sin explicación documentada",
         causa_probable="Inhibidor de remediación real (sistema legacy/propietario) nunca se documentó formalmente como excepción",
         recomendacion="Documentar el inhibidor específico con dueño y control compensatorio aplicado, en vez de dejarlo como una tarea pendiente sin contexto",
         fuente="CompTIA CySA+ CS0-003 — 4.1 Reporting and Communication"),
    dict(dominio="reportes_comunicacion", patron="Un incidente se detecta rápido pero la respuesta/resolución tarda mucho más de lo esperado",
         causa_probable="Buen MTTD (detección) pero mal MTTR (respuesta) -- el cuello de botella está en el proceso, no en el monitoreo",
         recomendacion="Enfocar la mejora en el proceso de escalamiento y ejecución de respuesta, no en agregar más monitoreo que ya funciona bien",
         fuente="CompTIA CySA+ CS0-003 — 4.2 Reporting and Communication"),
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
    "sistemas_operativos":      ("srv", "servidor", "laptop", "notebook", "workstation"),
    "dispositivos_moviles":     ("tablet", "celular", "móvil", "movil", "smartphone"),
}


def _matching_domains(entity_names: list[str], strict: bool = False) -> set[str]:
    """`strict=True` no aplica el fallback a 'metodologia' -- pensado para
    texto libre de chat (7 sep 2026), donde un saludo o pregunta no técnica
    no debe inyectar conocimiento igual (costo de tokens desperdiciado). El
    fallback default (strict=False) sigue igual para cerebro: un cluster de
    equipos siempre es una situación técnica real, así que algo genérico es
    mejor que nada."""
    texto = " | ".join((n or "").lower() for n in entity_names)
    dominios_match = {
        dominio for dominio, kws in _DOMAIN_KEYWORDS.items()
        if any(kw in texto for kw in kws)
    }
    if strict:
        return dominios_match
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


def find_relevant(entity_names: list[str], max_reglas: int = 6, max_teoria: int = 4,
                   strict: bool = False) -> tuple[list[dict], list[dict]]:
    """Reglas + teoría relevante para un grupo de entidades, por nombre.
    Determinístico (coincidencia de palabra clave), nunca decidido por el LLM."""
    dominios_match = _matching_domains(entity_names, strict=strict)
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


def format_for_prompt(entity_names: list[str], strict: bool = False) -> str:
    """Bloque de texto compacto para inyectar en el prompt del cerebro --
    solo lo relevante a las entidades del cluster actual, no las 212 enteras."""
    reglas, teoria = find_relevant(entity_names, strict=strict)
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
