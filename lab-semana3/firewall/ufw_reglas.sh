#!/usr/bin/env bash
# =====================================================================
#  QuestCash — Semana 3
#  Firewall a nivel de sistema operativo (ufw / iptables)
#
#  IMPORTANTE: este script es para un SERVIDOR LINUX (VM Ubuntu o VPS).
#  macOS no usa ufw, y Docker Desktop corre sobre una VM propia, asi que
#  ufw no aplica ahi. Ver README-firewall.md para el detalle.
#
#  Filosofia: DENEGAR TODO lo entrante por defecto y abrir unicamente
#  lo que el servicio necesita para funcionar. Cada puerto abierto es
#  una puerta mas que alguien puede tocar.
# =====================================================================
set -euo pipefail

if ! command -v ufw >/dev/null 2>&1; then
  echo "ufw no esta instalado. Instalalo con: sudo apt install ufw"
  exit 1
fi

echo "==> Politica por defecto"
# Todo lo que ENTRA se rechaza salvo que una regla lo permita.
sudo ufw default deny incoming
# Todo lo que SALE se permite: el servidor necesita actualizarse,
# resolver DNS y hablar con la base de datos o APIs externas.
sudo ufw default allow outgoing

echo "==> Reglas permitidas"

# --- SSH -------------------------------------------------------------
# Sin esto te quedas fuera de tu propio servidor al activar el firewall.
# Se limita la tasa: ufw bloquea una IP que intente mas de 6 conexiones
# en 30 segundos, lo que frena los ataques de fuerza bruta.
sudo ufw limit 22/tcp comment 'SSH - administracion remota (rate limited)'

# --- HTTP ------------------------------------------------------------
# Necesario para que Let's Encrypt valide el dominio y para redirigir
# a HTTPS. No sirve trafico real de la aplicacion.
sudo ufw allow 80/tcp comment 'HTTP - redireccion a HTTPS y reto ACME'

# --- HTTPS -----------------------------------------------------------
# El puerto por el que entra TODO el trafico real de usuarios.
sudo ufw allow 443/tcp comment 'HTTPS - trafico de la aplicacion'

echo "==> Puertos que NO se abren (a proposito)"
cat <<'TXT'
   5432  PostgreSQL   -> solo accesible desde la red interna de Docker.
                         Exponerlo a internet es el error clasico que
                         termina en base de datos secuestrada.
   5000  Flask/API    -> las instancias solo hablan con Nginx, nunca
                         directo con el exterior.
   8080  Nginx (lab)  -> en produccion el proxy escucha en 80/443.
  19999  Netdata      -> panel de monitoreo. Contiene informacion
                         sensible de la infraestructura; se accede por
                         tunel SSH:  ssh -L 19999:localhost:19999 user@servidor
TXT

echo
echo "==> Activando el firewall"
sudo ufw --force enable

echo
echo "==> Estado final"
sudo ufw status verbose
echo
sudo ufw status numbered
