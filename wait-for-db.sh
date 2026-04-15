#!/bin/sh

echo "Esperando a la base de datos..."

while ! nc -z db 5432; do
  sleep 1
done

echo "Base de datos lista 🚀"

python app.py