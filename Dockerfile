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

RUN python3 <<'PY'
from pathlib import Path
c = Path("/app/docs/campo")
tec = c / "TECNICO_OPERACION.md"
sup = c / "SOPORTE_TECNICO.md"
out = c / "MANUAL_CAMPO_AGENTE.md"
if tec.is_file() and sup.is_file():
    merged = (
        "# Shomer Sentinel — Manual único para agente de campo\n\n"
        "> Generado en **build** desde `TECNICO_OPERACION.md` + `SOPORTE_TECNICO.md`.\n\n"
        "---\n\n"
        "## PARTE A — Operación en sitio\n\n"
        + tec.read_text(encoding="utf-8")
        + "\n\n---\n\n"
        "## PARTE B — Soporte e instalación\n\n"
        + sup.read_text(encoding="utf-8")
    )
    out.write_text(merged, encoding="utf-8")
PY

# El volumen /app/data persiste devices.json entre reinicios
VOLUME ["/app/data"]

CMD ["python", "main.py"]
