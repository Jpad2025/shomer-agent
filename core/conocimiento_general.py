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


init_db()
