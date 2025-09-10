
import io, os, re, smtplib, ssl, tempfile
from email.message import EmailMessage
from datetime import datetime, date

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from PIL import Image


# === UI Theme CSS (lightweight) ===
CUSTOM_CSS = '''
<style>
.block-container{max-width:1200px; padding-top:1rem;}
.app-hero{display:flex; align-items:center; gap:14px; padding:14px 18px; border-radius:14px;
background: linear-gradient(90deg, #0a7b8318, transparent); border:1px solid #0a7b8322;}
.app-hero h1{margin:0; font-size:34px; line-height:1.1; letter-spacing:.2px;}
.app-hero .sub{color:#334155; margin-top:4px; font-size:13px;}
.stButton>button{background:#0a7b83; color:#fff; border:0; border-radius:12px; padding:10px 16px; font-weight:600;}
.stButton>button:hover{filter:brightness(.95);}
.stExpander{border:1px solid #e2e8f0; border-radius:12px;}
[data-testid="stMetricValue"]{color:#0a7b83;}
</style>
'''

# ====== Config ======
DB_URL = "sqlite:///rnc.db"
engine = create_engine(DB_URL, poolclass=NullPool, future=True)
QUALITY_PASS = os.getenv("QUALITY_PASS", "qualidade123")

# Email (configure em Secrets do Streamlit Cloud)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

# ====== DB ======
def init_db():
    with engine.begin() as conn:
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS inspecoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TIMESTAMP NULL,
            rnc_num TEXT,
            emitente TEXT,
            area TEXT,
            pep TEXT,
            titulo TEXT,
            responsavel TEXT,
            descricao TEXT,
            referencias TEXT,
            causador TEXT,
            processo_envolvido TEXT,
            origem TEXT,
            acao_correcao TEXT,
            severidade TEXT,
            categoria TEXT,
            acoes TEXT,
            status TEXT DEFAULT 'Aberta',
            encerrada_em TIMESTAMP NULL,
            encerrada_por TEXT,
            encerramento_obs TEXT,
            eficacia TEXT,
            responsavel_acao TEXT,
            reaberta_em TIMESTAMP NULL,
            reaberta_por TEXT,
            reabertura_motivo TEXT
        );""")
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspecao_id INTEGER NOT NULL,
            blob BLOB NOT NULL,
            filename TEXT,
            mimetype TEXT,
            tipo TEXT CHECK(tipo IN ('abertura','encerramento','reabertura')) DEFAULT 'abertura'
        );""")
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS peps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE
        );""")
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            blob BLOB,
            text TEXT
        );""")
        for ddl in [
            "ALTER TABLE inspecoes ADD COLUMN referencias TEXT",
            "ALTER TABLE inspecoes ADD COLUMN causador TEXT",
            "ALTER TABLE inspecoes ADD COLUMN processo_envolvido TEXT",
            "ALTER TABLE inspecoes ADD COLUMN origem TEXT",
            "ALTER TABLE inspecoes ADD COLUMN acao_correcao TEXT",
            "ALTER TABLE inspecoes ADD COLUMN rnc_num TEXT",
            "ALTER TABLE inspecoes ADD COLUMN emitente TEXT",
            "ALTER TABLE inspecoes ADD COLUMN pep TEXT"
        ]:
            try: conn.exec_driver_sql(ddl)
            except Exception: pass

def get_pep_list():
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT code FROM peps ORDER BY code"), conn)
    return df["code"].tolist() if not df.empty else []

def add_peps_bulk(codes:list):
    codes = [c.strip() for c in codes if c and c.strip()]
    if not codes: return 0
    ins = 0
    with engine.begin() as conn:
        for code in codes:
            try:
                conn.execute(text("INSERT OR IGNORE INTO peps (code) VALUES (:c)"), {"c": code})
                ins += 1
            except Exception:
                pass
    return ins

