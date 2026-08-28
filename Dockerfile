# Python 3.12: 3.10 llega a fin de soporte en octubre de 2026 y dejaría de
# recibir parches de seguridad. Se elige 3.12 —y no 3.13/3.14— porque es la
# versión más nueva con la que TODAS las dependencias fijadas en
# requirements.txt instalan desde wheel, sin compilar: psycopg2-binary 2.9.9
# no publica wheels para 3.13 ni 3.14.
#
# La variante `slim` trae lo mismo sin la cadena de compilación ni las
# herramientas de documentación: la imagen baja de ~1 GB a ~150 MB de base.
FROM python:3.12-slim

WORKDIR /app

# netcat-openbsd lo usa wait-for-db.sh para esperar a Postgres.
RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# No escribir .pyc y no bufferizar la salida: los logs salen en el momento,
# que es lo que espera un recolector de logs cuando corre en un contenedor.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["sh", "wait-for-db.sh"]
