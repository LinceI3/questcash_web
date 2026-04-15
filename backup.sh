#!/bin/bash

echo "Iniciando backup de la base de datos..."

docker exec questcash_db pg_dump -U questcash questcash > backup.sql

echo "Backup completado correctamente"