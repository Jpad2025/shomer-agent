FROM python:3.11-slim-bookworm

# Herramientas de red necesarias para los drivers
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    sshpass \
    iputils-ping \
    snmp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 14 sep 2026: se quita el paso que generaba MANUAL_CAMPO_AGENTE.md en build
# concatenando TECNICO_OPERACION.md + SOPORTE_TECNICO.md -- ese archivo
# horneado en la imagen quedaba desincronizado de los fuentes en cuanto
# alguien los editaba, porque el deploy normal (fleet_sync.sh) solo reinicia
# el contenedor, nunca reconstruye la imagen. Verificado en Ópera: la imagen
# llevaba desde el 20 de junio sin reconstruirse y el bot seguía respondiendo
# con contenido de esa fecha. Ahora groq_helper.py lee TECNICO_OPERACION.md +
# SOPORTE_TECNICO.md en vivo (docker-compose los monta como volumen), con
# cache de 30 min -- ver docstring de core/groq_helper.py.

# El volumen /app/data persiste devices.json entre reinicios
VOLUME ["/app/data"]

CMD ["python", "main.py"]
