# RNC App v2.7 — Streamlit Cloud
- RNC Nº automático (YYYY-NNN)
- PEP (código — descrição) em lista
- Campos do procedimento interno
- Fotos no banco (BLOB)
- PDF por RNC (com logo e fotos)
- E-mail automático (abertura/encerramento)
- **Importar/Exportar CSV** (backup manual)

## Deploy
1) Suba estes arquivos no GitHub.
2) No Streamlit Cloud, faça deploy de `app.py`.
3) Em **Secrets**, defina:
QUALITY_PASS="sua_senha"
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
EMAIL_FROM, EMAIL_TO
APP_BASE_URL="https://seuapp.streamlit.app" (opcional)

## Backup manual
- Exportar CSV regularmente e guardar.
- Para restaurar, use **Importar/Exportar → Importar CSV**.
