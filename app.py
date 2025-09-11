
import io, os, re, smtplib, ssl, tempfile
from email.message import EmailMessage
from datetime import datetime, date
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from PIL import Image

# ====== Minimal style ======
CUSTOM_CSS = """
<style>
.block-container{max-width:1200px; padding-top:1rem;}
.stButton>button{background:#0a7b83; color:#fff; border:0; border-radius:12px; padding:10px 16px; font-weight:600;}
.stButton>button:hover{filter:brightness(.95);}
.stExpander{border:1px solid #e2e8f0; border-radius:12px;}
[data-testid='stMetricValue']{color:#0a7b83;}
</style>
"""
st.set_page_config(page_title="RNC — v2.7.1 (v07)", page_icon="📝", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ====== Config ======
DB_URL = "sqlite:///rnc.db"
engine = create_engine(DB_URL, poolclass=NullPool, future=True)
QUALITY_PASS = os.getenv("QUALITY_PASS", "qualidade123")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = [e.strip() for e in os.getenv("EMAIL_TO", "").split(",") if e.strip()]
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

# ====== DB & Migrations ======
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
            reabertura_motivo TEXT,
            encerramento_desc TEXT,
            reabertura_desc TEXT,
            cancelada_em TIMESTAMP,
            cancelada_por TEXT,
            cancelamento_motivo TEXT
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
        CREATE TABLE IF NOT EXISTS peps (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE);""" )
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, blob BLOB, text TEXT);""" )

def settings_set_logo(image_bytes: bytes):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO settings(key, blob) VALUES('logo', :b) ON CONFLICT(key) DO UPDATE SET blob=excluded.blob"), {"b": image_bytes})

def settings_get_logo():
    with engine.begin() as conn:
        row = conn.execute(text("SELECT blob FROM settings WHERE key='logo'")).fetchone()
    return row[0] if row else None

def settings_clear_logo():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM settings WHERE key='logo'"))

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

def next_rnc_num_for_date(d:date) -> str:
    year = d.year
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT rnc_num FROM inspecoes WHERE rnc_num LIKE :p"), {"p": f"{year}-%"}).fetchall()
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

def fetch_df():
    with engine.begin() as conn:
        df = pd.read_sql(text("""
            SELECT id, data, rnc_num, emitente, area, pep, titulo, responsavel,
                   severidade, categoria, status, descricao, referencias,
                   causador, processo_envolvido, origem, acao_correcao,
                   acoes, encerrada_em, encerrada_por, encerramento_obs, eficacia,
                   responsavel_acao, reaberta_em, reaberta_por, reabertura_motivo,
                   encerramento_desc, reabertura_desc, cancelada_em, cancelada_por, cancelamento_motivo
            FROM inspecoes ORDER BY id DESC
        """), conn)
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.date
    return df

def fetch_photos(iid:int, tipo:str):
    with engine.begin() as conn:
        df = pd.read_sql(text("SELECT id, blob, filename, mimetype FROM fotos WHERE inspecao_id=:iid AND tipo=:tipo ORDER BY id"),
                         conn, params={"iid": iid, "tipo": tipo})
    return df.to_dict("records") if not df.empty else []

def add_photos(iid:int, images:list, tipo:str):
    with engine.begin() as conn:
        for img in images:
            conn.execute(text("""
                INSERT INTO fotos (inspecao_id, blob, filename, mimetype, tipo)
                VALUES (:iid, :blob, :name, :mime, :tipo)
            """), {"iid": iid, "blob": img["blob"], "name": img["name"], "mime": img["mime"], "tipo": tipo})

def encerrar_inspecao(iid:int, por:str, obs:str, eficacia:str, desc:str, images:list):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE inspecoes
               SET status='Encerrada',
                   encerrada_em=:dt,
                   encerrada_por=:por,
                   encerramento_obs=:obs,
                   eficacia=:ef,
                   encerramento_desc=:desc
             WHERE id=:iid
        """), {"dt": datetime.now(), "por": por, "obs": obs, "ef": efficacy_map(eficacia), "desc": desc, "iid": iid})
    if images:
        add_photos(iid, images, "encerramento")

def reabrir_inspecao(iid:int, por:str, motivo:str, desc:str, images:list):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE inspecoes
               SET status='Em ação',
                   reaberta_em=:dt,
                   reaberta_por=:por,
                   reabertura_motivo=:motivo,
                   reabertura_desc=:desc
             WHERE id=:iid
        """), {"dt": datetime.now(), "por": por, "motivo": motivo, "desc": desc, "iid": iid})
    if images:
        add_photos(iid, images, "reabertura")

