# Python 3.12: 3.10 llega a fin de soporte en octubre de 2026 y dejaría de
# recibir parches de seguridad. Se elige 3.12 —y no 3.13/3.14— porque es la
# versión más nueva con la que TODAS las dependencias fijadas en
# requirements.txt instalan desde wheel, sin compilar: psycopg2-binary 2.9.9
# no publica wheels para 3.13 ni 3.14.
FROM python:3.12-slim

WORKDIR /app

# netcat-openbsd lo usa wait-for-db.sh para esperar a Postgres.
# curl lo usa el HEALTHCHECK de abajo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Usuario sin privilegios.
#
# Correr como root dentro del contenedor significa que una ejecución de código
# arbitraria empieza siendo root: puede escribir en cualquier ruta de la
# imagen, instalar herramientas y —si el contenedor tiene capacidades de más—
# intentar salir hacia el anfitrión. No cuesta nada evitarlo.
#
# Solo se le da propiedad de lo que necesita escribir: las fotos de perfil.
# El resto del código queda de solo lectura para el proceso.
RUN useradd --system --create-home --shell /usr/sbin/nologin questcash \
    && mkdir -p /app/static/uploads/profiles \
    && chown -R questcash:questcash /app/static/uploads
USER questcash

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# Comprueba que el proceso responde, no que la base esté viva: para eso está
# /ready. Confundirlas hace que el orquestador reinicie la aplicación en bucle
# cuando lo que se cayó fue Postgres.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:5000/health || exit 1

CMD ["sh", "wait-for-db.sh"]
