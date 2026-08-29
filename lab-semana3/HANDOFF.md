# Contexto para la sesión que corra en la computadora

> Pega este archivo (o pídele a Claude que lo lea) al iniciar la tarea
> en modo **"On your computer"**.

## Qué se está haciendo

Reporte de la **semana 3** de la materia, para el proyecto **QuestCash**.
Objetivo de la semana: *"que el sistema esté vigilado, protegido a nivel de red
y sea tolerante a fallas"*.

Entregable ED — semana 3:

1. Capturas del monitoreo mostrando actividad real del sistema.
2. Reglas de firewall documentadas (qué puertos abiertos y por qué).
3. Video o capturas de la prueba de balanceo de carga (apagar una instancia y
   ver que el sitio sigue vivo).

## Estado: todo está preparado, falta ejecutarlo

En una sesión anterior (en la nube) se dejó listo el laboratorio completo en
`questcash_web/lab-semana3/`. **No se pudo ejecutar** porque ese entorno tenía
la salida a internet bloqueada: `apt`, `pip` y `npm` devolvían 403, así que no
se pudo instalar Nginx ni Netdata.

Lo que falta es simplemente correrlo en una máquina con Docker e internet.

## Lo que hay que hacer

```bash
cd ~/questcash_web
bash lab-semana3/scripts/00_arrancar.sh      # levanta el stack
bash lab-semana3/scripts/01_reparto.sh       # prueba de reparto
bash lab-semana3/scripts/02_failover.sh      # LA prueba central
bash lab-semana3/scripts/03_generar_carga.sh # carga para el monitoreo
```

Luego:

- Tomar las capturas que lista `lab-semana3/CAPTURAS.md` y guardarlas en
  `lab-semana3/evidencia/capturas/`.
- Compilar el reporte LaTeX con la evidencia real.

## Estilo del reporte

Debe seguir el mismo formato que el de la semana 2, que está en
`questcash_web/docs/semana2/reporte_semana2.tex`. **Reutilizar su preámbulo tal
cual** (paleta `qcNavy`/`qcBlue`, cajas `consola` y `nota`, estilos `terminal` y
`python` de `listings`, encabezado `fancyhdr`, portada con tabla de metadatos).
Compila con `pdflatex`, dos pasadas.

El reporte de la semana 2 documentaba la autenticación JWT y salió de 11 páginas.
El de la semana 3 debe verse como su continuación, no como otro documento.

## Datos del proyecto que conviene tener a mano

- **Backend:** `questcash_web/` — Flask + SQLAlchemy, API JSON en `/api/v1`,
  vistas HTML con Jinja. `app = create_app()` a nivel de módulo, así que
  Gunicorn lo sirve como `app:app`.
- **Móvil:** `questcash_mobile/` — Expo / React Native, consume `/api/v1`.
- **Producción:** Render, **plan free** (una sola instancia, se duerme por
  inactividad, sin acceso al SO). Dominio `.onrender.com`, sin Cloudflare.
- **El usuario ya decidió** que el reporte sea *solo del laboratorio*, sin una
  pista paralela sobre Render — pero sí conviene explicar en una sección breve
  por qué el laboratorio es necesario (Render no permite ufw, SSH ni 2
  instancias en el plan free).

## Advertencia sobre el firewall

`ufw` **no se puede demostrar en macOS** (es de Linux; macOS usa `pf`, y Docker
Desktop gestiona sus propias reglas en una VM). Está documentado en
`lab-semana3/firewall/README-firewall.md`. El usuario tiene VirtualBox
instalado: la opción con evidencia real es una VM Ubuntu. Hay que preguntarle si
quiere hacerlo o si prefiere documentarlo como diseño.
