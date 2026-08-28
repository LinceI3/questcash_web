# Reglas de firewall — documentación

## Política

| Dirección | Política por defecto | Razón |
|---|---|---|
| Entrante (`incoming`) | **DENY** | Nada entra salvo lo explícitamente permitido. Es el principio de mínimo privilegio aplicado a la red. |
| Saliente (`outgoing`) | **ALLOW** | El servidor necesita salir: actualizaciones del SO, DNS, certificados ACME, APIs externas. |

## Puertos abiertos

| Puerto | Protocolo | Servicio | Por qué está abierto |
|---|---|---|---|
| 22 | TCP | SSH | Única vía de administración del servidor. Se abre con `ufw limit`, que bloquea una IP tras 6 intentos de conexión en 30 s — frena la fuerza bruta automatizada. |
| 80 | TCP | HTTP | Necesario para el reto HTTP-01 de Let's Encrypt (renovación del certificado) y para redirigir a HTTPS. No sirve contenido real. |
| 443 | TCP | HTTPS | Por aquí entra **todo** el tráfico de usuarios. Es el único puerto que la aplicación necesita realmente. |

## Puertos deliberadamente cerrados

| Puerto | Servicio | Por qué NO se abre |
|---|---|---|
| 5432 | PostgreSQL | Solo debe ser alcanzable desde la red interna de Docker. Una base de datos expuesta a internet es una de las causas más comunes de fuga de datos y ransomware. |
| 5000 | Flask / Gunicorn | Las instancias de la API solo hablan con Nginx. Si fueran accesibles directo, alguien podría saltarse el balanceador, el rate limiting y el TLS. |
| 8080 | Nginx del laboratorio | Puerto de desarrollo. En un servidor real el proxy escucha en 80 y 443. |
| 19999 | Netdata | El panel expone topología, procesos y métricas del servidor: es reconocimiento gratis para un atacante. Se accede por túnel SSH: `ssh -L 19999:localhost:19999 usuario@servidor` y luego `http://localhost:19999` en tu máquina. |

## Por qué esto no se puede aplicar sobre Docker Desktop en macOS

`ufw` es un envoltorio de `iptables`, que es del kernel de Linux. macOS usa `pf`
(Packet Filter), que es otra cosa. Además Docker Desktop corre los contenedores
dentro de una VM Linux propia y gestiona sus reglas de red automáticamente:
cualquier `ufw` aplicado dentro de un contenedor no reflejaría la realidad del
host.

Para presentar evidencia real hay dos caminos válidos:

1. **VM Ubuntu en VirtualBox** — ejecutas `ufw_reglas.sh` dentro y capturas la
   salida de `ufw status verbose`. Es un firewall de verdad sobre un SO de verdad.
2. **VPS** — una instancia mínima en cualquier proveedor, con IP pública. Es el
   escenario más fiel: puedes comprobar desde fuera, con `nmap`, que efectivamente
   solo responden 22, 80 y 443.

## Comprobaciones que valen como evidencia

```bash
# 1. Estado del firewall con la política y los comentarios
sudo ufw status verbose

# 2. Lista numerada (útil para mostrar el orden de las reglas)
sudo ufw status numbered

# 3. Qué procesos escuchan realmente y en qué interfaz
sudo ss -tulnp | grep LISTEN

# 4. Vista desde FUERA: el escaneo solo debe encontrar 22, 80 y 443
nmap -Pn <ip-del-servidor>
```

El punto 4 es el más contundente: demuestra que el firewall funciona desde la
perspectiva de un atacante, no solo desde la configuración declarada.