def settings_set_logo(image_bytes: bytes):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO settings(key, blob) VALUES('logo', :b) ON CONFLICT(key) DO UPDATE SET blob=excluded.blob"), {"b": image_bytes})

def settings_get_logo():
    with engine.begin() as conn:
        row = conn.execute(text("SELECT blob FROM settings WHERE key='logo'")).fetchone()
    return row[0] if row else None

def next_rnc_num_for_date(d:date) -> str:
    year = d.year
    prefix = f"{year}-"
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT rnc_num FROM inspecoes WHERE rnc_num LIKE :p"), {"p": f"{prefix}%"}).fetchall()
    seqs = []
    for (val,) in rows:
        if not val: continue
        m = re.match(rf"^{year}-(\d+)$", str(val).strip())
        if m:
            try: seqs.append(int(m.group(1)))
            except: pass
    nxt = (max(seqs)+1) if seqs else 1
    return f"{year}-{nxt:03d}"

def insert_inspecao(rec, images: list):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO inspecoes (data, rnc_num, emitente, area, pep, titulo, responsavel, descricao, referencias,
                                   causador, processo_envolvido, origem, acao_correcao,
                                   severidade, categoria, acoes, status, responsavel_acao)
            VALUES (:data, :rnc_num, :emitente, :area, :pep, :titulo, :responsavel, :descricao, :referencias,
                    :causador, :processo_envolvido, :origem, :acao_correcao,
                    :severidade, :categoria, :acoes, :status, :responsavel_acao)
        """), rec)
        iid = conn.execute(text("SELECT last_insert_rowid()")).scalar_one()
        for img in images:
            conn.execute(text("""
                INSERT INTO fotos (inspecao_id, blob, filename, mimetype, tipo)
                VALUES (:iid, :blob, :name, :mime, 'abertura')
            """), {"iid": iid, "blob": img["blob"], "name": img["name"], "mime": img["mime"]})
        return iid

def add_photos(iid:int, images:list, tipo:str):
    with engine.begin() as conn:
        for img in images:
            conn.execute(text("""
                INSERT INTO fotos (inspecao_id, blob, filename, mimetype, tipo)
                VALUES (:iid, :blob, :name, :mime, :tipo)
            """), {"iid": iid, "blob": img["blob"], "name": img["name"], "mime": img["mime"], "tipo": tipo})

def fetch_df():
    with engine.begin() as conn:
        df = pd.read_sql(text("""
            SELECT id, data, rnc_num, emitente, area, pep, titulo, responsavel,
                   severidade, categoria, status, descricao, referencias,
                   causador, processo_envolvido, origem, acao_correcao,
                   acoes, encerrada_em, encerrada_por, encerramento_obs, eficacia,
                   responsavel_acao, reaberta_em, reaberta_por, reabertura_motivo
            FROM inspecoes
            ORDER BY id DESC
        """), conn)
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.date
    return df

def fetch_photos(iid:int, tipo:str):
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT id, blob, filename, mimetype FROM fotos WHERE inspecao_id=:iid AND tipo=:tipo ORDER BY id"),
                         conn, params={"iid": iid, "tipo": tipo})
    return df.to_dict("records") if not df.empty else []

def encerrar_inspecao(iid:int, por:str, obs:str, eficacia:str, images:list):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE inspecoes
               SET status='Encerrada',
                   encerrada_em=:dt,
                   encerrada_por=:por,
                   encerramento_obs=:obs,
                   eficacia=:ef
             WHERE id=:iid
        """), {"dt": datetime.now(), "por": por, "obs": obs, "ef": eficacia, "iid": iid})
    if images:
        add_photos(iid, images, "encerramento")

