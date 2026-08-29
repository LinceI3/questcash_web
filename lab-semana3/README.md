# Laboratorio semana 3 — Monitoreo, firewall y balanceo de carga

Este laboratorio monta la arquitectura que pide la semana 3 usando **el código
real de QuestCash**, no una maqueta:

```
        cliente
           |
           v
   [ Nginx :8080 ]   <-- balanceador de carga
        /      \
   [ api1 ]  [ api2 ]  <-- 2 instancias IDÉNTICAS de la app Flask
        \      /
       [ Postgres ]    <-- estado compartido (por eso son intercambiables)

   [ Netdata :19999 ]  <-- monitoreo del host y de los contenedores
```

## Por qué un laboratorio y no producción

La app pública vive en **Render (plan free)**. Render es un PaaS: administra el
sistema operativo por ti, así que **no hay acceso SSH, ni `ufw`, ni forma de
correr dos instancias** (el plan free da una sola, y además se duerme por
inactividad). Los tres puntos de esta semana requieren control del servidor, y
por eso se demuestran en un entorno donde sí lo tenemos. La sección
correspondiente del reporte lo explica a detalle.

---

## Requisitos

- Docker Desktop corriendo.
- Ejecutar todo desde la **raíz del proyecto** (`questcash_web/`).

## Pasos

```bash
cd ~/questcash_web

# 1) Levantar el laboratorio (tarda unos minutos la primera vez)
bash lab-semana3/scripts/00_arrancar.sh

# 2) Comprobar que el tráfico se reparte entre las dos instancias
bash lab-semana3/scripts/01_reparto.sh

# 3) LA PRUEBA CENTRAL: apagar una instancia con tráfico en vivo
bash lab-semana3/scripts/02_failover.sh

# 4) Generar carga y capturar el monitoreo (abre http://localhost:19999)
bash lab-semana3/scripts/03_generar_carga.sh
```

Cuando termines, lee `CAPTURAS.md` para saber exactamente qué capturar.

Para bajar todo:

```bash
docker compose -f docker-compose.lab.yml down -v
```

---

## Qué demuestra cada pieza

| Requisito de la semana | Cómo se cumple aquí |
|---|---|
| Herramienta de monitoreo | Netdata en `:19999`, observando host, red y los 5 contenedores |
| Firewall a nivel SO | `firewall/ufw_reglas.sh` — política *deny incoming* + solo 22/80/443 |
| Balanceador con 2 instancias | Nginx con `upstream` de `api1` y `api2`, round-robin |
| Prueba de apagar una instancia | `02_failover.sh` — apaga `qc_api2` con tráfico en vivo y mide la disponibilidad |

---

## Detalles que importan

**Las dos instancias comparten la base de datos.** Eso es lo que las hace
intercambiables: si cada una tuviera su propio Postgres, apagar una perdería
datos y no sería alta disponibilidad, sería dos aplicaciones distintas.

**Las instancias no publican puertos.** En `docker-compose.lab.yml` solo `lb`
tiene sección `ports:`. `api1` y `api2` únicamente son alcanzables desde la red
interna de Docker. Eso ya es una forma de segmentación: aunque no haya `ufw`,
el único punto de entrada es el balanceador.

**El failover no se nota gracias a `proxy_next_upstream`.** Cuando Nginx intenta
hablar con una instancia caída, reintenta en la otra *dentro de la misma
petición*. Por eso el resultado esperado es 100 % de disponibilidad y cero
errores, no "unos cuantos 502 al principio".

**El health check es pasivo.** Nginx open source no hace sondeos activos (eso es
Nginx Plus). Con `max_fails=1 fail_timeout=5s` marca la instancia como caída al
primer fallo y la reintenta sola pasados 5 segundos — por eso al reencender
`qc_api2` el tráfico se rebalancea sin tocar nada.
