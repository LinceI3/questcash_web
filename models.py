# models.py
from decimal import Decimal

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import declared_attr
from sqlalchemy.types import TypeDecorator
from datetime import datetime, date

from crypto_utils import cifrar, descifrar, indice_ciego

db = SQLAlchemy()

# Tipo de todos los importes de dinero.
#
# Antes eran db.Float, que en Postgres es `double precision`: binario, incapaz
# de representar exactamente la mayoría de los decimales, y con error que se
# ACUMULA en cada suma sobre `monto_actual`. En una aplicación cuyo texto
# principal es "te faltan $X para tu meta", eso produce centavos que aparecen y
# desaparecen. Numeric es decimal exacto y no acumula error.
#
# 14 dígitos con 2 decimales: hasta 999,999,999,999.99 — muy por encima del
# tope de 1,000,000,000 que imponen los validadores.
#
# SQLAlchemy devuelve estas columnas como decimal.Decimal. Nunca se deben
# mezclar con float en una operación aritmética (Python lanza TypeError):
# conviértase explícitamente con float() en el código de análisis, o manténgase
# en Decimal en la ruta que mueve dinero.
Dinero = db.Numeric(14, 2)
CERO = Decimal("0.00")


class MarcasDeTiempo:
    """Cuándo se creó y cuándo se tocó por última vez cada fila.

    Hacen falta para tres cosas que hoy no se pueden hacer:

      - Sincronización incremental: un cliente móvil que vuelve tras estar sin
        red necesita pedir "lo que cambió desde X" en vez de recargarlo todo.
      - Investigar un incidente: sin saber cuándo cambió una fila no se puede
        reconstruir qué pasó, que es justo lo que exige la obligación de
        notificar una vulneración de datos.
      - Retención: no se puede aplicar una política de conservación sobre datos
        que no dicen cuándo nacieron.

    Se usa `server_default=now()` para que las filas que ya existen queden con
    un valor en vez de NULL al aplicar la migración, y `onupdate` para que
    `actualizado_en` se mantenga solo sin que cada vista tenga que acordarse.
    """

    @declared_attr
    def creado_en(cls):
        return db.Column(
            db.DateTime(timezone=True),
            nullable=False,
            server_default=db.func.now(),
        )

    @declared_attr
    def actualizado_en(cls):
        return db.Column(
            db.DateTime(timezone=True),
            nullable=False,
            server_default=db.func.now(),
            onupdate=db.func.now(),
        )


class TextoCifrado(TypeDecorator):
    """Columna que se guarda cifrada con AES-256-GCM y se lee en claro.

    El cifrado ocurre en el borde de SQLAlchemy: `process_bind_param` corre
    justo antes de mandar el valor a la base de datos y `process_result_value`
    justo después de leerlo. Para el resto de la aplicación —vistas, API,
    plantillas— el atributo se comporta como un `String` normal; lo que cambia
    es lo que queda escrito en disco.

    Ver `crypto_utils.py` para el formato del sobre (`qc1:...`) y el manejo de
    claves.
    """

    impl = db.String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return cifrar(value)

    def process_result_value(self, value, dialect):
        return descifrar(value)


