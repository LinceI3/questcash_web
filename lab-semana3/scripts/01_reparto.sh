#!/usr/bin/env bash
# =====================================================================
#  PRUEBA 1 — ¿El balanceador realmente reparte el trafico?
#
#  Manda N peticiones al balanceador y cuenta cuantas atendio cada
#  instancia, leyendo la cabecera X-Served-By que agrega Nginx.
# =====================================================================
set -u
cd "$(dirname "$0")/../.." || exit 1

BASE="http://localhost:8080"
RUTA="${RUTA:-/login}"
N="${N:-200}"
OUT="lab-semana3/evidencia"
mkdir -p "$OUT"

{
echo "======================================================================"
echo " PRUEBA 1 — Reparto de carga entre las 2 instancias"
echo " Fecha : $(date)"
echo " URL   : $BASE$RUTA"
echo " Total : $N peticiones"
echo "======================================================================"
echo

: > /tmp/qc_reparto.txt
fallos=0

for i in $(seq 1 "$N"); do
  # Una sola peticion: se capturan cabeceras y codigo a la vez.
  code=$(curl -s -o /dev/null -D /tmp/qc_h.txt -w "%{http_code}" "$BASE$RUTA" 2>/dev/null)
  inst=$(tr -d '\r' < /tmp/qc_h.txt | awk 'tolower($1)=="x-served-by:" {print $2}')
  echo "${inst:-desconocido}" >> /tmp/qc_reparto.txt
  case "$code" in
    200|302) ;;
    *) fallos=$((fallos+1)) ;;
  esac
done

echo "Peticiones atendidas por cada instancia (cabecera X-Served-By):"
echo
sort /tmp/qc_reparto.txt | uniq -c | sort -rn \
  | awk -v n="$N" '{printf "   %-26s %5d peticiones  (%5.1f %%)\n", $2, $1, ($1*100)/n}'
echo
echo "Peticiones con error: $fallos de $N"
echo
echo "Interpretacion: con round-robin se espera un reparto cercano al 50/50."
echo "Las direcciones IP corresponden a los contenedores qc_api1 y qc_api2"
echo "dentro de la red interna de Docker (ver equivalencia abajo)."
echo

echo "----------------------------------------------------------------------"
echo " Equivalencia IP -> contenedor"
echo "----------------------------------------------------------------------"
for c in qc_api1 qc_api2; do
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$c" 2>/dev/null)
  printf "   %-10s -> %s:5000\n" "$c" "$ip"
done

echo
echo "----------------------------------------------------------------------"
echo " Muestra del log de Nginx (campo upstream = instancia que respondio)"
echo "----------------------------------------------------------------------"
docker exec qc_lb tail -n 10 /var/log/nginx/access.log 2>/dev/null

} 2>&1 | tee "$OUT/01_reparto.txt"

echo
echo "Evidencia guardada en $OUT/01_reparto.txt"
