FROM python:3.10

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y netcat-openbsd && \
    pip install --no-cache-dir -r requirements.txt
COPY . .

ENV FLASK_APP=app.py

EXPOSE 5000

CMD ["sh", "wait-for-db.sh"]