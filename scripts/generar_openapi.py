#!/usr/bin/env python3
"""Genera docs/openapi.json a partir de las rutas registradas.

Por qué generarla y no escribirla
---------------------------------
Una especificación escrita a mano diverge del código a la primera prisa, y una
documentación que miente es peor que ninguna: manda al que la lee en dirección
contraria. Esta sale de las rutas reales de Flask, así que un endpoint nuevo
aparece solo y uno retirado desaparece.

Lo que NO puede deducirse del código —qué hace cada endpoint, qué devuelve, qué
errores tiene— vive en DESCRIPCIONES, abajo. Es la parte que hay que mantener a
mano, y es poca.

    python scripts/generar_openapi.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Qué hace cada endpoint. La clave es "MÉTODO /ruta".
DESCRIPCIONES = {
    "POST /auth/register": ("Crea una cuenta y devuelve una sesión.", ["Sesión"]),
    "POST /auth/login": ("Inicia sesión. Cinco intentos fallidos bloquean la cuenta 5 minutos.", ["Sesión"]),
    "POST /auth/refresh": ("Canjea el refresh token por un par nuevo. El anterior deja de valer.", ["Sesión"]),
    "POST /auth/logout": ("Cierra esta sesión en el servidor.", ["Sesión"]),
    "POST /auth/logout-all": ("Cierra la sesión en todos los dispositivos.", ["Sesión"]),
    "GET /auth/sesiones": ("Dispositivos con sesión abierta. No expone ningún token.", ["Sesión"]),
    "GET /auth/me": ("Datos de la cuenta y rango actual.", ["Sesión"]),
    "POST /auth/recuperar": ("Pide un enlace de recuperación. Responde igual exista o no la cuenta.", ["Cuenta"]),
    "PUT /auth/password": ("Cambia la contraseña. Cierra las demás sesiones y devuelve una nueva.", ["Cuenta"]),
    "GET /auth/mis-datos": ("Descarga todo lo que QuestCash guarda de esta persona.", ["Cuenta"]),
    "DELETE /auth/cuenta": ("Elimina la cuenta. Irreversible; exige la contraseña.", ["Cuenta"]),
    "GET /dashboard": ("Resumen de inicio: metas, totales, rachas y lectura de Questy.", ["Metas"]),
    "GET /estadisticas": ("Series históricas de ahorro.", ["Metas"]),
    "GET /quests": ("Metas propias y compartidas.", ["Metas"]),
    "POST /quests": ("Crea una meta. Acepta Idempotency-Key.", ["Metas"]),
    "GET /quests/{quest_id}": ("Detalle de una meta, con participantes y evaluación de Questy.", ["Metas"]),
    "PUT /quests/{quest_id}": ("Edita una meta. Solo el creador.", ["Metas"]),
    "DELETE /quests/{quest_id}": ("Elimina una meta y sus movimientos. Solo el creador.", ["Metas"]),
    "POST /quests/{quest_id}/cancel": ("Cancela una meta. Solo el creador.", ["Metas"]),
    "GET /quests/{quest_id}/movimientos": ("Movimientos de una meta. Paginado por cursor.", ["Movimientos"]),
    "POST /quests/{quest_id}/movimientos": ("Registra un aporte o retiro. Acepta Idempotency-Key.", ["Movimientos"]),
    "GET /quests/{quest_id}/colaboradores": ("Participantes de la meta. No expone sus correos.", ["Colaboración"]),
    "POST /quests/{quest_id}/colaboradores": ("Invita por correo. NO añade a nadie: crea una invitación.", ["Colaboración"]),
    "GET /quests/{quest_id}/invitaciones": ("Invitaciones pendientes de la meta. Solo el creador.", ["Colaboración"]),
    "POST /quests/{quest_id}/abandonar": ("Sale de una meta compartida. Los aportes hechos se conservan.", ["Colaboración"]),
    "GET /invitaciones": ("Invitaciones dirigidas a mí, pendientes de respuesta.", ["Colaboración"]),
    "POST /invitaciones/{invitacion_id}/aceptar": ("Acepta una invitación y entra en la meta.", ["Colaboración"]),
    "POST /invitaciones/{invitacion_id}/rechazar": ("Rechaza una invitación.", ["Colaboración"]),
    "GET /gastos": ("Gastos del período. La lista pagina; los totales cubren el período entero.", ["Gastos"]),
    "POST /gastos": ("Registra un gasto. Acepta Idempotency-Key.", ["Gastos"]),
    "GET /categorias-gasto": ("Categorías del sistema más las propias. Nunca las de otra persona.", ["Gastos"]),
    "GET /insignias": ("Catálogo completo, marcando las obtenidas.", ["Gamificación"]),
    "GET /notificaciones": ("Notificaciones persistidas y avisos calculados al vuelo.", ["Gamificación"]),
    "POST /notificaciones/{notif_id}/leer": ("Marca una notificación como leída.", ["Gamificación"]),
    "GET /perfil": ("Perfil y rango.", ["Cuenta"]),
    "PATCH /perfil": ("Actualiza nombre, alias y preferencias de notificación.", ["Cuenta"]),
}

SIN_AUTENTICAR = {
    "POST /auth/register", "POST /auth/login", "POST /auth/refresh",
    "POST /auth/logout", "POST /auth/recuperar",
}


def construir():
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("SECRET_KEY", "generacion-de-documentacion")
    from app import app

    rutas = {}
    for regla in app.url_map.iter_rules():
        if not str(regla).startswith("/api/v1/"):
            continue
        ruta = re.sub(r"<(?:int:)?(\w+)>", r"{\1}", str(regla)).replace("/api/v1", "")
        parametros = [
            {"name": n, "in": "path", "required": True, "schema": {"type": "integer"}}
            for n in re.findall(r"\{(\w+)\}", ruta)
        ]
        for metodo in sorted(regla.methods - {"HEAD", "OPTIONS"}):
            clave = f"{metodo} {ruta}"
            resumen, etiquetas = DESCRIPCIONES.get(clave, ("(sin describir)", ["Otros"]))
            operacion = {
                "summary": resumen,
                "tags": etiquetas,
                "responses": {
                    "200": {"description": "Correcto"},
                    "400": {"description": "Datos inválidos; el cuerpo trae `errors`"},
                },
            }
            if parametros:
                operacion["parameters"] = list(parametros)
            if clave not in SIN_AUTENTICAR:
                operacion["security"] = [{"bearerAuth": []}]
                operacion["responses"]["401"] = {
                    "description": "`token_expired` (renovable), `token_revoked` o `invalid_token`"
                }
                operacion["responses"]["403"] = {"description": "No es tuyo"}
            if metodo == "POST" and "Idempotency-Key" in resumen:
                operacion.setdefault("parameters", []).append({
                    "name": "Idempotency-Key", "in": "header", "required": False,
                    "schema": {"type": "string"},
                    "description": "Repetir la operación con la misma clave devuelve la respuesta original en vez de ejecutarla otra vez.",
                })
                operacion["responses"]["409"] = {
                    "description": "Otra petición con la misma clave está en curso"
                }
            if "Paginado" in resumen or "pagina" in resumen:
                operacion.setdefault("parameters", []).extend([
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": 200}},
                    {"name": "cursor", "in": "query", "schema": {"type": "string"},
                     "description": "`next_cursor` de la página anterior."},
                ])
            rutas.setdefault(ruta, {})[metodo.lower()] = operacion

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "QuestCash API",
            "version": "1.0.0",
            "description": (
                "API de QuestCash. Autenticación por Bearer token: un access de 60 "
                "minutos que se renueva en `/auth/refresh` con un refresh rotatorio.\n\n"
                "Los importes viajan como número JSON y se guardan en la base como "
                "`Numeric(14,2)`: la aritmética es decimal exacta, sin deriva de "
                "centavos.\n\n"
                "Las operaciones que crean algo aceptan `Idempotency-Key` para que un "
                "doble toque o un reintento no las registren dos veces."
            ),
        },
        "servers": [{"url": "/api/v1"}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            }
        },
        "paths": dict(sorted(rutas.items())),
    }


if __name__ == "__main__":
    especificacion = construir()
    os.makedirs("docs", exist_ok=True)
    with open("docs/openapi.json", "w", encoding="utf-8") as f:
        json.dump(especificacion, f, ensure_ascii=False, indent=2)
        f.write("\n")

    total = sum(len(v) for v in especificacion["paths"].values())
    sin_describir = [
        f"{m.upper()} {r}" for r, ops in especificacion["paths"].items()
        for m, o in ops.items() if o["summary"] == "(sin describir)"
    ]
    print(f"docs/openapi.json — {len(especificacion['paths'])} rutas, {total} operaciones")
    if sin_describir:
        print("Sin describir (añádelas a DESCRIPCIONES):")
        for x in sin_describir:
            print(f"  {x}")
        raise SystemExit(1)