def cancel_inspecao(iid:int, por:str, motivo:str):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE inspecoes
               SET status='Cancelada',
                   cancelada_em=:dt,
                   cancelada_por=:por,
                   cancelamento_motivo=:motivo
             WHERE id=:iid
        """), {"dt": datetime.now(), "por": por, "motivo": motivo, "iid": iid})

def delete_inspecao(iid:int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fotos WHERE inspecao_id=:iid"), {"iid": iid})
        conn.execute(text("DELETE FROM inspecoes WHERE id=:iid"), {"iid": iid})

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
        c.setFont("Helvetica-Bold", 10)
        c.drawString(15*mm, y_start, title)
        c.setFont("Helvetica", 9)
        maxw = W - 30*mm
        ypos = y_start - 4*mm
        for line in _wrap_text(str(text or "-"), c, maxw):
            c.drawString(15*mm, ypos, line)
            ypos -= 5*mm
            if ypos < 20*mm:
                c.showPage(); ypos = H - 20*mm
        return ypos

    def _wrap_text(text, canv, maxw):
        words = str(text).split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if canv.stringWidth(test, "Helvetica", 9) <= maxw:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines or ["-"]

    # Abertura
    y = draw_block("Descrição da não conformidade:", row.get("descricao"), y - 10*mm)
    y = draw_block("Referências:", row.get("referencias"), y - 6*mm)
    y = draw_block("Causador:", row.get("causador"), y - 6*mm)
    y = draw_block("Processo envolvido:", row.get("processo_envolvido"), y - 6*mm)
    y = draw_block("Origem:", row.get("origem"), y - 6*mm)
    y = draw_block("Ação de correção:", row.get("acao_correcao"), y - 6*mm)

    # Encerramento
    y = draw_block("Encerramento — observações:", row.get("encerramento_obs"), y - 8*mm)
    y = draw_block("Encerramento — descrição detalhada:", row.get("encerramento_desc"), y - 6*mm)
    y = draw_block("Eficácia:", row.get("eficacia"), y - 6*mm)
    y = draw_block("Encerrado por / Em:", f"{row.get('encerrada_por') or '-'} / {row.get('encerrada_em') or '-'}", y - 6*mm)

    # Reabertura
    y = draw_block("Reabertura — motivo:", row.get("reabertura_motivo"), y - 8*mm)
    y = draw_block("Reabertura — descrição detalhada:", row.get("reabertura_desc"), y - 6*mm)
    y = draw_block("Reaberta por / Em:", f"{row.get('reaberta_por') or '-'} / {row.get('reaberta_em') or '-'}", y - 6*mm)

    # Cancelamento
    if str(row.get("status")).lower() == "cancelada":
        y = draw_block("Cancelamento — motivo:", row.get("cancelamento_motivo"), y - 8*mm)
        y = draw_block("Cancelada por / Em:", f"{row.get('cancelada_por') or '-'} / {row.get('cancelada_em') or '-'}", y - 6*mm)

    # Fotos
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

def efficacy_map(val:str)->str:
    return {"A verificar":"A verificar", "Eficaz":"Eficaz", "Não eficaz":"Não eficaz"}.get(val, val or "")

# ====== CSV Import/Export helpers ======
EXPECTED_COLS = [
    "id","data","rnc_num","emitente","area","pep","titulo","responsavel",
    "descricao","referencias","causador","processo_envolvido","origem","acao_correcao",
    "severidade","categoria","acoes","status","encerrada_em","encerrada_por",
    "encerramento_obs","eficacia","responsavel_acao","reaberta_em","reaberta_por","reabertura_motivo",
    "encerramento_desc","reabertura_desc","cancelada_em","cancelada_por","cancelamento_motivo"
]

def normalize_df_cols(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {"rnc nº":"rnc_num","rnc_no":"rnc_num","rnc":"rnc_num","responsável":"responsavel","pep_descricao":"pep"}
    df.columns = [aliases.get(str(c).strip().lower().replace(" ","_"), str(c).strip().lower().replace(" ","_")) for c in df.columns]
    for c in EXPECTED_COLS:
        if c not in df.columns: df[c] = None
    df = df[EXPECTED_COLS]
    for dtcol in ["data","encerrada_em","reaberta_em","cancelada_em"]:
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
            for k in ["data","encerrada_em","reaberta_em","cancelada_em"]:
                if isinstance(rec.get(k), pd.Timestamp):
                    rec[k] = rec[k].to_pydatetime()
            if rnc_key and rnc_key in exist_map:
                rec["id"] = int(exist_map[rnc_key])
                sets = ", ".join([f"{k}=:{k}" for k in rec.keys() if k != "id"])
                conn.execute(text(f"UPDATE inspecoes SET {sets} WHERE id=:id"), rec)
            else:
                cols = [k for k in EXPECTED_COLS if k != "id"]
                conn.execute(text(f"INSERT INTO inspecoes ({', '.join(cols)}) VALUES ({', '.join(':'+k for k in cols)})"), rec)
            n += 1
    return n

# ====== UI & Auth ======
init_db()
if "is_quality" not in st.session_state:
    st.session_state.is_quality = False

with st.sidebar.expander("🔐 Entrar (Qualidade) — cadastrar/editar"):
    pwd = st.text_input("Senha (Quality)", type="password", placeholder="Informe a senha")
    cA, cB = st.columns(2)
    if cA.button("Entrar como Qualidade"):
        if pwd == QUALITY_PASS:
            st.session_state.is_quality = True
            st.success("Perfil Qualidade ativo.")
        else:
            st.error("Senha incorreta.")
    if cB.button("Sair"):
        st.session_state.is_quality = False
        st.info("Agora você está como Visitante.")

# Logo uploader + delete
with st.sidebar.expander("🖼️ Logo da empresa (para PDF e topo)"):
    logo_bytes = settings_get_logo()
    if logo_bytes:
        st.image(Image.open(io.BytesIO(logo_bytes)), width=180)
        if st.button("Remover logo atual"):
            settings_clear_logo()
            st.warning("Logo removida. Recarregue a página para atualizar.")
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
            out.append({"blob": up.getbuffer().tobytes(), "name": up.name, "mime": up.type or "image/jpeg"})
        except Exception:
            pass
    return out

def join_list(lst): return "; ".join([x for x in lst if x])

CAUSADOR_OPTS = ["Solda","Pintura","Engenharia","Fornecedor","Cliente","Caldeiraria","Usinagem","Planejamento","Qualidade","R.H","Outros"]
PROCESSO_OPTS = ["Comercial","Compras","Planejamento","Recebimento","Produção","Inspeção Final","Segurança","Meio Ambiente","5S","R.H","Outros"]
ORIGEM_OPTS = ["Pintura","Orçamento","Usinagem","Almoxarifado","Solda","Montagem","Cliente","Expedição","Preparação","R.H","Outros"]
ACAO_CORRECAO_OPTS = ["Refugo","Retrabalho","Aceitar sob concessão","Comunicar ao fornecedor","Ver e agir","Limpeza","Manutenção","Solicitação de compra"]

# ====== Nova RNC ======
if menu == "Nova RNC":
    st.header("Nova RNC (RNC Nº automático)")
    blob = settings_get_logo()
    if blob:
        c1,c2,c3 = st.columns([1,2,1])
        with c2: st.image(Image.open(io.BytesIO(blob)), width=260)
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    with st.form("form_rnc"):
        col0, col1, col2 = st.columns(3)
        emitente = col0.text_input("Emitente", placeholder="Seu nome")
        data_insp = col1.date_input("Data", value=date.today(), format="DD/MM/YYYY")
        col2.text_input("RNC Nº (gerado automaticamente)", value=next_rnc_num_for_date(data_insp), disabled=True)

        col4, col5, col6 = st.columns(3)
        area = col4.text_input("Área/Local", placeholder="Ex.: Correia TR-2011KS-07")
        categoria = col5.selectbox("Categoria", ["Segurança","Qualidade","Meio Ambiente","Operação","Manutenção","Outros"])
        severidade = col6.selectbox("Severidade", ["Baixa","Média","Alta","Crítica"])

        with st.expander("PEP (código — descrição)"):
            pep_list = get_pep_list()
            pep_choice = st.selectbox("Selecionar", options=(pep_list + ["Outro"]))
            pep_outro = st.text_input("Informe PEP (código — descrição)") if pep_choice=="Outro" else ""
            pep_final = pep_outro.strip() if pep_choice=="Outro" else pep_choice

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
                "rnc_num": rnc_num, "emitente": emitente.strip(), "area": area.strip(), "pep": pep_final or None,
                "titulo": titulo.strip(), "responsavel": responsavel.strip(),
                "descricao": descricao.strip(), "referencias": referencias.strip(),
                "causador": join_list(causador), "processo_envolvido": join_list(processo),
                "origem": join_list(origem), "acao_correcao": join_list(acao_correcao),
                "severidade": severidade, "categoria": categoria, "acoes": "", "status": "Aberta",
                "responsavel_acao": responsavel_acao.strip(),
            }
            iid = insert_inspecao(rec, imgs)
            st.success(f"RNC salva! Nº {rnc_num} • Código interno: #{iid}")

# ====== Consultar / Encerrar / Reabrir ======
elif menu == "Consultar/Encerrar/Reabrir":
    st.header("Consulta de RNCs")
    df = fetch_df()

    colf1, colf2, colf3, colf4, colf5 = st.columns(5)
    f_status = colf1.multiselect("Status", ["Aberta","Em análise","Em ação","Bloqueada","Encerrada","Cancelada"])
    f_sev = colf2.multiselect("Severidade", ["Baixa","Média","Alta","Crítica"])
    f_area = colf3.text_input("Filtrar por Área/Local")
    f_resp = colf4.text_input("Filtrar por Responsável")
    f_pep  = colf5.text_input("Filtrar por PEP")

    if not df.empty:
        if f_status: df = df[df["status"].isin(f_status)]
        if f_sev: df = df[df["severidade"].isin(f_sev)]
        if f_area: df = df[df["area"].str.contains(f_area, case=False, na=False)]
        if f_resp: df = df[df["responsavel"].str.contains(f_resp, case=False, na=False)]
        if f_pep: df = df[df["pep"].fillna("").str.contains(f_pep, case=False, na=False)]

        st.dataframe(df[["id","data","rnc_num","emitente","pep","area","titulo","responsavel",
                         "severidade","categoria","status","encerrada_em","reaberta_em","cancelada_em"]],
                     use_container_width=True, hide_index=True)

        st.markdown("---")
        if not df.empty:
            sel_id = st.number_input("Ver RNC (ID)", min_value=int(df["id"].min()), max_value=int(df["id"].max()), value=int(df["id"].iloc[0]), step=1)
            if sel_id in df["id"].values:
                row = df[df["id"] == sel_id].iloc[0].to_dict()
                st.subheader(f"RNC Nº {row.get('rnc_num') or '-'} — {row['titulo']} [{row['status']}]")

                if st.button("📄 Gerar PDF desta RNC", key=f"pdf_{sel_id}"):
                    path = generate_pdf(int(row["id"]))
                    with open(path, "rb") as _f:
                        st.download_button("Baixar PDF", _f, file_name=f"RNC_{row.get('rnc_num') or row['id']}.pdf", mime="application/pdf", key=f"dl_{sel_id}")

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

                tabs = st.tabs(["📸 Abertura", "✅ Encerramento", "♻️ Reabertura", "🗂️ Cancelamento / Exclusão"])
                with tabs[0]:
                    for rec in fetch_photos(int(row["id"]), "abertura"):
                        try: st.image(Image.open(io.BytesIO(rec["blob"])), width=360)
                        except: st.caption("Foto indisponível")
                with tabs[1]:
                    enc = fetch_photos(int(row["id"]), "encerramento")
                    st.markdown("**Observações de encerramento:**")
                    st.write(row.get("encerramento_obs") or "-")
                    st.markdown("**Descrição do fechamento:**")
                    st.write(row.get("encerramento_desc") or "-")
                    st.markdown("**Eficácia:** " + (row.get("eficacia") or "-"))
                    if enc:
                        st.markdown("**Evidências:**")
                        for rec in enc:
                            try: st.image(Image.open(io.BytesIO(rec["blob"])), width=360)
                            except: st.caption("Foto indisponível")
                    if st.session_state.is_quality and row["status"] != "Encerrada":
                        st.markdown("---")
                        with st.form(f"encerrar_{sel_id}"):
                            encerr_por = st.text_input("Encerrada por")
                            encerr_obs = st.text_area("Observações de encerramento")
                            encerr_desc = st.text_area("Descrição detalhada do fechamento")
                            eficacia = st.selectbox("Verificação de eficácia", ["A verificar","Eficaz","Não eficaz"])
                            fotos_enc = st.file_uploader("Evidências (fotos)", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"enc_{sel_id}")
                            sub = st.form_submit_button("Encerrar RNC")
                            if sub:
                                imgs = files_to_images(fotos_enc)
                                encerrar_inspecao(int(row["id"]), encerr_por.strip(), encerr_obs.strip(), eficacia, encerr_desc.strip(), imgs)
                                st.success("RNC encerrada. Recarregue para ver o novo status.")
                with tabs[2]:
                    rea = fetch_photos(int(row["id"]), "reabertura")
                    st.markdown("**Motivo da reabertura:**")
                    st.write(row.get("reabertura_motivo") or "-")
                    st.markdown("**Descrição da reabertura:**")
                    st.write(row.get("reabertura_desc") or "-")
                    if rea:
                        st.markdown("**Evidências:**")
                        for rec in rea:
                            try: st.image(Image.open(io.BytesIO(rec["blob"])), width=360)
                            except: st.caption("Foto indisponível")
                    if st.session_state.is_quality and row["status"] in ["Encerrada","Em ação","Em análise","Bloqueada","Aberta"]:
                        st.markdown("---")
                        with st.form(f"reabrir_{sel_id}"):
                            reab_por = st.text_input("Reaberta por")
                            reab_motivo = st.text_area("Motivo da reabertura")
                            reab_desc = st.text_area("Descrição detalhada da reabertura")
                            fotos_reab = st.file_uploader("Fotos (opcional)", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"reab_{sel_id}")
                            sub2 = st.form_submit_button("Reabrir RNC")
                            if sub2:
                                imgs = files_to_images(fotos_reab)
                                reabrir_inspecao(int(row["id"]), reab_por.strip(), reab_motivo.strip(), reab_desc.strip(), imgs)
                                st.success("RNC reaberta. Status voltou para 'Em ação'.")
                with tabs[3]:
                    if st.session_state.is_quality:
                        st.warning("Atenção: cancelar mantém o registro com status 'Cancelada'. Apagar remove definitivamente os dados e fotos.")
                        with st.form(f"cancel_{sel_id}"):
                            c_por = st.text_input("Cancelada por")
                            c_motivo = st.text_area("Motivo do cancelamento")
                            do_cancel = st.form_submit_button("Cancelar RNC")
                            if do_cancel:
                                cancel_inspecao(int(row["id"]), c_por.strip(), c_motivo.strip())
                                st.success("RNC marcada como Cancelada.")
                        st.divider()
                        with st.form(f"delete_{sel_id}"):
                            st.error("Exclusão definitiva (não pode ser desfeita).")
                            confirm = st.text_input("Digite CONFIRMAR para apagar definitivamente:")
                            do_delete = st.form_submit_button("Apagar RNC (definitivo)")
                            if do_delete and confirm.strip().upper() == "CONFIRMAR":
                                delete_inspecao(int(row["id"]))
                                st.success("RNC apagada permanentemente (registros e fotos). Atualize a página.")
                            elif do_delete:
                                st.warning("Digite CONFIRMAR exatamente para prosseguir.")

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
        st.download_button("Baixar CSV", data=csv_bytes, file_name="rnc_export_v2_7_1.csv", mime="text/csv")

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
