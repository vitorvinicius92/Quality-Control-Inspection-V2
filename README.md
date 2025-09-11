# RNC App v2.7.1 (v07) — Streamlit Cloud

Sistema de Registro de Não Conformidades (RNC) com:
- Abertura, consulta, encerramento e reabertura
- Cancelamento (soft delete) e Exclusão definitiva
- Fotos por etapa (abertura/encerramento/reabertura)
- PDF da RNC (inclui descrições detalhadas de fechamento e reabertura)
- Importar/Exportar CSV
- Gerenciar PEPs (lista suspensa)
- Logo da empresa (upload/remover)
- Envio de e-mail (via SMTP) — opcional

## Como publicar no Streamlit Cloud

1) Crie um repositório no GitHub e envie os arquivos deste pacote.
2) No Streamlit Cloud, faça **Deploy** apontando para `app.py`.
3) Em **App settings → Secrets**, configure (se quiser e-mail):
```
QUALITY_PASS="sua_senha_forte"
SMTP_HOST="smtp.office365.com"
SMTP_PORT="587"
SMTP_USER="seu.email@empresa.com"
SMTP_PASS="sua_senha_ou_app_password"
EMAIL_FROM="seu.email@empresa.com"
EMAIL_TO="qualidade@empresa.com, gestor@empresa.com"
APP_BASE_URL="https://seuapp.streamlit.app"
```
4) Abra o app e, no menu lateral, use **Logo da empresa** para subir/remover a logo.

## Backup e CSV
- Exporte CSV regularmente (botão **Exportar CSV**).
- Para restaurar/atualizar dados, use **Importar CSV**.
- Colunas novas no v07: `encerramento_desc`, `reabertura_desc`, `cancelada_em`, `cancelada_por`, `cancelamento_motivo`.

## Observações
- O app usa **SQLite** (`rnc.db`) criado automaticamente no diretório do app.
- Para PDF, o pacote **reportlab** já está no `requirements.txt`.
