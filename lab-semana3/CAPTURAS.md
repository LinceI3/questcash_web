# Qué capturar — Entregable ED, semana 3

El entregable pide tres cosas. Aquí está exactamente qué tomar y cuándo.

---

## 1. Capturas del monitoreo con actividad real

**Cuándo:** mientras corre `03_generar_carga.sh` (dura 2 minutos). Las gráficas
planas de un sistema en reposo no cuentan como "actividad real".

Abre `http://localhost:19999` y captura:

| # | Sección de Netdata | Qué se debe ver |
|---|---|---|
| M1 | Vista general (arriba del todo) | CPU y red moviéndose durante la carga |
| M2 | **System overview → CPU** | El pico de CPU coincidiendo con la ráfaga |
| M3 | **Networking → network interfaces** | Tráfico de entrada/salida no plano |
| M4 | **Docker containers** (menú lateral) | Los 5 contenedores listados con su consumo |
| M5 | Barra superior con el reloj visible | Sirve para fechar la evidencia |

> Consejo: pon la ventana en pantalla completa y usa el selector de tiempo en
> "last 5 minutes" para que el pico se vea grande y no como una rayita.

---

## 2. Reglas de firewall documentadas

Esto **no se puede demostrar en macOS ni en Docker Desktop** — `ufw` es de Linux
y Docker Desktop corre sobre su propia VM. Dos caminos:

**Camino A (recomendado, es real):** levanta una VM Ubuntu en VirtualBox — ya lo
tienes instalado —, copia `firewall/ufw_reglas.sh`, ejecútalo y captura:

| # | Comando | Qué se debe ver |
|---|---|---|
| F1 | `sudo ufw status verbose` | Política `deny (incoming)` + las 3 reglas |
| F2 | `sudo ufw status numbered` | La lista numerada con los comentarios |
| F3 | `sudo ss -tulnp \| grep LISTEN` | Qué procesos escuchan y en qué puerto |
| F4 | `nmap localhost` desde otra máquina | Solo 22, 80 y 443 visibles desde fuera |

**Camino B:** documentas el ruleset como diseño y explicas por qué no se puede
aplicar sobre Docker Desktop. Menos puntos, pero es honesto.

---

## 3. Prueba del balanceo de carga

**Cuándo:** al correr `02_failover.sh`. El script ya guarda la línea de tiempo
completa en texto, pero conviene además grabar la pantalla.

Recomendado: **graba un video de 60 segundos** con tres cosas visibles a la vez:

1. Una terminal corriendo `02_failover.sh` (se ve el momento del apagón).
2. El navegador en `http://localhost:8080/login`, recargando — la página nunca
   deja de cargar.
3. Otra terminal con `docker compose -f docker-compose.lab.yml ps` — se ve
   `qc_api2` pasar a `Exited` y volver a `Up`.

En macOS: `Cmd + Shift + 5` graba pantalla sin instalar nada.

Si prefieres capturas en vez de video, toma cuatro:

| # | Momento | Qué se debe ver |
|---|---|---|
| B1 | Antes | `docker ps` con las 5 contenedores en `Up` |
| B2 | Durante | La línea de tiempo del script con `qc_api2` ya detenida y `HTTP=200` siguiendo |
| B3 | Durante | El navegador cargando el sitio con una instancia caída |
| B4 | Después | El resumen final: disponibilidad 100 %, 0 peticiones fallidas |

---

## Dónde queda todo

Los scripts guardan la salida en texto en `lab-semana3/evidencia/`:

```
evidencia/
  00_estado_contenedores.txt
  00_upstream.txt
  01_reparto.txt
  02_failover.txt
  03_carga.txt
```

Pon tus capturas de pantalla en `lab-semana3/evidencia/capturas/` con nombres
`M1.png`, `F1.png`, `B1.png`… y con eso armo el reporte final.
