#!/usr/bin/env bash
# =====================================================================
#  Levanta el laboratorio y espera a que el balanceador responda.
#  Ejecutar desde la RAIZ del proyecto (questcash_web/).
# =====================================================================
set -u
cd "$(dirname "$0")/../.." || exit 1

COMPOSE="docker compose -f docker-compose.lab.yml"
BASE="http://localhost:8080"
OUT="lab-semana3/evidencia"
mkdir -p "$OUT"

# ---------------------------------------------------------------------
#  Chequeo previo: data/raw/ pesa ~750 MB de CSVs del ENIGH que la app
#  NO necesita en tiempo de ejecucion (solo usa data/processed/).
#  Si no se excluye, Docker los copia a la imagen y la build tarda
#  eternidades. Se agrega al .dockerignore si falta.
# ---------------------------------------------------------------------
if [ -d data/raw ] && ! grep -q "^data/raw" .dockerignore 2>/dev/null; then
  echo "==> Excluyendo data/raw/ del contexto de Docker (~750 MB innecesarios)"
  printf '\n# CSVs crudos del ENIGH: no se usan en runtime\ndata/raw/\n' >> .dockerignore
fi

echo "==> Construyendo y levantando el laboratorio..."
$COMPOSE up -d --build 2>&1 | tail -20

echo
echo "==> Esperando a que el balanceador responda (max 120s)..."
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/lb-health" 2>/dev/null)
  if [ "$code" = "200" ]; then
    echo "    Balanceador vivo tras ${i}0s aprox."
    break
  fi
  sleep 2
done

echo
echo "==> Esperando a que AMBAS instancias respondan (max 120s)..."
for i in $(seq 1 60); do
  a=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/login" 2>/dev/null)
  if [ "$a" = "200" ] || [ "$a" = "302" ]; then
    echo "    La aplicacion responde (HTTP $a)."
    break
  fi
  sleep 2
done

echo
echo "==> Estado de los contenedores"
$COMPOSE ps | tee "$OUT/00_estado_contenedores.txt"

echo
echo "==> Topologia del upstream declarada en Nginx"
docker exec qc_lb nginx -T 2>/dev/null | sed -n '/upstream questcash_api/,/}/p' \
  | tee "$OUT/00_upstream.txt"

echo
echo "Listo."
echo "  Aplicacion : $BASE/login"
echo "  Netdata    : http://localhost:19999"
echo
echo "Siguiente paso:  bash lab-semana3/scripts/01_reparto.sh"
