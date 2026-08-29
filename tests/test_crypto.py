"""Cifrado en reposo e índice ciego.

Lo que estas pruebas protegen es que nadie desactive el cifrado sin darse
cuenta: es invisible desde la aplicación —los atributos se leen como texto
normal— así que un cambio en models.py podría quitarlo sin que nada falle.
"""
import crypto_utils
import pytest
from models import Gasto, Movimiento, Usuario, db


def test_cifrar_y_descifrar_es_ida_y_vuelta():
    for valor in ("hola@questcash.com", "Ana Contreras", "acentos áéíóú ñ", "x" * 500):
        assert crypto_utils.descifrar(crypto_utils.cifrar(valor)) == valor


def test_cada_cifrado_es_distinto():
    """El nonce es aleatorio en cada escritura: cifrar dos veces el mismo
    correo da dos cadenas distintas. Por eso hace falta el índice ciego."""
    a = crypto_utils.cifrar("mismo@questcash.com")
    b = crypto_utils.cifrar("mismo@questcash.com")
    assert a != b
    assert crypto_utils.descifrar(a) == crypto_utils.descifrar(b)


def test_cifrar_es_idempotente():
    una = crypto_utils.cifrar("dato")
    assert crypto_utils.cifrar(una) == una


def test_los_vacios_pasan_tal_cual():
    """Así los campos opcionales siguen siendo NULL en la base."""
    assert crypto_utils.cifrar(None) is None
    assert crypto_utils.cifrar("") == ""


def test_alterar_un_byte_hace_fallar_el_descifrado():
    """El tag GCM es de integridad: si alguien toca el registro directamente en
    la base, el descifrado falla en vez de devolver basura en silencio."""
    valor = crypto_utils.cifrar("dato importante")
    alterado = valor[:-4] + ("AAAA" if not valor.endswith("AAAA") else "BBBB")
    with pytest.raises(Exception):
        crypto_utils.descifrar(alterado)


def test_el_indice_ciego_es_determinista_y_normaliza():
    a = crypto_utils.indice_ciego("Ana@QuestCash.com")
    b = crypto_utils.indice_ciego("  ana@questcash.com  ")
    assert a == b and len(a) == 64
    assert crypto_utils.indice_ciego("otro@questcash.com") != a


def test_lo_que_queda_escrito_en_la_base_es_ilegible(cliente, crear_usuario, auth, aplicacion):
    """La comprobación que de verdad importa: mirar el disco, no la API."""
    u = crear_usuario(nombre="Nombre Secreto")
    cab = auth(u["access"])
    import datetime
    limite = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    meta = cliente.post("/api/v1/quests", headers=cab, json={
        "nombre": "M", "monto_objetivo": "100.00", "fecha_limite": limite,
    }).get_json()["quest"]["id"]
    cliente.post(f"/api/v1/quests/{meta}/movimientos", headers=cab,
                 json={"tipo": "aporte", "monto": "10.00", "nota": "nota confidencial"})
    cliente.post("/api/v1/gastos", headers=cab,
                 json={"monto": "5.00", "descripcion": "descripcion confidencial"})

    with aplicacion.app_context():
        crudo = db.session.execute(db.text(
            "SELECT nombre, correo, correo_bi FROM usuarios WHERE id = :i"
        ), {"i": u["id"]}).first()
        assert crudo.nombre.startswith("qc1:")
        assert crudo.correo.startswith("qc1:")
        assert "Nombre Secreto" not in crudo.nombre
        assert "@" not in crudo.correo
        assert len(crudo.correo_bi) == 64          # HMAC, no el correo

        nota = db.session.execute(db.text(
            "SELECT nota FROM movimientos WHERE quest_id = :q"), {"q": meta}).scalar()
        assert nota.startswith("qc1:") and "confidencial" not in nota

        desc = db.session.execute(db.text(
            "SELECT descripcion FROM gastos WHERE usuario_id = :u"), {"u": u["id"]}).scalar()
        assert desc.startswith("qc1:") and "confidencial" not in desc

        # Y aun así la aplicación los lee en claro.
        assert Usuario.query.get(u["id"]).nombre == "Nombre Secreto"
        assert Movimiento.query.filter_by(quest_id=meta).first().nota == "nota confidencial"
        assert Gasto.query.filter_by(usuario_id=u["id"]).first().descripcion == "descripcion confidencial"


def test_el_login_encuentra_al_usuario_por_indice_ciego(cliente, crear_usuario):
    """La columna cifrada no se puede consultar con WHERE porque cada escritura
    usa un nonce distinto: el login busca por correo_bi."""
    u = crear_usuario(correo="Buscame@QuestCash.com")
    # Mayúsculas y espacios: el índice normaliza antes de calcular.
    r = cliente.post("/api/v1/auth/login",
                     json={"correo": "  buscame@questcash.com ", "password": u["password"]})
    assert r.status_code == 200


def test_la_password_no_se_guarda_nunca(cliente, crear_usuario, aplicacion):
    u = crear_usuario()
    with aplicacion.app_context():
        h = db.session.execute(db.text(
            "SELECT password_hash FROM usuarios WHERE id = :i"), {"i": u["id"]}).scalar()
    assert u["password"] not in h
    assert h.startswith("scrypt:32768:8:3$"), "debe usar los parámetros de OWASP"
