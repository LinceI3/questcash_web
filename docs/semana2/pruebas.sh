#!/usr/bin/env bash
# Bateria de pruebas del middleware JWT — QuestCash API v1
BASE="http://127.0.0.1:5001/api/v1"
lim() { sed 's/\r$//' | grep -vE "^(Server|Date|Connection):"; }
linea() { printf '\n========================================================\n %s\n========================================================\n' "$1"; }

linea "P0 - LOGIN con credenciales validas => devuelve JWT (200)"
echo '$ curl -i -X POST $BASE/auth/login -H "Content-Type: application/json" -d {"correo":"...","password":"..."}'
curl -s -i -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d '{"correo":"armando@questcash.mx","password":"Secreta123!"}' | lim
TOKEN=$(curl -s -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d '{"correo":"armando@questcash.mx","password":"Secreta123!"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

linea "P0b - LOGIN con contrasena incorrecta => 401 invalid_credentials"
echo '$ curl -i -X POST $BASE/auth/login -d {"correo":"...","password":"incorrecta"}'
curl -s -i -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d '{"correo":"armando@questcash.mx","password":"incorrecta"}' | lim

linea "P1 - GET /auth/me SIN token => RECHAZA (401 missing_token)"
echo '$ curl -i $BASE/auth/me'
curl -s -i "$BASE/auth/me" | lim

linea "P2 - GET /auth/me CON token valido => ACEPTA (200)"
echo '$ curl -i $BASE/auth/me -H "Authorization: Bearer $TOKEN"'
curl -s -i "$BASE/auth/me" -H "Authorization: Bearer $TOKEN" | lim

linea "P3 - Token MANIPULADO (payload sub 1 -> 2, firma original) => 401 invalid_token"
FAKE=$(python3 - "$TOKEN" <<'PY'
import base64, json, sys
h,p,s = sys.argv[1].split('.')
d=lambda x: json.loads(base64.urlsafe_b64decode(x+'='*(-len(x)%4)))
pl=d(p); pl["sub"]="2"
np=base64.urlsafe_b64encode(json.dumps(pl,separators=(',',':')).encode()).rstrip(b'=').decode()
print(f"{h}.{np}.{s}")
PY
)
echo '$ curl -i $BASE/auth/me -H "Authorization: Bearer <token con payload alterado>"'
curl -s -i "$BASE/auth/me" -H "Authorization: Bearer $FAKE" | lim

linea "P4 - Token EXPIRADO => 401 token_expired"
EXP=$(curl -s http://127.0.0.1:5001/__token_expirado | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo '$ curl -i $BASE/auth/me -H "Authorization: Bearer <token vencido>"'
curl -s -i "$BASE/auth/me" -H "Authorization: Bearer $EXP" | lim

linea "P5 - Token firmado con OTRA clave secreta => 401 invalid_token"
OTRO=$(curl -s http://127.0.0.1:5001/__token_otra_firma | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
echo '$ curl -i $BASE/auth/me -H "Authorization: Bearer <token firmado por un tercero>"'
curl -s -i "$BASE/auth/me" -H "Authorization: Bearer $OTRO" | lim

linea "P6 - Esquema de cabecera incorrecto (Basic en vez de Bearer) => 401 missing_token"
echo '$ curl -i $BASE/auth/me -H "Authorization: Basic REDACTADO-VALOR-DE-PRUEBA"'
curl -s -i "$BASE/auth/me" -H "Authorization: Basic REDACTADO-VALOR-DE-PRUEBA" | lim

linea "P7 - Segundo endpoint protegido /dashboard: sin token vs con token"
printf '$ curl -o /dev/null -w "%%{http_code}" $BASE/dashboard                -> '; curl -s -o /dev/null -w "%{http_code}\n" "$BASE/dashboard"
printf '$ curl -o /dev/null -w "%%{http_code}" $BASE/dashboard  (con Bearer)  -> '; curl -s -o /dev/null -w "%{http_code}\n" "$BASE/dashboard" -H "Authorization: Bearer $TOKEN"

linea "P8 - Contenido del token emitido (header y payload decodificados)"
python3 - "$TOKEN" <<'PY'
import base64, json, sys, datetime
tok=sys.argv[1]; h,p,s=tok.split('.')
d=lambda x: json.loads(base64.urlsafe_b64decode(x+'='*(-len(x)%4)))
pl=d(p)
print("token   :", tok[:38]+"..."+tok[-12:])
print("header  :", json.dumps(d(h)))
print("payload :", json.dumps(pl))
print("iat     :", datetime.datetime.fromtimestamp(pl['iat'], datetime.timezone.utc).isoformat())
print("exp     :", datetime.datetime.fromtimestamp(pl['exp'], datetime.timezone.utc).isoformat())
print("vigencia:", (pl['exp']-pl['iat'])/86400, "dias")
print("firma   :", s[:20]+"... ("+str(len(s))+" chars)")
PY