class Usuario(MarcasDeTiempo, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)

    # --- Datos personales: cifrados en reposo (ver TextoCifrado) -------------
    # La longitud declarada es la del CRIPTOGRAMA, no la del dato: el sobre
    # AES-GCM en base64url ocupa aproximadamente 4/3 del original más 40 bytes
    # de nonce y tag. Se declara 512 con holgura.
    nombre = db.Column(TextoCifrado(512), nullable=False)
    correo = db.Column(TextoCifrado(512), nullable=False)

    # Índice ciego del correo: HMAC-SHA256 determinista del correo normalizado.
    # Es por donde se busca al hacer login (el correo cifrado no se puede
    # consultar porque cada escritura usa un nonce distinto) y donde vive
    # ahora la restricción de unicidad de la cuenta.
    correo_bi = db.Column(db.String(64), unique=True, index=True, nullable=True)

    password_hash = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    # Versión de los tokens de acceso emitidos para esta cuenta.
    #
    # Un access token lleva dentro el valor que tenía al emitirse. Incrementar
    # esta columna invalida de golpe TODOS los tokens vivos del usuario, sin
    # tener que buscarlos ni guardarlos: al validar se compara y no coinciden.
    # Es lo que hace posible "cerrar sesión en todos los dispositivos" y lo que
    # debe hacer un cambio de contraseña.
    # server_default además de default: sin él, añadir esta columna NOT NULL
    # sobre una tabla con filas falla — Postgres no sabe qué poner en las
    # que ya existen, y el `default` de Python solo aplica a las nuevas.
    token_version = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )

    # --- Búsqueda por correo ------------------------------------------------
    @staticmethod
    def por_correo(correo):
        """Sustituye a `Usuario.query.filter_by(correo=...)`, que dejó de
        funcionar al cifrar la columna. Busca por el índice ciego."""
        bi = indice_ciego(correo)
        if not bi:
            return None
        return Usuario.query.filter_by(correo_bi=bi).first()

    def set_correo(self, correo):
        """Asigna el correo y mantiene sincronizado su índice ciego. Usar
        siempre esto en vez de `usuario.correo = ...`."""
        normalizado = (correo or "").strip().lower()
        self.correo = normalizado
        self.correo_bi = indice_ciego(normalizado)

    # 🔸 Puntos acumulados del usuario
    puntos_totales = db.Column(db.Integer, nullable=False, default=0)

    # Relación 1-N con Quest (como creador)
    quests = db.relationship("Quest", back_populates="usuario", lazy=True)

    # Participación en quests colaborativos
    participaciones = db.relationship("ParticipacionQuest", back_populates="usuario", lazy=True)

    # Relación con insignias obtenidas
    insignias_usuario = db.relationship("UsuarioInsignia", back_populates="usuario", lazy=True)

    # --- Perfil del usuario ---
    # El alias es un dato personal más: también va cifrado en reposo.
    alias = db.Column(TextoCifrado(512), nullable=True)

    # Foto de perfil (nombre del archivo almacenado en /static/uploads/profiles)
    foto_perfil = db.Column(db.String(255), nullable=True)

    # Preferencias de notificación
    notif_ia = db.Column(db.Boolean, nullable=False, default=True)
    notif_fechas = db.Column(db.Boolean, nullable=False, default=True)
    notif_progreso = db.Column(db.Boolean, nullable=False, default=True)


class Sesion(MarcasDeTiempo, db.Model):
    """Un refresh token vivo, es decir, un dispositivo con sesión iniciada.

    Antes la API emitía un único JWT de 30 días sin `jti`, sin lista de
    revocación y sin forma de renovarlo. Cerrar sesión solo borraba el token
    del dispositivo: seguía siendo válido un mes para quien lo tuviera, y
    cambiar la contraseña tampoco lo invalidaba. Un token capturado daba un mes
    de acceso completo a los datos financieros del usuario.

    El modelo ahora es el estándar de dos tokens:

      - ACCESS token, corto (60 min por omisión). No se guarda en ninguna
        parte: se valida por firma, caducidad y `token_version`.
      - REFRESH token, largo (30 días), que SÍ vive aquí y se puede revocar.
        Rota en cada uso: al canjearlo se marca el anterior como usado y se
        emite uno nuevo. Si alguien roba un refresh y lo canjea, el legítimo
        deja de funcionar en su siguiente intento — el robo se nota.

    Del token solo se guarda su hash. Igual que con las contraseñas: quien lea
    esta tabla no puede suplantar a nadie con lo que encuentre dentro.
    """

    __tablename__ = "sesiones"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)

    # SHA-256 del refresh token. Determinista para poder buscarlo, e inútil
    # para quien lo lea.
    token_hash = db.Column(db.String(64), unique=True, index=True, nullable=False)

    # Etiqueta legible del dispositivo, para que el usuario reconozca sus
    # sesiones en una futura pantalla de "dispositivos conectados".
    dispositivo = db.Column(db.String(120), nullable=True)

    expira_en = db.Column(db.DateTime(timezone=True), nullable=False)
    ultimo_uso = db.Column(db.DateTime(timezone=True), nullable=True)

    # Motivo de revocación: logout | rotacion | cierre_total | expirada.
    # Se conserva la fila revocada en vez de borrarla: si un refresh ya rotado
    # vuelve a aparecer, es señal de robo y hay con qué detectarlo.
    revocada_en = db.Column(db.DateTime(timezone=True), nullable=True)
    motivo_revocacion = db.Column(db.String(30), nullable=True)

    usuario = db.relationship("Usuario")

    __table_args__ = (
        db.Index("ix_sesiones_usuario", "usuario_id"),
    )

    def esta_viva(self, ahora):
        return self.revocada_en is None and self.expira_en > ahora


