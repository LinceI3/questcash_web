#!/usr/bin/env bash
# Respaldo de la base de datos de QuestCash.
#
# Sustituye a backup.sh, que era un `pg_dump > backup.sql` en el directorio
# actual: sobrescribía el respaldo anterior en cada ejecución, no se programaba,
# no se cifraba, no salía de la máquina, no tenía retención y nunca se había
# restaurado. Para un producto que guarda el historial financiero de personas,
# la pérdida de datos habría sido total y definitiva.
#
# Uso:
#   scripts/respaldo.sh                    # respaldo con la fecha en el nombre
#   DESTINO=/ruta scripts/respaldo.sh      # dónde dejarlo
#
# Objetivo declarado:  RPO 24 h  /  RTO 4 h
#   RPO: se pierde como mucho un día de datos -> respaldo diario.
#   RTO: se vuelve a estar en pie en 4 horas  -> la restauración debe estar
#        probada y documentada, o el número es una ilusión.
set -euo pipefail

DESTINO="${DESTINO:-./respaldos}"
RETENER_DIARIOS="${RETENER_DIARIOS:-7}"
RETENER_SEMANALES="${RETENER_SEMANALES:-4}"
CONTENEDOR_DB="${CONTENEDOR_DB:-questcash_db}"

: "${POSTGRES_USER:?define POSTGRES_USER (o carga el .env con: set -a; . ./.env; set +a)}"
: "${POSTGRES_DB:?define POSTGRES_DB}"

FECHA="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DESTINO"
ARCHIVO="$DESTINO/questcash-$FECHA.sql.gz"

echo "Respaldando $POSTGRES_DB -> $ARCHIVO"

# --format=plain comprimido con gzip: legible con `gzip -dc` y restaurable con
# sin depender de que la versión de pg_restore coincida.
docker exec "$CONTENEDOR_DB" pg_dump \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --no-owner --no-privileges \
    | gzip -9 > "$ARCHIVO"

# Comprobación mínima: un respaldo vacío o truncado es peor que ninguno,
# porque da falsa tranquilidad.
TAMANO=$(wc -c < "$ARCHIVO" | tr -d ' ')
if [ "$TAMANO" -lt 1024 ]; then
    echo "ERROR: el respaldo pesa $TAMANO bytes. Algo falló." >&2
    rm -f "$ARCHIVO"
    exit 1
fi
if ! gzip -t "$ARCHIVO" 2>/dev/null; then
    echo "ERROR: el archivo está corrupto." >&2
    rm -f "$ARCHIVO"
    exit 1
fi
# `grep -c` y no `grep -q`: con `set -o pipefail`, grep -q sale en cuanto
# encuentra la primera coincidencia y eso manda SIGPIPE a gzip, así que el
# ÉXITO de la búsqueda hacía fallar la tubería y el respaldo bueno se borraba.
TABLAS=$(gzip -dc "$ARCHIVO" | grep -c "CREATE TABLE" || true)
if [ "${TABLAS:-0}" -lt 1 ]; then
    echo "ERROR: el respaldo no contiene el esquema." >&2
    rm -f "$ARCHIVO"
    exit 1
fi

echo "  $(du -h "$ARCHIVO" | cut -f1)  verificado  ($TABLAS tablas)"

# --- Cifrado ---------------------------------------------------------------
# Un volcado contiene los datos personales YA DESCIFRADOS de la columna
# `password_hash` y todos los criptogramas. Guardarlo en claro fuera de la
# base anula buena parte del cifrado en reposo.
if [ -n "${RESPALDO_CLAVE_GPG:-}" ]; then
    gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase "$RESPALDO_CLAVE_GPG" -o "$ARCHIVO.gpg" "$ARCHIVO"
    rm -f "$ARCHIVO"
    ARCHIVO="$ARCHIVO.gpg"
    echo "  cifrado con AES-256"
else
    echo "  AVISO: sin RESPALDO_CLAVE_GPG, el respaldo queda EN CLARO." >&2
    echo "         Aceptable en una máquina de desarrollo; no fuera de ella." >&2
fi

# --- Retención -------------------------------------------------------------
# Sin esto el disco se llena y alguien acaba borrando a mano, que es como se
# pierden los respaldos que sí hacían falta.
cd "$DESTINO"
ls -1t questcash-*.sql.gz* 2>/dev/null | tail -n +"$((RETENER_DIARIOS + 1))" | while read -r viejo; do
    # Se conserva el del lunes de cada semana dentro de la ventana semanal.
    DIA_SEMANA=$(date -j -f "%Y%m%d" "$(echo "$viejo" | sed -E 's/questcash-([0-9]{8}).*/\1/')" +%u 2>/dev/null \
                 || date -d "$(echo "$viejo" | sed -E 's/questcash-([0-9]{8}).*/\1/')" +%u 2>/dev/null || echo 0)
    if [ "$DIA_SEMANA" != "1" ]; then
        rm -f "$viejo" && echo "  retirado por antigüedad: $viejo"
    fi
done

echo
echo "Respaldos guardados: $(ls -1 questcash-*.sql.gz* 2>/dev/null | wc -l | tr -d ' ')"
echo
echo "RECORDATORIO: un respaldo que nunca se ha restaurado no es un respaldo."
echo "Prueba la restauración con scripts/restaurar.sh --verificar"
