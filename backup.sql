--
-- PostgreSQL database dump
--

\restrict kc661f5W46lQTBohHAquAWDVhfekAZk5BPdNc4wf05JUM5PVMwsrg1SJ0PU73CT

-- Dumped from database version 15.17 (Debian 15.17-1.pgdg13+1)
-- Dumped by pg_dump version 15.17 (Debian 15.17-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: categorias_gasto; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.categorias_gasto (
    id integer NOT NULL,
    nombre character varying(50) NOT NULL,
    tipo character varying(20),
    color character varying(20)
);


ALTER TABLE public.categorias_gasto OWNER TO questcash;

--
-- Name: categorias_gasto_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.categorias_gasto_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.categorias_gasto_id_seq OWNER TO questcash;

--
-- Name: categorias_gasto_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.categorias_gasto_id_seq OWNED BY public.categorias_gasto.id;


--
-- Name: gastos; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.gastos (
    id integer NOT NULL,
    usuario_id integer NOT NULL,
    categoria_id integer NOT NULL,
    monto double precision NOT NULL,
    descripcion character varying(200),
    fecha date NOT NULL,
    metodo_pago character varying(30),
    es_hormiga boolean NOT NULL
);


ALTER TABLE public.gastos OWNER TO questcash;

--
-- Name: gastos_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.gastos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.gastos_id_seq OWNER TO questcash;

--
-- Name: gastos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.gastos_id_seq OWNED BY public.gastos.id;


--
-- Name: insignias; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.insignias (
    id integer NOT NULL,
    codigo character varying(50) NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion text,
    rareza character varying(20) NOT NULL,
    icono character varying(100)
);


ALTER TABLE public.insignias OWNER TO questcash;

--
-- Name: insignias_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.insignias_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.insignias_id_seq OWNER TO questcash;

--
-- Name: insignias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.insignias_id_seq OWNED BY public.insignias.id;


--
-- Name: movimientos; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.movimientos (
    id integer NOT NULL,
    tipo character varying(20) NOT NULL,
    monto double precision NOT NULL,
    fecha timestamp without time zone,
    nota text,
    categoria character varying(50),
    usuario_id integer NOT NULL,
    quest_id integer NOT NULL
);


ALTER TABLE public.movimientos OWNER TO questcash;

--
-- Name: movimientos_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.movimientos_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.movimientos_id_seq OWNER TO questcash;

--
-- Name: movimientos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.movimientos_id_seq OWNED BY public.movimientos.id;


--
-- Name: participaciones_quest; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.participaciones_quest (
    id integer NOT NULL,
    rol character varying(20) NOT NULL,
    fecha_union timestamp without time zone,
    usuario_id integer NOT NULL,
    quest_id integer NOT NULL
);


ALTER TABLE public.participaciones_quest OWNER TO questcash;

--
-- Name: participaciones_quest_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.participaciones_quest_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.participaciones_quest_id_seq OWNER TO questcash;

--
-- Name: participaciones_quest_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.participaciones_quest_id_seq OWNED BY public.participaciones_quest.id;


--
-- Name: quests; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.quests (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    descripcion text,
    monto_objetivo double precision NOT NULL,
    monto_actual double precision NOT NULL,
    fecha_limite date NOT NULL,
    fecha_creacion date NOT NULL,
    dificultad character varying(20),
    estatus character varying(20) NOT NULL,
    puntos_recompensa integer NOT NULL,
    puntos_otorgados boolean NOT NULL,
    es_colaborativo boolean NOT NULL,
    tipo character varying(20) NOT NULL,
    usuario_id integer NOT NULL
);


ALTER TABLE public.quests OWNER TO questcash;

--
-- Name: quests_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.quests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.quests_id_seq OWNER TO questcash;

--
-- Name: quests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.quests_id_seq OWNED BY public.quests.id;


--
-- Name: usuarios; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.usuarios (
    id integer NOT NULL,
    nombre character varying(100) NOT NULL,
    correo character varying(120) NOT NULL,
    password_hash character varying(255) NOT NULL,
    fecha_registro timestamp without time zone,
    puntos_totales integer NOT NULL,
    alias character varying(50),
    foto_perfil character varying(255),
    notif_ia boolean NOT NULL,
    notif_fechas boolean NOT NULL,
    notif_progreso boolean NOT NULL
);


ALTER TABLE public.usuarios OWNER TO questcash;

--
-- Name: usuarios_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.usuarios_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.usuarios_id_seq OWNER TO questcash;

--
-- Name: usuarios_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.usuarios_id_seq OWNED BY public.usuarios.id;


--
-- Name: usuarios_insignias; Type: TABLE; Schema: public; Owner: questcash
--

CREATE TABLE public.usuarios_insignias (
    id integer NOT NULL,
    usuario_id integer NOT NULL,
    insignia_id integer NOT NULL,
    fecha_obtenida timestamp without time zone
);


ALTER TABLE public.usuarios_insignias OWNER TO questcash;

--
-- Name: usuarios_insignias_id_seq; Type: SEQUENCE; Schema: public; Owner: questcash
--

CREATE SEQUENCE public.usuarios_insignias_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.usuarios_insignias_id_seq OWNER TO questcash;

--
-- Name: usuarios_insignias_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: questcash
--

ALTER SEQUENCE public.usuarios_insignias_id_seq OWNED BY public.usuarios_insignias.id;


--
-- Name: categorias_gasto id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.categorias_gasto ALTER COLUMN id SET DEFAULT nextval('public.categorias_gasto_id_seq'::regclass);


--
-- Name: gastos id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.gastos ALTER COLUMN id SET DEFAULT nextval('public.gastos_id_seq'::regclass);


--
-- Name: insignias id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.insignias ALTER COLUMN id SET DEFAULT nextval('public.insignias_id_seq'::regclass);


--
-- Name: movimientos id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.movimientos ALTER COLUMN id SET DEFAULT nextval('public.movimientos_id_seq'::regclass);


--
-- Name: participaciones_quest id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.participaciones_quest ALTER COLUMN id SET DEFAULT nextval('public.participaciones_quest_id_seq'::regclass);


--
-- Name: quests id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.quests ALTER COLUMN id SET DEFAULT nextval('public.quests_id_seq'::regclass);


--
-- Name: usuarios id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios ALTER COLUMN id SET DEFAULT nextval('public.usuarios_id_seq'::regclass);


--
-- Name: usuarios_insignias id; Type: DEFAULT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios_insignias ALTER COLUMN id SET DEFAULT nextval('public.usuarios_insignias_id_seq'::regclass);


--
-- Data for Name: categorias_gasto; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.categorias_gasto (id, nombre, tipo, color) FROM stdin;
\.


--
-- Data for Name: gastos; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.gastos (id, usuario_id, categoria_id, monto, descripcion, fecha, metodo_pago, es_hormiga) FROM stdin;
\.


--
-- Data for Name: insignias; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.insignias (id, codigo, nombre, descripcion, rareza, icono) FROM stdin;
1	PRIMER_AHORRO	Primer ahorro registrado	Registraste tu primer aporte de ahorro.	común	primer_ahorro.png
2	PRIMERA_META	Primera meta creada	Creaste tu primera meta en QuestCash.	rara	Primera_meta.png
3	PRIMER_RETO	Primer reto completado	Completaste tu primer reto de ahorro.	épica	primer_reto.png
4	AHORRO_1000	Has ahorrado $1,000 MXN	Alcanzaste un total acumulado de $1,000 MXN.	legendaria	Ahorro_1000.png
5	META_A_TIEMPO	Meta cumplida a tiempo	Completaste un reto antes o justo en la fecha límite.	mítica	Meta_tiempo.png
\.


--
-- Data for Name: movimientos; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.movimientos (id, tipo, monto, fecha, nota, categoria, usuario_id, quest_id) FROM stdin;
\.


--
-- Data for Name: participaciones_quest; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.participaciones_quest (id, rol, fecha_union, usuario_id, quest_id) FROM stdin;
\.


--
-- Data for Name: quests; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.quests (id, nombre, descripcion, monto_objetivo, monto_actual, fecha_limite, fecha_creacion, dificultad, estatus, puntos_recompensa, puntos_otorgados, es_colaborativo, tipo, usuario_id) FROM stdin;
\.


--
-- Data for Name: usuarios; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.usuarios (id, nombre, correo, password_hash, fecha_registro, puntos_totales, alias, foto_perfil, notif_ia, notif_fechas, notif_progreso) FROM stdin;
\.


--
-- Data for Name: usuarios_insignias; Type: TABLE DATA; Schema: public; Owner: questcash
--

COPY public.usuarios_insignias (id, usuario_id, insignia_id, fecha_obtenida) FROM stdin;
\.


--
-- Name: categorias_gasto_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.categorias_gasto_id_seq', 1, false);


--
-- Name: gastos_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.gastos_id_seq', 1, false);


--
-- Name: insignias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.insignias_id_seq', 5, true);


--
-- Name: movimientos_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.movimientos_id_seq', 1, false);


--
-- Name: participaciones_quest_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.participaciones_quest_id_seq', 1, false);


--
-- Name: quests_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.quests_id_seq', 1, false);


--
-- Name: usuarios_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.usuarios_id_seq', 1, false);


--
-- Name: usuarios_insignias_id_seq; Type: SEQUENCE SET; Schema: public; Owner: questcash
--

SELECT pg_catalog.setval('public.usuarios_insignias_id_seq', 1, false);


--
-- Name: categorias_gasto categorias_gasto_nombre_key; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.categorias_gasto
    ADD CONSTRAINT categorias_gasto_nombre_key UNIQUE (nombre);


--
-- Name: categorias_gasto categorias_gasto_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.categorias_gasto
    ADD CONSTRAINT categorias_gasto_pkey PRIMARY KEY (id);


--
-- Name: gastos gastos_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.gastos
    ADD CONSTRAINT gastos_pkey PRIMARY KEY (id);


--
-- Name: insignias insignias_codigo_key; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.insignias
    ADD CONSTRAINT insignias_codigo_key UNIQUE (codigo);


--
-- Name: insignias insignias_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.insignias
    ADD CONSTRAINT insignias_pkey PRIMARY KEY (id);


--
-- Name: movimientos movimientos_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.movimientos
    ADD CONSTRAINT movimientos_pkey PRIMARY KEY (id);


--
-- Name: participaciones_quest participaciones_quest_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.participaciones_quest
    ADD CONSTRAINT participaciones_quest_pkey PRIMARY KEY (id);


--
-- Name: quests quests_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.quests
    ADD CONSTRAINT quests_pkey PRIMARY KEY (id);


--
-- Name: usuarios_insignias uq_usuario_insignia; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios_insignias
    ADD CONSTRAINT uq_usuario_insignia UNIQUE (usuario_id, insignia_id);


--
-- Name: participaciones_quest uq_usuario_quest; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.participaciones_quest
    ADD CONSTRAINT uq_usuario_quest UNIQUE (usuario_id, quest_id);


--
-- Name: usuarios usuarios_correo_key; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_correo_key UNIQUE (correo);


--
-- Name: usuarios_insignias usuarios_insignias_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios_insignias
    ADD CONSTRAINT usuarios_insignias_pkey PRIMARY KEY (id);


--
-- Name: usuarios usuarios_pkey; Type: CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios
    ADD CONSTRAINT usuarios_pkey PRIMARY KEY (id);


--
-- Name: gastos gastos_categoria_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.gastos
    ADD CONSTRAINT gastos_categoria_id_fkey FOREIGN KEY (categoria_id) REFERENCES public.categorias_gasto(id);


--
-- Name: gastos gastos_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.gastos
    ADD CONSTRAINT gastos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: movimientos movimientos_quest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.movimientos
    ADD CONSTRAINT movimientos_quest_id_fkey FOREIGN KEY (quest_id) REFERENCES public.quests(id);


--
-- Name: movimientos movimientos_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.movimientos
    ADD CONSTRAINT movimientos_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: participaciones_quest participaciones_quest_quest_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.participaciones_quest
    ADD CONSTRAINT participaciones_quest_quest_id_fkey FOREIGN KEY (quest_id) REFERENCES public.quests(id);


--
-- Name: participaciones_quest participaciones_quest_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.participaciones_quest
    ADD CONSTRAINT participaciones_quest_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: quests quests_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.quests
    ADD CONSTRAINT quests_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- Name: usuarios_insignias usuarios_insignias_insignia_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios_insignias
    ADD CONSTRAINT usuarios_insignias_insignia_id_fkey FOREIGN KEY (insignia_id) REFERENCES public.insignias(id);


--
-- Name: usuarios_insignias usuarios_insignias_usuario_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: questcash
--

ALTER TABLE ONLY public.usuarios_insignias
    ADD CONSTRAINT usuarios_insignias_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuarios(id);


--
-- PostgreSQL database dump complete
--

\unrestrict kc661f5W46lQTBohHAquAWDVhfekAZk5BPdNc4wf05JUM5PVMwsrg1SJ0PU73CT

