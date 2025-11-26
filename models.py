# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

db = SQLAlchemy()


class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.utcnow)

    # 🔸 Puntos acumulados del usuario
    puntos_totales = db.Column(db.Integer, nullable=False, default=0)

    # Relación 1-N con Quest (como creador)
    quests = db.relationship("Quest", back_populates="usuario", lazy=True)

    # Participación en quests colaborativos
    participaciones = db.relationship("ParticipacionQuest", back_populates="usuario", lazy=True)

    # Relación con insignias obtenidas
    insignias_usuario = db.relationship("UsuarioInsignia", back_populates="usuario", lazy=True)

    # --- Perfil del usuario ---
    alias = db.Column(db.String(50), nullable=True)

    # Foto de perfil (nombre del archivo almacenado en /static/uploads/profiles)
    foto_perfil = db.Column(db.String(255), nullable=True)

    # Preferencias de notificación
    notif_ia = db.Column(db.Boolean, nullable=False, default=True)
    notif_fechas = db.Column(db.Boolean, nullable=False, default=True)
    notif_progreso = db.Column(db.Boolean, nullable=False, default=True)


class Quest(db.Model):
    __tablename__ = "quests"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    monto_objetivo = db.Column(db.Float, nullable=False)
    monto_actual = db.Column(db.Float, nullable=False, default=0.0)
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

    def progreso_porcentaje(self):
        if self.monto_objetivo <= 0:
            return 0
        return min(int((self.monto_actual / self.monto_objetivo) * 100), 100)


class Movimiento(db.Model):
    __tablename__ = "movimientos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # 'aporte' o 'retiro'
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    nota = db.Column(db.Text, nullable=True)
    # Categoría del movimiento (comida, transporte, viaje, etc.)
    categoria = db.Column(db.String(50), nullable=True, default="general")

    # Relaciones
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    quest_id = db.Column(db.Integer, db.ForeignKey("quests.id"), nullable=False)

    usuario = db.relationship("Usuario")
    quest = db.relationship("Quest", back_populates="movimientos")


class ParticipacionQuest(db.Model):
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
    )


class Insignia(db.Model):
    __tablename__ = "insignias"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)  # ej. FIRST_GOAL
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    rareza = db.Column(db.String(20), nullable=False, default="común")  # común, rara, épica, legendaria
    icono = db.Column(db.String(100), nullable=True)  # por ahora solo texto / nombre de archivo

    usuarios = db.relationship("UsuarioInsignia", back_populates="insignia", lazy=True)


class UsuarioInsignia(db.Model):
    __tablename__ = "usuarios_insignias"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    insignia_id = db.Column(db.Integer, db.ForeignKey("insignias.id"), nullable=False)
    fecha_obtenida = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="insignias_usuario")
    insignia = db.relationship("Insignia", back_populates="usuarios")

    __table_args__ = (
        db.UniqueConstraint("usuario_id", "insignia_id", name="uq_usuario_insignia"),
    )

   

class CategoriaGasto(db.Model):
    __tablename__ = "categorias_gasto"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False, unique=True)
    tipo = db.Column(db.String(20))  # opcional: 'fijo', 'variable', etc.
    color = db.Column(db.String(20))  # opcional, para usar en gráficas/chips

    gastos = db.relationship("Gasto", back_populates="categoria", lazy=True)

    def __repr__(self):
        return f"<CategoriaGasto {self.nombre}>"


class Gasto(db.Model):
    __tablename__ = "gastos"

    id = db.Column(db.Integer, primary_key=True)

    # quién hizo el gasto
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)

    # categoría del gasto (comida, transporte, etc.)
    categoria_id = db.Column(
        db.Integer, db.ForeignKey("categorias_gasto.id"), nullable=False
    )

    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(200))
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    metodo_pago = db.Column(db.String(30))  # ej. 'efectivo', 'tarjeta', 'transferencia'

    # marca simple de “gasto hormiga”
    es_hormiga = db.Column(db.Boolean, nullable=False, default=False)

    usuario = db.relationship("Usuario", backref="gastos")
    categoria = db.relationship("CategoriaGasto", back_populates="gastos")

    def __repr__(self):
        return f"<Gasto {self.monto} {self.categoria_id} {self.fecha}>"