def reabrir_inspecao(iid:int, por:str, motivo:str, images:list):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE inspecoes
               SET status='Em ação',
                   reaberta_em=:dt,
                   reaberta_por=:por,
                   reabertura_motivo=:motivo
             WHERE id=:iid
        """), {"dt": datetime.now(), "por": por, "motivo": motivo, "iid": iid})
    if images:
        add_photos(iid, images, "reabertura")

# ====== Emails ======
def email_enabled():
    return all([SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO])

def send_email(subject: str, body: str):
    if not email_enabled():
        return False, "E-mail não configurado (defina SMTP_* e EMAIL_*)."
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        msg.set_content(body)

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True, "ok"
    except Exception as e:
        return False, str(e)

# ====== PDF (ReportLab) ======
def generate_pdf(iid:int) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    df = fetch_df()
    row = df[df["id"] == iid].iloc[0].to_dict()

    fd, path = tempfile.mkstemp(suffix=f"_RNC_{row.get('rnc_num','')}.pdf")
    os.close(fd)
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4

    y = H - 20*mm
    logo_blob = settings_get_logo()
    if logo_blob:
        try:
            img = ImageReader(io.BytesIO(logo_blob))
            c.drawImage(img, 15*mm, y-15*mm, width=35*mm, height=15*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    c.setFont("Helvetica-Bold", 14)
    c.drawString(60*mm, y, "RNC - RELATÓRIO DE NÃO CONFORMIDADE")

    c.setFont("Helvetica", 9)
    y -= 10*mm
    c.drawString(15*mm, y, f"RNC Nº: {row.get('rnc_num') or '-'}")
    c.drawString(70*mm, y, f"Data: {row.get('data') or '-'}")
    c.drawString(115*mm, y, f"Emitente: {row.get('emitente') or '-'}")
    y -= 6*mm
    c.drawString(15*mm, y, f"Área/Local: {row.get('area') or '-'}")
    c.drawString(115*mm, y, f"Severidade: {row.get('severidade') or '-'}")
    y -= 6*mm
    c.drawString(15*mm, y, f"PEP: {row.get('pep') or '-'}")
    c.drawString(115*mm, y, f"Categoria: {row.get('categoria') or '-'}")

    def draw_block(title, text, y_start):
        from reportlab.lib.pagesizes import A4
        W, H = A4
        c.setFont("Helvetica-Bold", 10)
        c.drawString(15*mm, y_start, title)
        c.setFont("Helvetica", 9)
        max_width = W - 30*mm
        ypos = y_start - 4*mm
        for line in break_lines(str(text or "-"), c, max_width):
            c.drawString(15*mm, ypos, line)
            ypos -= 5*mm
            if ypos < 20*mm:
                c.showPage(); ypos = H - 20*mm
        return ypos

    def break_lines(text, canv, max_w):
        words = str(text).split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if canv.stringWidth(test, "Helvetica", 9) <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines or ["-"]

    y = draw_block("Descrição da não conformidade:", row.get("descricao"), y - 10*mm)
    y = draw_block("Referências:", row.get("referencias"), y - 6*mm)
    y = draw_block("Causador:", row.get("causador"), y - 6*mm)
    y = draw_block("Processo envolvido:", row.get("processo_envolvido"), y - 6*mm)
    y = draw_block("Origem:", row.get("origem"), y - 6*mm)
    y = draw_block("Ação de correção:", row.get("acao_correcao"), y - 6*mm)

    for tipo, titulo in [("abertura","Fotos da abertura"), ("encerramento","Evidências de encerramento"), ("reabertura","Fotos da reabertura")]:
        pics = fetch_photos(iid, tipo)
        if not pics: continue
        c.setFont("Helvetica-Bold", 10)
        c.drawString(15*mm, y - 4*mm, titulo + ":")
        y -= 10*mm
        x = 15*mm
        for rec in pics:
            try:
                img = ImageReader(io.BytesIO(rec["blob"]))
                iw, ih = img.getSize()
                w, h = 60*mm, 45*mm
                if x + w > W - 15*mm:
                    x = 15*mm
                    y -= (h + 6*mm)
                if y < 25*mm:
                    c.showPage(); y = H - 25*mm; x = 15*mm
                c.drawImage(img, x, y - h, width=w, height=h, preserveAspectRatio=True, anchor='sw', mask='auto')
                x += (w + 6*mm)
            except Exception:
                continue
        y -= 55*mm

    c.showPage()
    c.save()
    return path

# ====== CSV Import Helpers ======
EXPECTED_COLS = [
    "id","data","rnc_num","emitente","area","pep","titulo","responsavel",
    "descricao","referencias","causador","processo_envolvido","origem","acao_correcao",
    "severidade","categoria","acoes","status","encerrada_em","encerrada_por",
    "encerramento_obs","eficacia","responsavel_acao","reaberta_em","reaberta_por","reabertura_motivo"
]

def normalize_df_cols(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "rnc nº": "rnc_num", "rnc_no": "rnc_num", "rnc_no.": "rnc_num", "rnc_numero": "rnc_num", "rnc": "rnc_num",
        "responsavel_inspecao": "responsavel", "responsável": "responsavel",
        "categoria_risco": "severidade",
        "pep_descricao": "pep"
    }
    new_cols = []
    for c in df.columns:
        key = str(c).strip().lower().replace(" ", "_")
        key = aliases.get(key, key)
        new_cols.append(key)
    df.columns = new_cols
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None
    df = df[EXPECTED_COLS]
    for dtcol in ["data","encerrada_em","reaberta_em"]:
        df[dtcol] = pd.to_datetime(df[dtcol], errors="coerce")
    return df

def upsert_from_csv(df: pd.DataFrame) -> int:
    n = 0
    with engine.begin() as conn:
        existing = pd.read_sql(text("SELECT id, rnc_num FROM inspecoes"), conn)
        exist_map = {str(r).strip(): i for i, r in zip(existing["id"], existing["rnc_num"].fillna("").astype(str))}
        for _, row in df.iterrows():
            rnc_key = str(row.get("rnc_num") or "").strip()
            rec = {k: (None if pd.isna(v) else v) for k, v in row.items() if k in EXPECTED_COLS and k != "id"}
            for k in ["data","encerrada_em","reaberta_em"]:
                if isinstance(rec.get(k), pd.Timestamp):
                    rec[k] = rec[k].to_pydatetime()
            if rnc_key and rnc_key in exist_map:
                rec["id"] = int(exist_map[rnc_key])
                sets = ", ".join([f"{k}=:{k}" for k in rec.keys() if k != "id"])
                conn.execute(text(f"UPDATE inspecoes SET {sets} WHERE id=:id"), rec)
            else:
                cols = [k for k in EXPECTED_COLS if k not in ["id"]]
                cols_sql = ", ".join(cols)
                vals_sql = ", ".join([f":{k}" for k in cols])
                conn.execute(text(f"INSERT INTO inspecoes ({cols_sql}) VALUES ({vals_sql})"), rec)
            n += 1
    return n

# ====== UI & Auth ======
st.set_page_config(page_title="Registro de Não Conformidades (RNC) — v2.7", page_icon="📝", layout="wide")
st.sidebar.title("RNC — v2.7")
st.sidebar.caption("RNC Nº automático • PDF • Logo • E-mail • Importar CSV")

init_db()


st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if "is_quality" not in st.session_state:
    st.session_state.is_quality = False

with st.sidebar.expander("🔐 Entrar (Qualidade) — cadastrar/editar"):
    pwd = st.text_input("Senha (Quality)", type="password", placeholder="Informe a senha")
    if st.button("Entrar como Qualidade"):
        if pwd == QUALITY_PASS:
            st.session_state.is_quality = True
            st.success("Perfil Qualidade ativo.")
        else:
            st.error("Senha incorreta.")
    if st.session_state.is_quality and st.button("Sair"):
        st.session_state.is_quality = False
        st.info("Agora você está como Visitante.")

# Logo uploader
with st.sidebar.expander("🖼️ Logo da empresa (para PDF e topo)"):
    from PIL import Image as PILImage
    logo_bytes = settings_get_logo()
    if logo_bytes:
        st.image(PILImage.open(io.BytesIO(logo_bytes)), caption="Logo atual", width=180)
    if st.session_state.is_quality:
        up_logo = st.file_uploader("Enviar nova logo (PNG/JPG)", type=["png","jpg","jpeg"])
        if up_logo is not None:
            settings_set_logo(up_logo.getbuffer().tobytes())
            st.success("Logo atualizada! Recarregue a página para ver.")

# Menu
if st.session_state.is_quality:
    menu = st.sidebar.radio("Navegação", ["Nova RNC", "Consultar/Encerrar/Reabrir", "Importar/Exportar", "Gerenciar PEPs"], label_visibility="collapsed")
else:
    menu = st.sidebar.radio("Navegação", ["Consultar/Encerrar/Reabrir", "Importar/Exportar"], label_visibility="collapsed")

def files_to_images(uploaded_files):
    out = []
    for up in uploaded_files or []:
        try:
            blob = up.getbuffer().tobytes()
            out.append({"blob": blob, "name": up.name, "mime": up.type or "image/jpeg"})
        except Exception:
            pass
    return out

def show_image_from_blob(blob_bytes, width=360):
    try:
        im = Image.open(io.BytesIO(blob_bytes))
        st.image(im, width=width)
    except Exception:
        st.caption("Não foi possível exibir esta imagem.")

CAUSADOR_OPTS = ["Solda","Pintura","Engenharia","Fornecedor","Cliente","Caldeiraria","Usinagem","Planejamento","Qualidade","R.H","Outros"]
PROCESSO_OPTS = ["Comercial","Compras","Planejamento","Recebimento","Produção","Inspeção Final","Segurança","Meio Ambiente","5S","R.H","Outros"]
ORIGEM_OPTS = ["Pintura","Orçamento","Usinagem","Almoxarifado","Solda","Montagem","Cliente","Expedição","Preparação","R.H","Outros"]
ACAO_CORRECAO_OPTS = ["Refugo","Retrabalho","Aceitar sob concessão","Comunicar ao fornecedor","Ver e agir","Limpeza","Manutenção","Solicitação de compra"]

def join_list(lst):
    return "; ".join([x for x in lst if x])

def next_rnc_preview(d):
    try:
        return next_rnc_num_for_date(d)
    except Exception:
        return "prévia indisponível"

# ====== Nova RNC ======
if menu == "Nova RNC":
    st.header("Nova RNC (RNC Nº automático)")
    blob = settings_get_logo()
    if blob:
        st.image(Image.open(io.BytesIO(blob)), width=220)

    with st.form("form_rnc"):
        col0, col1, col2 = st.columns(3)
        with col0:
            emitente = st.text_input("Emitente", placeholder="Seu nome")
        with col1:
            data_insp = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")
        with col2:
            st.text_input("RNC Nº (gerado automaticamente)", value=next_rnc_preview(data_insp), disabled=True)

        col4, col5, col6 = st.columns(3)
        with col4:
            area = st.text_input("Área/Local", placeholder="Ex.: Correia TR-2011KS-07")
        with col5:
            categoria = st.selectbox("Categoria", ["Segurança","Qualidade","Meio Ambiente","Operação","Manutenção","Outros"])
        with col6:
            severidade = st.selectbox("Severidade", ["Baixa","Média","Alta","Crítica"])

        with st.expander("PEP (código — descrição)"):
            pep_list = get_pep_list()
            pep_choice = st.selectbox("Selecionar", options=(pep_list + ["Outro"]))
            pep_outro = st.text_input("Informe PEP (código — descrição)", value="") if pep_choice == "Outro" else ""
            pep_final = pep_outro.strip() if pep_choice == "Outro" else pep_choice

        causador = st.multiselect("Causador", CAUSADOR_OPTS)
        processo = st.multiselect("Processo envolvido", PROCESSO_OPTS)
        origem = st.multiselect("Origem", ORIGEM_OPTS)

        titulo = st.text_input("Título", placeholder="Resumo curto da não conformidade")
        descricao = st.text_area("Descrição da não conformidade", height=160)
        referencias = st.text_area("Referências", placeholder="Normas/procedimentos/desenhos aplicáveis", height=90)
        acao_correcao = st.multiselect("Ação de correção", ACAO_CORRECAO_OPTS)

        responsavel = st.text_input("Responsável pela inspeção", placeholder="Quem identificou")
        responsavel_acao = st.text_input("Responsável pela ação corretiva", placeholder="Quem vai executar")

        fotos = st.file_uploader("Fotos da abertura (JPG/PNG)", type=["jpg","jpeg","png"], accept_multiple_files=True)

        submitted = st.form_submit_button("Salvar RNC")
        if submitted:
            rnc_num = next_rnc_num_for_date(data_insp)
            imgs = files_to_images(fotos)
            rec = {
                "data": datetime.combine(data_insp, datetime.min.time()),
                "rnc_num": rnc_num,
                "emitente": emitente.strip(),
                "area": area.strip(),
                "pep": pep_final or None,
                "titulo": titulo.strip(),
                "responsavel": responsavel.strip(),
                "descricao": descricao.strip(),
                "referencias": referencias.strip(),
                "causador": join_list(causador),
                "processo_envolvido": join_list(processo),
                "origem": join_list(origem),
                "acao_correcao": join_list(acao_correcao),
                "severidade": severidade,
                "categoria": categoria,
                "acoes": "",
                "status": "Aberta",
                "responsavel_acao": responsavel_acao.strip(),
            }
            iid = insert_inspecao(rec, imgs)
            st.success(f"RNC salva! Nº {rnc_num} • Código interno: #{iid}")

            subject = f"[RNC ABERTA] Nº {rnc_num} — {titulo}"
            link = APP_BASE_URL or "(defina APP_BASE_URL para link)"
            body = f"""Uma nova RNC foi registrada.

