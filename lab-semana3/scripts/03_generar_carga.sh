#!/usr/bin/env bash
# =====================================================================
#  PRUEBA 3 — Generar carga real para que el monitoreo tenga que mostrar
#
#  Netdata en reposo enseña graficas planas y eso no sirve como
#  evidencia. Este script mete trafico sostenido durante N segundos
#  para que las graficas de CPU, red y contenedores se muevan de verdad.
#
#  MIENTRAS CORRE: abre http://localhost:19999 y toma las capturas.
# =====================================================================
set -u
cd "$(dirname "$0")/../.." || exit 1

BASE="http://localhost:8080"
RUTA="${RUTA:-/login}"
SEGUNDOS="${SEGUNDOS:-120}"
CONCURRENCIA="${CONCURRENCIA:-8}"
OUT="lab-semana3/evidencia"
mkdir -p "$OUT"

echo "======================================================================"
echo " Generando carga durante ${SEGUNDOS}s con ${CONCURRENCIA} clientes"
echo " ABRE AHORA http://localhost:19999 y toma las capturas del panel."
echo "======================================================================"
echo

fin=$(( $(date +%s) + SEGUNDOS ))
for c in $(seq 1 "$CONCURRENCIA"); do
  (
    n=0
    while [ "$(date +%s)" -lt "$fin" ]; do
      curl -s -o /dev/null -m 5 "$BASE$RUTA"
      n=$((n+1))
    done
    echo "$n" >> /tmp/qc_carga_conteo.txt
  ) &
done

: > /tmp/qc_carga_conteo.txt
while [ "$(date +%s)" -lt "$fin" ]; do
  restante=$(( fin - $(date +%s) ))
  printf "\r   quedan %3ds ..." "$restante"
  sleep 5
done
wait
echo
echo

total=$(awk '{s+=$1} END{print s+0}' /tmp/qc_carga_conteo.txt 2>/dev/null)
{
  echo "======================================================================"
  echo " PRUEBA 3 — Carga sostenida para el monitoreo"
  echo " Fecha        : $(date)"
  echo " Duracion     : ${SEGUNDOS}s"
  echo " Concurrencia : ${CONCURRENCIA} clientes simultaneos"
  echo " Peticiones   : ${total}"
  if [ "$SEGUNDOS" -gt 0 ]; then
    echo " Throughput   : $(awk -v t="$total" -v s="$SEGUNDOS" 'BEGIN{printf "%.1f", t/s}') req/s"
  fi
  echo "======================================================================"
  echo
  echo "--- Estado de Nginx (stub_status) ---"
  docker exec qc_lb curl -s http://127.0.0.1/nginx_status 2>/dev/null
  echo
  echo "--- Uso de recursos por contenedor (docker stats) ---"
  docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" 2>/dev/null
  echo
  echo "--- Reparto acumulado en el log de Nginx ---"
  docker exec qc_lb sh -c "grep -o 'upstream=[0-9.]*:[0-9]*' /var/log/nginx/access.log | sort | uniq -c | sort -rn" 2>/dev/null
} 2>&1 | tee "$OUT/03_carga.txt"

echo
echo "Evidencia guardada en $OUT/03_carga.txt"
