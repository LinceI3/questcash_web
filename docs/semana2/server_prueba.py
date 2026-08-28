"""Servidor de prueba: monta el decorador jwt_required REAL del proyecto
(auth_jwt.py) sobre un endpoint protegido y uno publico, para evidenciar
el comportamiento del middleware de autenticacion.
"""
from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask, g, jsonify, request

from auth_jwt import generate_token, jwt_required   # <- codigo real del proyecto
from config import Config                            # <- codigo real del proyecto
from models import Usuario

app = Flask(__name__)
app.config.from_object(Config)

# Usuario de prueba en la "base de datos"
Usuario(1, "Armando Yael", "armando@questcash.mx")


@app.route("/api/v1/auth/login", methods=["POST"])
def login():
    """Endpoint PUBLICO: valida credenciales y devuelve un JWT."""
    data = request.get_json(silent=True) or {}
    if data.get("correo") == "armando@questcash.mx" and data.get("password") == "Secreta123!":
        return jsonify({"token": generate_token(1),
                        "user": {"id": 1, "correo": "armando@questcash.mx"}})
    return jsonify({"error": "invalid_credentials"}), 401


@app.route("/api/v1/auth/me", methods=["GET"])
@jwt_required
def me():
    """Endpoint PROTEGIDO: solo accesible con Bearer token valido."""
    u = g.api_usuario
    return jsonify({"user": {"id": u.id, "nombre": u.nombre, "correo": u.correo}})


@app.route("/api/v1/dashboard", methods=["GET"])
@jwt_required
def dashboard():
    return jsonify({"user_id": g.api_usuario.id, "quests": [], "saldo_total": 0})


# --- utilidades solo para generar tokens de prueba (no forman parte del proyecto) ---
@app.route("/__token_expirado", methods=["GET"])
def token_expirado():
    now = datetime.now(timezone.utc)
    payload = {"sub": "1", "iat": now - timedelta(days=31), "exp": now - timedelta(seconds=10)}
    return jsonify({"token": jwt.encode(payload, app.config["JWT_SECRET_KEY"], algorithm="HS256")})


@app.route("/__token_otra_firma", methods=["GET"])
def token_otra_firma():
    now = datetime.now(timezone.utc)
    payload = {"sub": "1", "iat": now, "exp": now + timedelta(days=1)}
    return jsonify({"token": jwt.encode(payload, "secreto-del-atacante", algorithm="HS256")})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