RNC Nº: {rnc_num}
Data: {data_insp}
Emitente: {emitente}
Área: {area}
PEP: {pep_final}
Título: {titulo}
Severidade: {severidade}
Categoria: {categoria}

Acesse: {link}
"""
            ok, msg = send_email(subject, body)
            if ok: st.info("E-mail de abertura enviado.")
            else: st.warning(f"E-mail não enviado: {msg} (configure SMTP_* e EMAIL_*).")

# ====== Consultar / Encerrar / Reabrir ======
elif menu == "Consultar/Encerrar/Reabrir":
    st.header("Consulta de RNCs")
    df = fetch_df()

    colf1, colf2, colf3, colf4, colf5 = st.columns(5)
    with colf1:
        f_status = st.multiselect("Status", ["Aberta","Em análise","Em ação","Bloqueada","Encerrada"])
    with colf2:
        f_sev = st.multiselect("Severidade", ["Baixa","Média","Alta","Crítica"])
    with colf3:
        f_area = st.text_input("Filtrar por Área/Local")
    with colf4:
        f_resp = st.text_input("Filtrar por Responsável")
    with colf5:
        f_pep = st.text_input("Filtrar por PEP")

    if not df.empty:
        if f_status: df = df[df["status"].isin(f_status)]
        if f_sev: df = df[df["severidade"].isin(f_sev)]
        if f_area: df = df[df["area"].str.contains(f_area, case=False, na=False)]
        if f_resp: df = df[df["responsavel"].str.contains(f_resp, case=False, na=False)]
        if f_pep: df = df[df["pep"].fillna("").str.contains(f_pep, case=False, na=False)]

        st.dataframe(df[["id","data","rnc_num","emitente","pep","area","titulo","responsavel",
                         "severidade","categoria","status","encerrada_em","reaberta_em"]],
                     use_container_width=True, hide_index=True)

        st.markdown("---")
        if not df.empty:
            sel_id = st.number_input("Ver RNC (ID)", min_value=int(df["id"].min()), max_value=int(df["id"].max()), value=int(df["id"].iloc[0]), step=1)
            if sel_id in df["id"].values:
                row = df[df["id"] == sel_id].iloc[0].to_dict()
                st.subheader(f"RNC Nº {row.get('rnc_num') or '-'} — {row['titulo']} [{row['status']}]")

                if st.button("📄 Gerar PDF desta RNC"):
                    path = generate_pdf(int(row["id"]))
                    with open(path, "rb") as f:
                        st.download_button("Baixar PDF", f, file_name=f"RNC_{row.get('rnc_num') or row['id']}.pdf", mime="application/pdf")
                    st.caption("PDF gerado com logo (se configurada) e fotos.")

                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("Data", str(row["data"]))
                c2.metric("Severidade", row["severidade"])
                c3.metric("Status", row["status"])
                c4.metric("PEP", row.get("pep") or "-")
                c5.metric("RNC Nº", row.get("rnc_num") or "-")
                c6.metric("Emitente", row.get("emitente") or "-")
                st.write(f"**Área/Local:** {row['area']}  \n**Resp. inspeção:** {row['responsavel']}  \n**Resp. ação corretiva:** {row.get('responsavel_acao') or '-'}  \n**Categoria:** {row['categoria']}")
                st.markdown("**Descrição**")
                st.write(row["descricao"] or "-")
                st.markdown("**Referências**")
                st.write(row.get("referencias") or "-")
                st.markdown("**Causador / Processo envolvido / Origem**")
                st.write(f"- **Causador:** {row.get('causador') or '-'}")
                st.write(f"- **Processo:** {row.get('processo_envolvido') or '-'}")
                st.write(f"- **Origem:** {row.get('origem') or '-'}")
                st.markdown("**Ação de correção**")
                st.write(row.get("acao_correcao") or "-")

                tabs = st.tabs(["📸 Abertura", "✅ Encerramento", "♻️ Reabertura"])
                with tabs[0]:
                    for rec in fetch_photos(int(row["id"]), "abertura"):
                        show_image_from_blob(rec["blob"])
                with tabs[1]:
                    enc = fetch_photos(int(row["id"]), "encerramento")
                    if enc:
                        for rec in enc:
                            show_image_from_blob(rec["blob"])
                    else:
                        st.caption("Sem evidências de encerramento.")
                with tabs[2]:
                    rea = fetch_photos(int(row["id"]), "reabertura")
                    if rea:
                        for rec in rea:
                            show_image_from_blob(rec["blob"])
                    else:
                        st.caption("Sem registros de reabertura.")

                if st.session_state.is_quality:
                    st.markdown("---")
                    colA, colB = st.columns(2)
                    with colA:
                        st.subheader("Encerrar RNC")
                        can_close = row["status"] != "Encerrada"
                        with st.form(f"encerrar_{sel_id}"):
                            encerr_por = st.text_input("Encerrada por", placeholder="Nome de quem encerra")
                            encerr_obs = st.text_area("Observações de encerramento", placeholder="O que foi feito? Ação definitiva?")
                            eficacia = st.selectbox("Verificação de eficácia", ["A verificar","Eficaz","Não eficaz"])
                            fotos_enc = st.file_uploader("Evidências (fotos)", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"enc_{sel_id}")
                            sub = st.form_submit_button("Encerrar RNC", disabled=not can_close)
                            if sub:
                                imgs = files_to_images(fotos_enc)
                                encerrar_inspecao(int(row["id"]), encerr_por.strip(), encerr_obs.strip(), eficacia, imgs)
                                st.success("RNC encerrada. Recarregue para ver o novo status.")
                                subject = f"[RNC ENCERRADA] Nº {row.get('rnc_num') or row['id']} — {row['titulo']}"
                                link = APP_BASE_URL or "(defina APP_BASE_URL para link)"
                                body = f"""RNC encerrada.

