#!/usr/bin/env bash
# =====================================================================
#  PRUEBA 2 — Tolerancia a fallas (la prueba central del entregable)
#
#  Se manda una racha continua de peticiones al balanceador. A la mitad
#  de la racha se APAGA una de las dos instancias. El sitio debe seguir
#  respondiendo: la instancia sobreviviente absorbe todo el trafico.
#
#  Al final se vuelve a encender y se comprueba que el balanceador la
#  reincorpora sola.
# =====================================================================
set -u
cd "$(dirname "$0")/../.." || exit 1

BASE="http://localhost:8080"
RUTA="${RUTA:-/login}"
VICTIMA="${VICTIMA:-qc_api2}"
DURACION="${DURACION:-45}"     # segundos totales de la racha
OUT="lab-semana3/evidencia"
mkdir -p "$OUT"
LOG="/tmp/qc_failover_timeline.txt"

{
echo "======================================================================"
echo " PRUEBA 2 — Failover: se apaga una instancia con trafico en vivo"
echo " Fecha        : $(date)"
echo " URL          : $BASE$RUTA"
echo " Instancia a apagar : $VICTIMA"
echo " Duracion     : ${DURACION}s (1 peticion cada 0.5s aprox.)"
echo "======================================================================"
echo

: > "$LOG"

# ---------------------------------------------------------------------
#  Racha de peticiones en segundo plano. Cada linea del timeline lleva
#  hora, codigo HTTP y la instancia que atendio.
# ---------------------------------------------------------------------
(
  fin=$(( $(date +%s) + DURACION ))
  while [ "$(date +%s)" -lt "$fin" ]; do
    code=$(curl -s -m 5 -o /dev/null -D /tmp/qc_h2.txt -w "%{http_code}" "$BASE$RUTA" 2>/dev/null)
    inst=$(tr -d '\r' < /tmp/qc_h2.txt 2>/dev/null | awk 'tolower($1)=="x-served-by:" {print $2}')
    printf "%s  HTTP=%s  instancia=%s\n" "$(date +%H:%M:%S)" "${code:-000}" "${inst:-sin_respuesta}" >> "$LOG"
    sleep 0.5
  done
) &
RACHA=$!

sleep $(( DURACION / 3 ))
echo ">>> $(date +%H:%M:%S)  APAGANDO $VICTIMA ..." | tee -a "$LOG"
docker stop "$VICTIMA" >/dev/null 2>&1
echo ">>> $(date +%H:%M:%S)  $VICTIMA detenida." | tee -a "$LOG"
echo

sleep $(( DURACION / 3 ))
echo ">>> $(date +%H:%M:%S)  ENCENDIENDO $VICTIMA de nuevo ..." | tee -a "$LOG"
docker start "$VICTIMA" >/dev/null 2>&1
echo ">>> $(date +%H:%M:%S)  $VICTIMA levantada." | tee -a "$LOG"

wait $RACHA

echo
echo "----------------------------------------------------------------------"
echo " LINEA DE TIEMPO COMPLETA"
echo "----------------------------------------------------------------------"
cat "$LOG"

echo
echo "----------------------------------------------------------------------"
echo " RESUMEN"
echo "----------------------------------------------------------------------"
total=$(grep -c "HTTP=" "$LOG")
ok=$(grep -cE "HTTP=(200|302)" "$LOG")
err=$(( total - ok ))
echo "   Peticiones enviadas          : $total"
echo "   Respondidas correctamente    : $ok"
echo "   Fallidas (timeout / 5xx)     : $err"
if [ "$total" -gt 0 ]; then
  echo "   Disponibilidad durante la caida: $(awk -v o="$ok" -v t="$total" 'BEGIN{printf "%.2f %%", (o*100)/t}')"
fi
echo
echo "   Reparto por instancia:"
grep "HTTP=" "$LOG" | awk '{print $NF}' | sed 's/instancia=//' | sort | uniq -c \
  | awk '{printf "      %-26s %4d\n", $2, $1}'

echo
echo "----------------------------------------------------------------------"
echo " Como lo vio Nginx (log de error al detectar la instancia caida)"
echo "----------------------------------------------------------------------"
docker exec qc_lb tail -n 8 /var/log/nginx/error.log 2>/dev/null || echo "   (sin errores registrados)"

echo
echo "----------------------------------------------------------------------"
echo " Estado final de los contenedores"
echo "----------------------------------------------------------------------"
docker compose -f docker-compose.lab.yml ps

} 2>&1 | tee "$OUT/02_failover.txt"

echo
echo "Evidencia guardada en $OUT/02_failover.txt"
