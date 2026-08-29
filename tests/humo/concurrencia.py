#!/usr/bin/env python3
"""Pruebas de concurrencia contra una pila REAL con varios workers.

Por qué no son pytest
---------------------
El cliente de pruebas de Flask atiende una petición a la vez en el mismo
proceso. Los tres defectos que verifica este archivo —aportes perdidos por
leer-modificar-escribir, idempotencia rota, contador de intentos que no se
comparte— SOLO aparecen con varios procesos compitiendo de verdad. Una versión
en pytest daría verde siempre y no probaría nada.

Ese fue exactamente el error durante la fase 3: el primer arreglo de la
condición de carrera se dio por bueno probándolo con un solo worker, y era
inerte.

Uso
---
    python tests/humo/concurrencia.py --url http://localhost:5002

La pila destino debe correr con **al menos 2 workers**. Con uno, este archivo
avisa y no prueba nada útil.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import sys
import urllib.error
import urllib.request
import uuid

fallos: list[str] = []


def ck(nombre, condicion, detalle=""):
    print(f"  {'OK  ' if condicion else 'FALLO'}  {nombre}" + (f"  — {detalle}" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


class Api:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def __call__(self, metodo, ruta, cuerpo=None, token=None, clave=None, timeout=60):
        req = urllib.request.Request(self.base + ruta, method=metodo)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        if clave:
            req.add_header("Idempotency-Key", clave)
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        try:
            with urllib.request.urlopen(req, datos, timeout=timeout) as r:
                texto = r.read().decode()
                return r.status, (json.loads(texto) if texto.strip().startswith(("{", "[")) else {}), dict(r.headers)
        except urllib.error.HTTPError as e:
            texto = e.read().decode()
            try:
                return e.code, json.loads(texto), dict(e.headers)
            except Exception:
                return e.code, {}, dict(e.headers)
        except Exception as e:  # red caída, timeout
            return 0, {"error": str(e)[:60]}, {}


def limite(dias=90):
    return (datetime.date.today() + datetime.timedelta(days=dias)).isoformat()


def alta(api):
    correo = f"humo{uuid.uuid4().hex[:10]}@questcash.com"
    password = "HumoSeguro99"
    s, r, _ = api("POST", "/api/v1/auth/register", {
        "nombre": "Humo", "correo": correo, "password": password, "password2": password,
    })
    if s != 201:
        sys.exit(f"no se pudo registrar el usuario de prueba: {s} {r}")
    return r["access_token"], correo, password


def meta(api, token, objetivo="100000.00"):
    s, r, _ = api("POST", "/api/v1/quests", {
        "nombre": f"Humo {uuid.uuid4().hex[:6]}",
        "monto_objetivo": objetivo, "fecha_limite": limite(),
    }, token=token)
    return r["quest"]["id"]


# ---------------------------------------------------------------------------
def aportes_simultaneos(api, token, n):
    """Sin bloqueo de fila se perdían aportes: los movimientos quedaban
    guardados pero el saldo no los reflejaba."""
    q = meta(api, token)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 40)) as ex:
        res = list(ex.map(
            lambda _: api("POST", f"/api/v1/quests/{q}/movimientos",
                          {"tipo": "aporte", "monto": "1.00"}, token=token),
            range(n)))
    aceptadas = sum(1 for s, _, _ in res if s == 201)
    _, detalle, _ = api("GET", f"/api/v1/quests/{q}", token=token)
    _, movs, _ = api("GET", f"/api/v1/quests/{q}/movimientos", token=token)
    saldo = detalle["quest"]["monto_actual"]
    guardados = len(movs["movimientos"])
    ck(f"{n} aportes simultáneos: saldo == movimientos == aceptadas",
       saldo == float(aceptadas) == float(guardados),
       f"aceptadas={aceptadas} movimientos={guardados} saldo={saldo}")


def idempotencia_simultanea(api, token, n):
    """Comprobar-luego-actuar no basta: hay que reservar la clave ANTES de
    ejecutar, o dos peticiones simultáneas ejecutan las dos."""
    q = meta(api, token)
    clave = str(uuid.uuid4())
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(
            lambda _: api("POST", f"/api/v1/quests/{q}/movimientos",
                          {"tipo": "aporte", "monto": "100.00"}, token=token, clave=clave),
            range(n)))
    ejecutadas = sum(1 for s, _, h in res if s == 201 and h.get("Idempotent-Replay") != "true")
    reproducidas = sum(1 for _, _, h in res if h.get("Idempotent-Replay") == "true")
    en_curso = sum(1 for s, _, _ in res if s == 409)
    _, detalle, _ = api("GET", f"/api/v1/quests/{q}", token=token)
    _, movs, _ = api("GET", f"/api/v1/quests/{q}/movimientos", token=token)
    de_cien = [m for m in movs["movimientos"] if float(m["monto"]) == 100.0]
    ck(f"{n} peticiones simultáneas con la MISMA clave: solo una ejecuta",
       ejecutadas == 1 and len(de_cien) == 1 and detalle["quest"]["monto_actual"] == 100.0,
       f"ejecutadas={ejecutadas} reproducidas={reproducidas} 409={en_curso} "
       f"movimientos_de_100={len(de_cien)} saldo={detalle['quest']['monto_actual']}")


def bloqueo_compartido(api):
    """El contador vivía en un diccionario de proceso: cada worker daba sus
    propios 5 intentos."""
    _, correo, password = alta(api)
    codigos = []
    for _ in range(7):
        s, _, _ = api("POST", "/api/v1/auth/login", {"correo": correo, "password": "mala"})
        codigos.append(s)
    bloqueado_en = next((i + 1 for i, c in enumerate(codigos) if c == 429), None)
    ck("el bloqueo se comparte entre workers (5 intentos en TOTAL)",
       bloqueado_en == 6, f"bloqueó en el intento {bloqueado_en}, códigos={codigos}")
    s, _, _ = api("POST", "/api/v1/auth/login", {"correo": correo, "password": password})
    ck("el bloqueo aplica también a la contraseña correcta", s == 429, f"HTTP {s}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5002")
    ap.add_argument("--n", type=int, default=40, help="peticiones simultáneas")
    args = ap.parse_args()

    api = Api(args.url)
    s, _, _ = api("GET", "/login", timeout=10)
    if s == 0:
        sys.exit(f"no hay nada escuchando en {args.url}")

    print(f"Pila destino: {args.url}")
    print("(debe correr con 2 workers o más; con uno estas pruebas no prueban nada)\n")

    token, _, _ = alta(api)

    print("--- aportes perdidos ---")
    for n in (25, args.n):
        aportes_simultaneos(api, token, n)

    print("\n--- idempotencia ---")
    idempotencia_simultanea(api, token, 8)

    print("\n--- bloqueo de intentos ---")
    bloqueo_compartido(api)

    print("\n" + ("TODO CORRECTO" if not fallos else f"{len(fallos)} FALLOS: {fallos}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