RNC Nº: {row.get('rnc_num')}
Encerrada por: {encerr_por}
Eficácia: {eficacia}
Observações: {encerr_obs}

Acesse: {link}
"""
                                ok, msg = send_email(subject, body)
                                if ok: st.info("E-mail de encerramento enviado.")
                                else: st.warning(f"E-mail não enviado: {msg}")

                    with colB:
                        st.subheader("Reabrir RNC")
                        can_reopen = row["status"] == "Encerrada"
                        with st.form(f"reabrir_{sel_id}"):
                            reab_por = st.text_input("Reaberta por", placeholder="Nome de quem reabre")
                            reab_motivo = st.text_area("Motivo da reabertura", placeholder="Ex.: eficácia não comprovada")
                            fotos_reab = st.file_uploader("Fotos (opcional)", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"reab_{sel_id}")
                            sub2 = st.form_submit_button("Reabrir RNC", disabled=not can_reopen)
                            if sub2:
                                imgs = files_to_images(fotos_reab)
                                reabrir_inspecao(int(row["id"]), reab_por.strip(), reab_motivo.strip(), imgs)
                                st.success("RNC reaberta. Status voltou para 'Em ação'.")

# ====== Importar / Exportar ======
elif menu == "Importar/Exportar":
    st.header("Importar / Exportar (CSV)")

    if st.session_state.is_quality:
        st.subheader("Importar CSV para restaurar/atualizar RNCs")
        up = st.file_uploader("Selecione o CSV (ponto e vírgula ou vírgula)", type=["csv"], key="csv_imp")
        if up is not None:
            try:
                df_imp = pd.read_csv(up)
            except Exception:
                up.seek(0)
                df_imp = pd.read_csv(up, sep=";")
            df_norm = normalize_df_cols(df_imp)
            count = upsert_from_csv(df_norm)
            st.success(f"{count} registro(s) importado(s)/atualizado(s).")

    st.subheader("Exportar CSV")
    df = fetch_df()
    if df.empty:
        st.info("Sem dados para exportar.")
    else:
        csv_bytes = df.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button("Baixar CSV", data=csv_bytes, file_name="rnc_export_v2_7.csv", mime="text/csv")

# ====== Gerenciar PEPs ======
elif menu == "Gerenciar PEPs":
    st.header("Gerenciar PEPs (Qualidade)")
    st.caption("Importe ou adicione itens como 'C023553 — ADEQ. ...' para aparecer na lista.")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Adicionar manualmente")
        new_pep = st.text_input("Novo PEP (código — descrição)", placeholder="Ex.: C023553 — ADEQ. ...")
        if st.button("Adicionar PEP"):
            if new_pep.strip():
                n = add_peps_bulk([new_pep.strip()])
                if n: st.success("PEP adicionado.")
                else: st.warning("Este PEP já existe ou é inválido.")
    with col2:
        st.subheader("Importar lista (CSV)")
        up = st.file_uploader("Arquivo CSV com uma coluna chamada 'code'", type=["csv"])
        if up is not None:
            try:
                df_csv = pd.read_csv(up)
            except Exception:
                up.seek(0)
                df_csv = pd.read_csv(up, sep=";")
            if "code" in df_csv.columns:
                n = add_peps_bulk(df_csv["code"].astype(str).tolist())
                st.success(f"{n} PEP(s) importado(s).")
            else:
                st.error("CSV deve conter uma coluna chamada 'code'.")
    st.markdown("---")
    st.subheader("Lista atual de PEPs")
    with engine.begin() as conn:
        df_pep = pd.read_sql(text("SELECT code AS 'PEP — descrição' FROM peps ORDER BY code"), conn)
    st.dataframe(df_pep, use_container_width=True, hide_index=True)
