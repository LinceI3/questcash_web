#!/usr/bin/env bash
# Restauración de un respaldo de QuestCash.
#
#   scripts/restaurar.sh --verificar              # restaura en una base
#                                                 # desechable y comprueba que
#                                                 # el contenido está completo
#   scripts/restaurar.sh --a questcash_copia AR   # restaura en la base indicada
#
# El modo --verificar es el que convierte el RTO de 4 horas en un número real
# en vez de una intención: prueba de extremo a extremo que el último respaldo
# se puede restaurar y que lo restaurado tiene sentido, sin tocar producción.
set -euo pipefail

CONTENEDOR_DB="${CONTENEDOR_DB:-questcash_db}"
DESTINO="${DESTINO:-./respaldos}"
: "${POSTGRES_USER:?define POSTGRES_USER}"

MODO="${1:---verificar}"

if [ "$MODO" = "--verificar" ]; then
    BASE_PRUEBA="questcash_verificacion_$(date +%s)"
    ARCHIVO="${2:-$(ls -1t "$DESTINO"/questcash-*.sql.gz* 2>/dev/null | head -1)}"
elif [ "$MODO" = "--a" ]; then
    BASE_PRUEBA="${2:?falta el nombre de la base}"
    ARCHIVO="${3:?falta el archivo de respaldo}"
else
    echo "Uso: $0 [--verificar [archivo] | --a <base> <archivo>]" >&2
    exit 2
fi

[ -n "${ARCHIVO:-}" ] && [ -f "$ARCHIVO" ] || { echo "No hay respaldo que restaurar" >&2; exit 1; }
echo "Restaurando $ARCHIVO -> $BASE_PRUEBA"

descomprimir() {
    case "$ARCHIVO" in
        *.gpg) gpg --batch --quiet --decrypt --passphrase "${RESPALDO_CLAVE_GPG:?el respaldo está cifrado: define RESPALDO_CLAVE_GPG}" "$ARCHIVO" | gunzip ;;
        *.gz)  gunzip -c "$ARCHIVO" ;;
        *)     cat "$ARCHIVO" ;;
    esac
}

docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $BASE_PRUEBA;" >/dev/null
docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $BASE_PRUEBA;" >/dev/null
descomprimir | docker exec -i "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d "$BASE_PRUEBA" -q >/dev/null

echo
echo "Contenido restaurado:"
docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d "$BASE_PRUEBA" -tA -c "
  SELECT '  usuarios     : ' || count(*) FROM usuarios;
  SELECT '  metas        : ' || count(*) FROM quests;
  SELECT '  movimientos  : ' || count(*) FROM movimientos;
  SELECT '  gastos       : ' || count(*) FROM gastos;
  SELECT '  revisión     : ' || coalesce(max(version_num),'(ninguna)') FROM alembic_version;"

echo
echo "Comprobaciones de integridad:"
CIFRADOS=$(docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d "$BASE_PRUEBA" -tA -c \
  "SELECT count(*) FROM usuarios WHERE correo LIKE 'qc1:%';" | tr -d ' ')
EN_CLARO=$(docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d "$BASE_PRUEBA" -tA -c \
  "SELECT count(*) FROM usuarios WHERE correo LIKE '%@%';" | tr -d ' ')
echo "  correos cifrados en el respaldo : $CIFRADOS"
echo "  correos en claro en el respaldo : $EN_CLARO  (debe ser 0)"

DESCUADRE=$(docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d "$BASE_PRUEBA" -tA -c "
  SELECT count(*) FROM quests q WHERE abs(q.monto_actual - coalesce(
    (SELECT sum(CASE WHEN m.tipo='aporte' THEN m.monto ELSE -m.monto END)
     FROM movimientos m WHERE m.quest_id=q.id), 0)) > 0.001
    AND EXISTS (SELECT 1 FROM movimientos m WHERE m.quest_id=q.id);" | tr -d ' ')
echo "  metas con saldo descuadrado     : $DESCUADRE"

if [ "$MODO" = "--verificar" ]; then
    docker exec "$CONTENEDOR_DB" psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE $BASE_PRUEBA;" >/dev/null
    echo
    echo "Base de verificación eliminada."
fi

[ "$EN_CLARO" = "0" ] || { echo "FALLO: el respaldo contiene correos en claro" >&2; exit 1; }
echo
echo "RESTAURACIÓN VERIFICADA — $(date +%Y-%m-%d)"