class Quest(MarcasDeTiempo, db.Model):
    __tablename__ = "quests"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    monto_objetivo = db.Column(Dinero, nullable=False)
    monto_actual = db.Column(Dinero, nullable=False, default=CERO)
    fecha_limite = db.Column(db.Date, nullable=False)
    # 🔸 Fecha de creación del reto
    fecha_creacion = db.Column(db.Date, nullable=False, default=date.today)

    dificultad = db.Column(db.String(20), nullable=True)  # fácil, media, difícil
    estatus = db.Column(db.String(20), nullable=False, default="pendiente")
    puntos_recompensa = db.Column(db.Integer, nullable=False, default=0)

    # 🔸 Para no dar puntos dos veces
    puntos_otorgados = db.Column(db.Boolean, nullable=False, default=False)

    # Indica si el reto es colaborativo (bandera legacy para compatibilidad)
    es_colaborativo = db.Column(db.Boolean, nullable=False, default=False)

    # individual o colaborativo
    tipo = db.Column(db.String(20), nullable=False, default="individual")

    # Ícono elegido por el usuario (nombre de Ionicons), usado por la app móvil
    icono = db.Column(db.String(30), nullable=True)

    # FK al usuario creador del reto
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    usuario = db.relationship("Usuario", back_populates="quests")

    # Relación 1-N con movimientos
    movimientos = db.relationship(
        "Movimiento",
        back_populates="quest",
        lazy=True,
        cascade="all, delete-orphan"
    )

    # Relación 1-N con participaciones
    participaciones = db.relationship(
        "ParticipacionQuest",
        back_populates="quest",
        lazy=True,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("ix_quests_usuario", "usuario_id"),
    )

    def progreso_porcentaje(self):
        objetivo = self.monto_objetivo or CERO
        if objetivo <= 0:
            return 0
        actual = self.monto_actual or CERO
        return min(int((actual / objetivo) * 100), 100)


class Movimiento(MarcasDeTiempo, db.Model):
    __tablename__ = "movimientos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # 'aporte' o 'retiro'
    monto = db.Column(Dinero, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    # La nota describe en texto libre en qué se ahorró o se retiró dinero:
    # es detalle financiero del usuario, va cifrada en reposo.
    nota = db.Column(TextoCifrado(2048), nullable=True)
    # Categoría del movimiento (comida, transporte, viaje, etc.)
    categoria = db.Column(db.String(50), nullable=True, default="general")

    # Relaciones
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)

    usuario = db.relationship("Usuario")
    quest = db.relationship("Quest", back_populates="movimientos")

    __table_args__ = (
        # El dashboard, las rachas y las estadísticas filtran por usuario y
        # ordenan por fecha descendente. Este índice cubre las tres.
        db.Index("ix_movimientos_usuario_fecha", "usuario_id", db.text("fecha DESC")),
        db.Index("ix_movimientos_quest", "quest_id"),
    )


class ParticipacionQuest(MarcasDeTiempo, db.Model):
    __tablename__ = "participaciones_quest"

    id = db.Column(db.Integer, primary_key=True)
    rol = db.Column(db.String(20), nullable=False, default="colaborador")  # creador / colaborador
    fecha_union = db.Column(db.DateTime, default=datetime.utcnow)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)

    usuario = db.relationship("Usuario", back_populates="participaciones")
    quest = db.relationship("Quest", back_populates="participaciones")

    __table_args__ = (
        db.UniqueConstraint("usuario_id", "quest_id", name="uq_usuario_quest"),
        db.Index("ix_participaciones_quest", "quest_id"),
    )


class Insignia(MarcasDeTiempo, db.Model):
    __tablename__ = "insignias"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)  # ej. FIRST_GOAL
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    rareza = db.Column(db.String(20), nullable=False, default="común")  # común, rara, épica, legendaria
    icono = db.Column(db.String(100), nullable=True)  # por ahora solo texto / nombre de archivo

    usuarios = db.relationship("UsuarioInsignia", back_populates="insignia", lazy=True)


class UsuarioInsignia(MarcasDeTiempo, db.Model):
    __tablename__ = "usuarios_insignias"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    insignia_id = db.Column(db.Integer, db.ForeignKey("insignias.id"), nullable=False)
    fecha_obtenida = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="insignias_usuario")
    insignia = db.relationship("Insignia", back_populates="usuarios")

    __table_args__ = (
        db.UniqueConstraint("usuario_id", "insignia_id", name="uq_usuario_insignia"),
        db.Index("ix_usuarios_insignias_insignia", "insignia_id"),
    )

   

class CategoriaGasto(MarcasDeTiempo, db.Model):
    __tablename__ = "categorias_gasto"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    tipo = db.Column(db.String(20))  # opcional: 'fijo', 'variable', etc.
    color = db.Column(db.String(20))  # opcional, para usar en gráficas/chips

    gastos = db.relationship("Gasto", back_populates="categoria", lazy=True)

    def __repr__(self):
        return f"<CategoriaGasto {self.nombre}>"


class Gasto(MarcasDeTiempo, db.Model):
    __tablename__ = "gastos"

    id = db.Column(db.Integer, primary_key=True)

    # quién hizo el gasto
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)

    # categoría del gasto (comida, transporte, etc.)
    categoria_id = db.Column(
        db.Integer, db.ForeignKey("categorias_gasto.id"), nullable=False
    )

    monto = db.Column(Dinero, nullable=False)
    # Descripción del gasto ("consulta médica", "pago del abogado"): puede
    # revelar hábitos y datos de salud o legales. Cifrada en reposo.
    descripcion = db.Column(TextoCifrado(1024))
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    metodo_pago = db.Column(db.String(30))  # ej. 'efectivo', 'tarjeta', 'transferencia'

    # marca simple de “gasto hormiga”
    es_hormiga = db.Column(db.Boolean, nullable=False, default=False)

    usuario = db.relationship("Usuario", backref="gastos")
    categoria = db.relationship("CategoriaGasto", back_populates="gastos")

    __table_args__ = (
        db.Index("ix_gastos_usuario_fecha", "usuario_id", db.text("fecha DESC")),
        db.Index("ix_gastos_categoria", "categoria_id"),
    )

    def __repr__(self):
        return f"<Gasto {self.monto} {self.categoria_id} {self.fecha}>"


class Notificacion(MarcasDeTiempo, db.Model):
    """Notificaciones persistidas, disparadas por eventos reales (meta
    completada, insignia nueva, aporte de un colaborador). Las notificaciones
    de reglas dinámicas (recordatorios de vencimiento, consejos de gasto)
    siguen generándose al vuelo en generar_notificaciones() y no se guardan
    aquí, para no duplicar filas cada vez que se recalculan."""
    __tablename__ = "notificaciones"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)

    # meta_completada | aporte_colaborador | insignia_nueva
    tipo = db.Column(db.String(30), nullable=False)

    titulo = db.Column(db.String(100), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    icono = db.Column(db.String(30), nullable=True)
    color = db.Column(db.String(20), nullable=True)

    leida = db.Column(db.Boolean, nullable=False, default=False)

    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=True)

    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("Usuario")
    quest = db.relationship("Quest")

    __table_args__ = (
        db.Index("ix_notificaciones_usuario_fecha", "usuario_id", db.text("fecha_creacion DESC")),
    )

    def __repr__(self):
        return f"<Notificacion {self.tipo} usuario={self.usuario_id}>"