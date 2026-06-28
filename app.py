import streamlit as st
import pandas as pd
import os
import re
import json
import zipfile
from io import BytesIO
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ==============================================================================
# BIBLIOTECAS OPCIONAIS
# ==============================================================================
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
except Exception:
    canvas = None
    colors = None
    A4 = None

# ==============================================================================
# CONFIGURAÇÃO VISUAL
# ==============================================================================
st.set_page_config(page_title="ERP LuhVee Stores", page_icon="🛍️", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0b0b0d; color: #e0e0e6; }
h1, h2, h3 { color: #ffffff !important; font-family: Arial, sans-serif; }
.brand-title { color: #ff007f; font-weight: bold; letter-spacing: 1px; }
.brand-subtitle { color: #da70d6; font-size: 14px; margin-top: -15px; margin-bottom: 25px; }
div.stButton > button:first-child {
    background-color: #ff007f; color: white; border: none; border-radius: 6px;
    padding: 10px 24px; font-weight: bold;
}
div.stButton > button:first-child:hover { background-color: #da70d6; color: white; border: none; }
div[data-testid="stMetricValue"] { color: #da70d6 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='brand-title'>LuhVee Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>ERP 3.0 — Google Sheets, Estoque, Pedidos, Crediário, Parcelas & Nota Fiscal</div>", unsafe_allow_html=True)

# ==============================================================================
# COLUNAS / ABAS
# ==============================================================================
COL_CLIENTES = ["ID", "NOME", "WHATSAPP", "CIDADE", "ENDEREÇO", "CPF", "OBSERVAÇÕES", "DATA CADASTRO"]
COL_PRODUTOS = ["CÓDIGO", "PRODUTO", "CATEGORIA", "FORNECEDOR", "CUSTO", "PREÇO VENDA", "ESTOQUE"]
COL_PEDIDOS = [
    "PEDIDO", "DATA", "CLIENTE", "WHATSAPP", "PAGAMENTO", "PARCELAS", "VALOR PARCELA",
    "PLATAFORMA", "TOTAL", "STATUS", "DATA PAGAMENTO", "VALOR RECEBIDO", "SALDO A RECEBER"
]
COL_ITENS = ["PEDIDO", "PRODUTO", "QUANTIDADE", "PREÇO", "TOTAL", "LUCRO"]
COL_COMPRAS = ["NF", "DATA", "FORNECEDOR", "VALOR TOTAL", "ARQUIVO PDF", "FORMA PAGAMENTO", "PARCELAS", "VALOR PARCELA", "PRIMEIRO VENCIMENTO", "STATUS", "DATA PAGAMENTO", "SALDO A PAGAR"]
COL_PARCELAS = ["PEDIDO", "CLIENTE", "WHATSAPP", "PARCELA", "VENCIMENTO", "VALOR", "STATUS", "DATA PAGAMENTO"]

ABAS = {
    "CLIENTES": COL_CLIENTES,
    "PRODUTOS": COL_PRODUTOS,
    "PEDIDOS": COL_PEDIDOS,
    "ITENS_PEDIDO": COL_ITENS,
    "COMPRAS": COL_COMPRAS,
    "PARCELAS_RECEBER": COL_PARCELAS,
}

CSV_MAP = {
    "CLIENTES": "clientes_base.csv",
    "PRODUTOS": "estoque_base.csv",
    "PEDIDOS": "pedidos_base.csv",
    "ITENS_PEDIDO": "itens_pedido_base.csv",
    "COMPRAS": "compras_base.csv",
    "PARCELAS_RECEBER": "parcelas_receber_base.csv",
}

# ==============================================================================
# UTILITÁRIOS
# ==============================================================================
def agora_brasil():
    return datetime.now(ZoneInfo("America/Sao_Paulo"))

def hoje_brasil():
    return agora_brasil().date()

def numero_para_float(valor, padrao=0.0):
    try:
        if pd.isna(valor):
            return padrao
        if isinstance(valor, str):
            valor = valor.replace("R$", "").replace(" ", "").strip()
            if valor == "":
                return padrao
            if "," in valor:
                valor = valor.replace(".", "").replace(",", ".")
        return float(valor)
    except Exception:
        return padrao

def numero_para_int(valor, padrao=0):
    try:
        return int(round(numero_para_float(valor, padrao)))
    except Exception:
        return padrao

def formatar_moeda(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def novo_id(prefixo, df, coluna):
    if df is None or df.empty or coluna not in df.columns:
        return f"{prefixo}-0001"
    nums = []
    for item in df[coluna].astype(str).tolist():
        try:
            nums.append(int(re.sub(r"\D", "", item)))
        except Exception:
            pass
    prox = max(nums) + 1 if nums else 1
    return f"{prefixo}-{prox:04d}"

def quantidade_parcelas(parcelas):
    texto = str(parcelas).lower().strip()
    if "vista" in texto or texto in ["", "nan", "none"]:
        return 1
    m = re.search(r"(\d+)", texto)
    return max(1, int(m.group(1))) if m else 1

def calcular_valor_parcela(total, parcelas):
    qtd = quantidade_parcelas(parcelas)
    return round(numero_para_float(total) / qtd, 2) if qtd else numero_para_float(total)

def status_pago(status):
    return str(status).strip().upper() in ["PAGO", "PAGA", "RECEBIDO", "RECEBIDA", "ENTREGUE"]

def datas_vencimento(primeiro_vencimento, qtd):
    try:
        base = pd.to_datetime(primeiro_vencimento).date()
    except Exception:
        base = hoje_brasil()
    datas = []
    for i in range(qtd):
        datas.append((pd.Timestamp(base) + pd.DateOffset(months=i)).strftime("%d/%m/%Y"))
    return datas

def gerar_parcelas_pedido(pedido, cliente, whatsapp, parcelas, total, primeiro_vencimento, status):
    qtd = quantidade_parcelas(parcelas)
    valor = calcular_valor_parcela(total, parcelas)
    datas = datas_vencimento(primeiro_vencimento, qtd)
    pago = status_pago(status)
    rows = []
    for i in range(1, qtd + 1):
        rows.append({
            "PEDIDO": pedido,
            "CLIENTE": cliente,
            "WHATSAPP": whatsapp,
            "PARCELA": f"{i}/{qtd}",
            "VENCIMENTO": datas[i - 1],
            "VALOR": round(valor, 2),
            "STATUS": "Pago" if pago else "Pendente",
            "DATA PAGAMENTO": agora_brasil().strftime("%d/%m/%Y %H:%M") if pago else ""
        })
    return pd.DataFrame(rows, columns=COL_PARCELAS)

def safe_df(df, colunas):
    if df is None or df.empty:
        df = pd.DataFrame(columns=colunas)
    else:
        df = pd.DataFrame(df.astype(str).to_dict("records"))
    for col in colunas:
        if col not in df.columns:
            df[col] = ""
    return df[colunas].fillna("")

def preparar_produtos(df):
    df = safe_df(df, COL_PRODUTOS)
    df["ESTOQUE"] = df["ESTOQUE"].apply(numero_para_int).astype(int)
    df["CUSTO"] = df["CUSTO"].apply(numero_para_float).astype(float)
    df["PREÇO VENDA"] = df["PREÇO VENDA"].apply(numero_para_float).astype(float)
    return df

def preparar_pedidos(df):
    df = safe_df(df, COL_PEDIDOS)
    for c in ["TOTAL", "VALOR PARCELA", "VALOR RECEBIDO", "SALDO A RECEBER"]:
        df[c] = df[c].apply(numero_para_float).astype(float)
    return df

def preparar_itens(df):
    df = safe_df(df, COL_ITENS)
    for c in ["QUANTIDADE", "PREÇO", "TOTAL", "LUCRO"]:
        if c == "QUANTIDADE":
            df[c] = df[c].apply(numero_para_int).astype(int)
        else:
            df[c] = df[c].apply(numero_para_float).astype(float)
    return df

def preparar_parcelas(df):
    df = safe_df(df, COL_PARCELAS)
    df["VALOR"] = df["VALOR"].apply(numero_para_float).astype(float)
    return df

def preparar_compras(df):
    df = safe_df(df, COL_COMPRAS)
    for c in ["VALOR TOTAL", "VALOR PARCELA", "SALDO A PAGAR"]:
        df[c] = df[c].apply(numero_para_float).astype(float)
    return df

def gerar_resumo_vencimentos(parcelas_df, compras_df):
    """
    Gera resumo de vencimentos sem erro de comparação de datas.
    Usa Timestamp do Pandas em todas as comparações.
    """
    hoje = pd.Timestamp(hoje_brasil())
    inicio_mes = pd.Timestamp(hoje.replace(day=1))
    fim_mes = pd.Timestamp((inicio_mes + pd.offsets.MonthEnd(1)).date())

    out = {
        "receber_hoje": 0.0,
        "receber_mes": 0.0,
        "receber_vencido": 0.0,
        "pagar_hoje": 0.0,
        "pagar_mes": 0.0,
        "pagar_vencido": 0.0,
    }

    if parcelas_df is not None and not parcelas_df.empty:
        temp = preparar_parcelas(parcelas_df)
        temp["VENC_DT"] = pd.to_datetime(temp["VENCIMENTO"], dayfirst=True, errors="coerce")
        pend = temp[temp["STATUS"].astype(str).str.upper() != "PAGO"].copy()

        out["receber_hoje"] = pend[pend["VENC_DT"].dt.date == hoje.date()]["VALOR"].sum()
        out["receber_mes"] = pend[(pend["VENC_DT"] >= inicio_mes) & (pend["VENC_DT"] <= fim_mes)]["VALOR"].sum()
        out["receber_vencido"] = pend[pend["VENC_DT"] < hoje]["VALOR"].sum()

    if compras_df is not None and not compras_df.empty:
        tempc = preparar_compras(compras_df)
        tempc["VENC_DT"] = pd.to_datetime(tempc["PRIMEIRO VENCIMENTO"], dayfirst=True, errors="coerce")
        pendc = tempc[tempc["STATUS"].astype(str).str.upper() != "PAGO"].copy()

        out["pagar_hoje"] = pendc[pendc["VENC_DT"].dt.date == hoje.date()]["SALDO A PAGAR"].sum()
        out["pagar_mes"] = pendc[(pendc["VENC_DT"] >= inicio_mes) & (pendc["VENC_DT"] <= fim_mes)]["SALDO A PAGAR"].sum()
        out["pagar_vencido"] = pendc[pendc["VENC_DT"] < hoje]["SALDO A PAGAR"].sum()

    return out


# ==============================================================================
# GOOGLE SHEETS
# ==============================================================================
def tem_secrets_google():
    try:
        return "SPREADSHEET_ID" in st.secrets and (
            "GCP_SERVICE_ACCOUNT_JSON" in st.secrets or "gcp_service_account" in st.secrets
        )
    except Exception:
        return False

@st.cache_resource(show_spinner=False)
def conectar_google_sheets():
    if not tem_secrets_google() or gspread is None or Credentials is None:
        return None
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
            raw = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
            info = json.loads(raw)
        else:
            info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_key(st.secrets["SPREADSHEET_ID"])
    except Exception as e:
        st.session_state["google_sheets_erro"] = str(e)
        return None

def obter_worksheet(nome_aba):
    ss = conectar_google_sheets()
    if ss is None:
        return None
    try:
        ws = ss.worksheet(nome_aba)
    except Exception:
        ws = ss.add_worksheet(title=nome_aba, rows=2000, cols=40)
        ws.append_row(ABAS[nome_aba])
    return ws

def padronizar_df(nome_aba, df):
    colunas = ABAS[nome_aba]
    df = df.copy() if df is not None else pd.DataFrame()

    # compatibilidade com CSV antigo
    mapas = {
        "PRODUTOS": {
            "Código": "CÓDIGO", "Produto": "PRODUTO", "Categoria": "CATEGORIA", "Fornecedor": "FORNECEDOR",
            "Custo Real": "CUSTO", "Custo Nota": "CUSTO", "Preço Venda": "PREÇO VENDA", "Estoque Atual": "ESTOQUE",
        },
        "CLIENTES": {
            "Nome": "NOME", "WhatsApp": "WHATSAPP", "Cidade": "CIDADE", "Endereço": "ENDEREÇO",
            "CPF": "CPF", "Observações": "OBSERVAÇÕES", "Data Cadastro": "DATA CADASTRO",
        },
        "PEDIDOS": {
            "Pedido": "PEDIDO", "Data": "DATA", "Cliente": "CLIENTE", "WhatsApp": "WHATSAPP",
            "Forma Pagamento": "PAGAMENTO", "Parcelas": "PARCELAS", "Total Pedido": "TOTAL", "Status": "STATUS",
        },
        "ITENS_PEDIDO": {
            "Pedido": "PEDIDO", "Produto": "PRODUTO", "Quantidade": "QUANTIDADE",
            "Preço Unitário": "PREÇO", "Total Item": "TOTAL", "Lucro Item": "LUCRO",
        }
    }
    for velho, novo in mapas.get(nome_aba, {}).items():
        if velho in df.columns and novo not in df.columns:
            df[novo] = df[velho]

    for c in colunas:
        if c not in df.columns:
            df[c] = ""
    return df[colunas].fillna("")

def carregar_aba(nome_aba):
    csv_file = CSV_MAP[nome_aba]
    colunas = ABAS[nome_aba]
    ws = obter_worksheet(nome_aba)

    if ws is not None:
        try:
            valores = ws.get_all_values()
            if len(valores) <= 1:
                if os.path.exists(csv_file):
                    df_csv = padronizar_df(nome_aba, pd.read_csv(csv_file))
                    if not df_csv.empty:
                        salvar_aba(nome_aba, df_csv, salvar_csv=True, salvar_google=True)
                    return df_csv
                return pd.DataFrame(columns=colunas)
            df = pd.DataFrame(valores[1:], columns=valores[0])
            return padronizar_df(nome_aba, df)
        except Exception:
            pass

    if os.path.exists(csv_file):
        try:
            return padronizar_df(nome_aba, pd.read_csv(csv_file))
        except Exception:
            pass

    return pd.DataFrame(columns=colunas)

def salvar_aba(nome_aba, df, salvar_csv=True, salvar_google=True):
    df = padronizar_df(nome_aba, df)
    if salvar_csv:
        df.to_csv(CSV_MAP[nome_aba], index=False)
    if salvar_google:
        ws = obter_worksheet(nome_aba)
        if ws is not None:
            ws.clear()
            ws.update([ABAS[nome_aba]] + df.astype(str).values.tolist())

def carregar_tudo():
    return {nome: carregar_aba(nome) for nome in ABAS}

if "dados" not in st.session_state:
    st.session_state.dados = carregar_tudo()
else:
    for nome in ABAS:
        if nome not in st.session_state.dados:
            st.session_state.dados[nome] = carregar_aba(nome)

def dados(nome):
    if nome not in st.session_state.dados:
        st.session_state.dados[nome] = carregar_aba(nome)
    return st.session_state.dados[nome]

def atualizar(nome, df):
    st.session_state.dados[nome] = padronizar_df(nome, df)
    salvar_aba(nome, st.session_state.dados[nome])

# ==============================================================================
# PDF RECIBO A4
# ==============================================================================
def gerar_pdf_recibo(pedido_info, itens, parcelas_df=None):
    if canvas is None or A4 is None:
        return None

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#444444")

    margem = 18 * mm
    y = altura - 18 * mm

    def nova_pagina():
        nonlocal y
        pdf.showPage()
        y = altura - 18 * mm
        cabecalho()

    def linha(espaco=6):
        nonlocal y
        pdf.setStrokeColor(rosa)
        pdf.setLineWidth(0.6)
        pdf.line(margem, y, largura - margem, y)
        y -= espaco * mm

    def texto(txt, x=None, fonte="Helvetica", tam=9, cor=preto, espaco=5):
        nonlocal y
        pdf.setFont(fonte, tam)
        pdf.setFillColor(cor)
        pdf.drawString(x if x is not None else margem, y, str(txt))
        y -= espaco * mm

    def direita(txt, tam=9):
        pdf.setFont("Helvetica", tam)
        pdf.setFillColor(preto)
        pdf.drawRightString(largura - margem, y, str(txt))

    def central(txt, fonte="Helvetica-Bold", tam=14, cor=preto, espaco=7):
        nonlocal y
        pdf.setFont(fonte, tam)
        pdf.setFillColor(cor)
        pdf.drawCentredString(largura / 2, y, str(txt))
        y -= espaco * mm

    def cabecalho():
        nonlocal y
        central("LUHVEE STORES", "Helvetica-Bold", 18, rosa, 8)
        central("Curadoria Inteligente & Achadinhos Exclusivos", "Helvetica", 9, cinza, 7)
        linha(6)

    cabecalho()
    central("RECIBO DE VENDA", "Helvetica-Bold", 15, preto, 8)

    total = numero_para_float(pedido_info.get("TOTAL", 0))
    parcelas = pedido_info.get("PARCELAS", "À vista")
    valor_parcela = numero_para_float(pedido_info.get("VALOR PARCELA", calcular_valor_parcela(total, parcelas)))
    saldo = numero_para_float(pedido_info.get("SALDO A RECEBER", total if not status_pago(pedido_info.get("STATUS", "")) else 0))

    texto(f"Pedido: {pedido_info.get('PEDIDO', '')}", fonte="Helvetica-Bold", tam=10)
    texto(f"Data: {pedido_info.get('DATA', '')}", tam=9)
    linha(5)

    texto("CLIENTE", fonte="Helvetica-Bold", tam=10, cor=rosa)
    texto(f"Nome: {pedido_info.get('CLIENTE', '')}", tam=9)
    texto(f"WhatsApp: {pedido_info.get('WHATSAPP', '')}", tam=9)
    linha(5)

    texto("DETALHES", fonte="Helvetica-Bold", tam=10, cor=rosa)
    texto(f"Plataforma: {pedido_info.get('PLATAFORMA', '')}", tam=9)
    texto(f"Pagamento: {pedido_info.get('PAGAMENTO', '')} - {parcelas}", tam=9)
    if quantidade_parcelas(parcelas) > 1:
        texto(f"Valor da parcela: {formatar_moeda(valor_parcela)}", tam=9)
    texto(f"Status: {pedido_info.get('STATUS', '')}", tam=9)
    if saldo > 0:
        texto(f"A receber: {formatar_moeda(saldo)}", fonte="Helvetica-Bold", tam=9, cor=rosa)
    linha(5)

    texto("PRODUTOS", fonte="Helvetica-Bold", tam=10, cor=rosa)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(margem, y, "Produto")
    pdf.drawRightString(largura - margem, y, "Total")
    y -= 4 * mm
    pdf.setStrokeColor(cinza)
    pdf.line(margem, y, largura - margem, y)
    y -= 4 * mm

    for _, item in itens.iterrows():
        if y < 65 * mm:
            nova_pagina()
            texto("PRODUTOS - continuação", fonte="Helvetica-Bold", tam=10, cor=rosa)
        qtd = numero_para_int(item.get("QUANTIDADE", 1), 1)
        prod = str(item.get("PRODUTO", ""))[:75]
        val = formatar_moeda(numero_para_float(item.get("TOTAL", 0)))
        pdf.setFont("Helvetica", 8)
        pdf.setFillColor(preto)
        pdf.drawString(margem, y, f"{qtd}x {prod}")
        pdf.drawRightString(largura - margem, y, val)
        y -= 5 * mm

    if parcelas_df is not None and not parcelas_df.empty:
        if y < 70 * mm:
            nova_pagina()
        linha(5)
        texto("PARCELAS / CREDIÁRIO", fonte="Helvetica-Bold", tam=10, cor=rosa)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(margem, y, "Vencimento")
        pdf.drawString(margem + 45 * mm, y, "Valor")
        pdf.drawString(margem + 85 * mm, y, "Status")
        y -= 4 * mm
        pdf.setStrokeColor(cinza)
        pdf.line(margem, y, largura - margem, y)
        y -= 4 * mm

        for _, p in parcelas_df.iterrows():
            if y < 45 * mm:
                nova_pagina()
                texto("PARCELAS / CREDIÁRIO - continuação", fonte="Helvetica-Bold", tam=10, cor=rosa)
            pdf.setFont("Helvetica", 8)
            pdf.setFillColor(preto)
            pdf.drawString(margem, y, str(p.get("VENCIMENTO", "")))
            pdf.drawString(margem + 45 * mm, y, formatar_moeda(numero_para_float(p.get("VALOR", 0))))
            pdf.drawString(margem + 85 * mm, y, str(p.get("STATUS", "Pendente")))
            y -= 5 * mm

    if y < 45 * mm:
        nova_pagina()
    linha(5)
    central("TOTAL DO PEDIDO", "Helvetica-Bold", 11, preto, 6)
    central(formatar_moeda(total), "Helvetica-Bold", 20, rosa, 12)
    linha(5)
    central("Obrigada pela preferência ❤️", "Helvetica-Oblique", 9, preto, 6)
    central("LuhVee Stores", "Helvetica-Bold", 10, rosa, 6)

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()

# ==============================================================================
# NOTA FISCAL PDF
# ==============================================================================
def extrair_produtos_nfe_pdf(arquivo_pdf):
    """
    Leitor robusto de DANFE/NF-e PDF.
    Corrigido para notas Kinature:
    - aceita 5.102UN grudado;
    - aceita CFOP5102 grudado no nome;
    - junta nomes quebrados em linhas antes do código;
    - ignora ICMS/impostos.
    """
    if pdfplumber is None:
        return pd.DataFrame(columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])

    produtos = []
    texto_total = ""

    def limpar_nome(nome):
        nome = str(nome).replace("\n", " ")
        nome = " ".join(nome.split()).strip()

        # Remove cabeçalhos e códigos grudados comuns
        nome = re.sub(r"^CFOP\s*5102\s*", "", nome, flags=re.IGNORECASE)
        nome = re.sub(r"^CFOP5102\s*", "", nome, flags=re.IGNORECASE)

        # Remove códigos numéricos soltos no começo e no fim
        nome = re.sub(r"^\d{1,6}\s+", "", nome).strip()
        nome = re.sub(r"\s+\d{1,6}$", "", nome).strip()

        # Limpa palavras técnicas que às vezes grudam no começo
        nome = re.sub(r"^CÓDIGO\s*", "", nome, flags=re.IGNORECASE).strip()
        return nome.upper()

    def add_produto(nome, qtd, custo, total):
        nome = limpar_nome(nome)
        qtd = numero_para_float(qtd)
        custo = numero_para_float(custo)
        total = numero_para_float(total)

        if not nome or qtd <= 0 or custo <= 0:
            return

        ignorar = [
            "DADOS DO PRODUTO", "DESCRIÇÃO DO PRODUTO", "VALOR TOTAL",
            "CÁLCULO DO IMPOSTO", "TRANSPORTADOR", "DADOS ADICIONAIS",
            "RESERVADO AO FISCO", "CÓDIGO DESCRIÇÃO", "FATURAS"
        ]
        if any(x in nome for x in ignorar):
            return

        produtos.append({
            "PRODUTO": nome,
            "QUANTIDADE": int(round(qtd)),
            "CUSTO UNITÁRIO": round(custo, 2),
            "TOTAL": round(total, 2)
        })

    try:
        with pdfplumber.open(arquivo_pdf) as pdf:
            for pagina in pdf.pages:
                texto_total += "\n" + (pagina.extract_text() or "")
    except Exception:
        return pd.DataFrame(columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])

    linhas = [" ".join(l.split()) for l in texto_total.splitlines() if l and l.strip()]

    # Padrão principal:
    # 2436 Produto 33049910 0102 5.102UN 5,00 5,49 27,45
    padrao_produto = re.compile(
        r"^(?P<desc>.*?)\s+"
        r"(?P<ncm>\d{8})\s+"
        r"(?P<csosn>\d{3,4})\s+"
        r"(?P<cfop>5[\.,]102|5102|5405)\s*UN\s+"
        r"(?P<qtd>\d+[\.,]\d+)\s+"
        r"(?P<custo>\d+[\.,]\d+)\s+"
        r"(?P<total>\d+[\.,]\d+)"
    )

    buffer_nome = ""

    for linha in linhas:
        linha_limpa = linha.replace("CFOP5102", "CFOP5102 ")

        # Ignora blocos não relacionados aos itens
        if any(x in linha_limpa.upper() for x in [
            "RECEBEMOS DE", "DANFE", "DOCUMENTO AUXILIAR", "CHAVE DE ACESSO",
            "DESTINATÁRIO", "REMETENTE", "CÁLCULO DO IMPOSTO", "FATURAS",
            "TRANSPORTADOR", "DADOS ADICIONAIS", "PROTOCOLO", "NATUREZA DA OPERAÇÃO",
            "VALOR TOTAL DA NOTA", "VALOR TOTAL DOS PRODUTOS", "CONSULTA DE AUTENTICIDADE",
            "INSCRIÇÃO ESTADUAL", "NOME / RAZÃO SOCIAL"
        ]):
            continue

        m = padrao_produto.search(linha_limpa)

        if m:
            desc = m.group("desc").strip()

            # Se a linha do produto veio só com código, usa a descrição guardada antes
            nome_base = (buffer_nome + " " + desc).strip() if buffer_nome else desc

            add_produto(nome_base, m.group("qtd"), m.group("custo"), m.group("total"))
            buffer_nome = ""
            continue

        # Guarda linhas que parecem continuação de nome de produto
        parece_nome = (
            len(linha_limpa) <= 140
            and not re.fullmatch(r"[\d\.,\s\/:-]+", linha_limpa)
            and not re.search(r"\d{8}\s+\d{3,4}\s+(5[\.,]102|5102|5405)", linha_limpa)
            and not re.search(r"\d{2}/\d{2}/\d{4}", linha_limpa)
        )

        if parece_nome:
            # evita pegar títulos grandes
            proibidos = ["CÓDIGO DESCRIÇÃO", "PREÇO PREÇO", "ITENS DA NOTA"]
            if not any(p in linha_limpa.upper() for p in proibidos):
                buffer_nome = (buffer_nome + " " + linha_limpa).strip()[-250:]

    # Remove duplicados
    if produtos:
        df = pd.DataFrame(produtos)

        # Correção extra: se algum nome veio só código/curto demais, remove
        df = df[df["PRODUTO"].astype(str).str.len() > 4]

        df = df.drop_duplicates(subset=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])
        return df.reset_index(drop=True)

    return pd.DataFrame(columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])


# ==============================================================================
# MENU
# ==============================================================================
menu = [
    "Dashboard",
    "👥 Clientes",
    "📦 Produtos / Estoque",
    "🧾 Criar Pedido",
    "📋 Histórico de Pedidos",
    "💳 Parcelas / Crediário",
    "📅 Agenda Financeira",
    "🛒 Calculadora de Pedido",
    "🧮 Calculadora LuhVee",
    "📑 Entrada por Nota Fiscal",
    "📤 Exportar para Yampi",
    "💾 Backup ERP",
    "🔧 Status Google Sheets",
]
escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# ==============================================================================
# STATUS
# ==============================================================================
if escolha == "🔧 Status Google Sheets":
    st.subheader("🔧 Status Google Sheets")
    ss = conectar_google_sheets()
    if ss is not None:
        st.success("✅ Conectado ao Google Sheets com sucesso.")
        st.write("Planilha ID:", st.secrets.get("SPREADSHEET_ID", "Não informado"))
        st.write("Abas esperadas:", list(ABAS.keys()))
    else:
        st.error("❌ Não conectado ao Google Sheets.")
        erro = st.session_state.get("google_sheets_erro", "")
        if erro:
            st.code(erro)

# ==============================================================================
# DASHBOARD
# ==============================================================================
elif escolha == "Dashboard":
    st.subheader("📊 Dashboard Geral")

    produtos = preparar_produtos(dados("PRODUTOS"))
    pedidos = preparar_pedidos(dados("PEDIDOS"))
    parcelas_df = preparar_parcelas(dados("PARCELAS_RECEBER"))

    total_estoque = (produtos["CUSTO"] * produtos["ESTOQUE"]).sum() if not produtos.empty else 0
    faturamento = pedidos["TOTAL"].sum() if not pedidos.empty else 0
    recebido = pedidos["VALOR RECEBIDO"].sum() if not pedidos.empty else 0
    a_receber = pedidos["SALDO A RECEBER"].sum() if not pedidos.empty else 0

    hoje = hoje_brasil()
    vencidas = 0.0
    if not parcelas_df.empty:
        tmp = parcelas_df.copy()
        tmp["VENC_DT"] = pd.to_datetime(tmp["VENCIMENTO"], dayfirst=True, errors="coerce")
        vencidas = tmp[
            (tmp["STATUS"].astype(str).str.upper() != "PAGO") &
            (tmp["VENC_DT"].notna()) &
            (tmp["VENC_DT"] < pd.Timestamp(hoje))
        ]["VALOR"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Investimento em Estoque", formatar_moeda(total_estoque))
    c2.metric("Faturamento", formatar_moeda(faturamento))
    c3.metric("Recebido", formatar_moeda(recebido))
    c4.metric("A Receber", formatar_moeda(a_receber))

    c5, c6, c7 = st.columns(3)
    c5.metric("Produtos", len(produtos))
    c6.metric("Pedidos", len(pedidos))
    c7.metric("Parcelas vencidas", formatar_moeda(vencidas))

    compras = preparar_compras(dados("COMPRAS"))
    resumo_fin = gerar_resumo_vencimentos(parcelas_df, compras)

    if resumo_fin["receber_vencido"] > 0:
        st.error(f"⚠️ Você tem {formatar_moeda(resumo_fin['receber_vencido'])} em parcelas vencidas para receber.")
    if resumo_fin["pagar_vencido"] > 0:
        st.error(f"⚠️ Você tem {formatar_moeda(resumo_fin['pagar_vencido'])} em contas/fornecedores vencidos para pagar.")
    if resumo_fin["receber_hoje"] > 0:
        st.warning(f"📅 Hoje vence {formatar_moeda(resumo_fin['receber_hoje'])} para receber.")
    if resumo_fin["pagar_hoje"] > 0:
        st.warning(f"📅 Hoje vence {formatar_moeda(resumo_fin['pagar_hoje'])} para pagar.")

    st.markdown("### 📦 Estoque baixo")
    baixo = produtos[produtos["ESTOQUE"] <= 2] if not produtos.empty else pd.DataFrame()
    st.dataframe(baixo, use_container_width=True)

# ==============================================================================
# CLIENTES
# ==============================================================================
elif escolha == "👥 Clientes":
    st.subheader("👥 Clientes")
    clientes = safe_df(dados("CLIENTES"), COL_CLIENTES)

    with st.form("form_cliente", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome")
        whatsapp = c2.text_input("WhatsApp")
        c3, c4 = st.columns(2)
        cidade = c3.text_input("Cidade")
        cpf = c4.text_input("CPF")
        endereco = st.text_input("Endereço")
        obs = st.text_area("Observações")
        if st.form_submit_button("Salvar Cliente"):
            if not nome.strip():
                st.error("Informe o nome.")
            else:
                novo = {
                    "ID": novo_id("CLI", clientes, "ID"),
                    "NOME": nome.strip(),
                    "WHATSAPP": whatsapp.strip(),
                    "CIDADE": cidade.strip(),
                    "ENDEREÇO": endereco.strip(),
                    "CPF": cpf.strip(),
                    "OBSERVAÇÕES": obs.strip(),
                    "DATA CADASTRO": agora_brasil().strftime("%d/%m/%Y %H:%M"),
                }
                clientes = pd.concat([clientes, pd.DataFrame([novo])], ignore_index=True)
                atualizar("CLIENTES", clientes)
                st.success("Cliente salvo.")
                st.rerun()

    editado = st.data_editor(clientes, use_container_width=True, num_rows="dynamic")
    if st.button("Salvar alterações dos clientes"):
        atualizar("CLIENTES", editado)
        st.success("Clientes atualizados.")
        st.rerun()

# ==============================================================================
# PRODUTOS
# ==============================================================================
elif escolha == "📦 Produtos / Estoque":
    st.subheader("📦 Produtos / Estoque")
    produtos = preparar_produtos(dados("PRODUTOS"))

    with st.form("form_produto", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        codigo = c1.text_input("Código")
        produto = c2.text_input("Produto")
        c3, c4, c5 = st.columns(3)
        categoria = c3.text_input("Categoria", "Cosméticos")
        fornecedor = c4.text_input("Fornecedor", "Fornecedor")
        estoque = c5.number_input("Quantidade", min_value=0, value=1, step=1)
        c6, c7 = st.columns(2)
        custo = c6.number_input("Custo Unitário", min_value=0.0, value=0.0, format="%.2f")
        preco = c7.number_input("Preço de Venda", min_value=0.0, value=0.0, format="%.2f")

        if st.form_submit_button("Salvar Produto"):
            if not produto.strip():
                st.error("Informe o produto.")
            else:
                novo = {
                    "CÓDIGO": codigo.strip().upper() or novo_id("PROD", produtos, "CÓDIGO"),
                    "PRODUTO": produto.strip().upper(),
                    "CATEGORIA": categoria.strip(),
                    "FORNECEDOR": fornecedor.strip(),
                    "CUSTO": round(custo, 2),
                    "PREÇO VENDA": round(preco, 2),
                    "ESTOQUE": int(estoque),
                }
                produtos = pd.concat([produtos, pd.DataFrame([novo])], ignore_index=True)
                atualizar("PRODUTOS", produtos)
                st.success("Produto salvo.")
                st.rerun()

    editado = st.data_editor(produtos, use_container_width=True, num_rows="dynamic")
    if st.button("Salvar alterações do estoque"):
        atualizar("PRODUTOS", editado)
        st.success("Estoque atualizado.")
        st.rerun()

# ==============================================================================
# CRIAR PEDIDO
# ==============================================================================
elif escolha == "🧾 Criar Pedido":
    st.subheader("🧾 Criar Pedido")

    clientes = safe_df(dados("CLIENTES"), COL_CLIENTES)
    produtos = preparar_produtos(dados("PRODUTOS"))
    pedidos = preparar_pedidos(dados("PEDIDOS"))
    itens_pedido = preparar_itens(dados("ITENS_PEDIDO"))
    parcelas_receber = preparar_parcelas(dados("PARCELAS_RECEBER"))

    if clientes.empty or produtos.empty:
        st.warning("Cadastre pelo menos 1 cliente e 1 produto.")
    else:
        pedido_id = novo_id("PED", pedidos, "PEDIDO")
        st.markdown(f"### Pedido: **{pedido_id}**")

        with st.form("form_pedido"):
            c1, c2, c3 = st.columns(3)
            cliente_nome = c1.selectbox("Cliente", clientes["NOME"].astype(str).tolist())
            pagamento = c2.selectbox("Pagamento", ["PIX", "Dinheiro", "Débito", "Crédito", "Crediário LuhVee", "Mercado Pago", "PagBank", "PicPay"])
            parcelas = c3.selectbox("Parcelas", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"])

            c4, c5 = st.columns(2)
            plataforma = c4.selectbox("Plataforma", ["WhatsApp", "Instagram", "Loja Física", "Yampi", "Shopee", "Mercado Livre", "iFood"])
            status = c5.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"])

            primeiro_vencimento = st.date_input("Primeiro vencimento", value=hoje_brasil(), format="DD/MM/YYYY")

            st.markdown("### Produtos")
            produtos_lista = produtos["PRODUTO"].astype(str).tolist()
            itens_temp = []

            for i in range(1, 21):
                p1, p2, p3 = st.columns([4, 1, 2])
                prod = p1.selectbox(f"Produto {i}", [""] + produtos_lista, key=f"prod_{i}")
                qtd = p2.number_input("Qtd", min_value=0, value=0, step=1, key=f"qtd_{i}")
                preco_padrao = 0.0
                if prod:
                    linha = produtos[produtos["PRODUTO"].astype(str) == prod]
                    if not linha.empty:
                        preco_padrao = numero_para_float(linha.iloc[0]["PREÇO VENDA"])
                preco = p3.number_input("Preço", min_value=0.0, value=preco_padrao, format="%.2f", key=f"preco_{i}")
                if prod and qtd > 0:
                    itens_temp.append({"PRODUTO": prod, "QUANTIDADE": qtd, "PREÇO": preco})

            finalizar = st.form_submit_button("Finalizar Pedido")

        if finalizar:
            if not itens_temp:
                st.error("Adicione pelo menos 1 produto.")
            else:
                erros = []
                for item in itens_temp:
                    linha = produtos[produtos["PRODUTO"].astype(str) == item["PRODUTO"]]
                    estoque_atual = numero_para_int(linha.iloc[0]["ESTOQUE"]) if not linha.empty else 0
                    if estoque_atual < item["QUANTIDADE"]:
                        erros.append(f"{item['PRODUTO']}: estoque {estoque_atual}, pedido {item['QUANTIDADE']}")

                if erros:
                    for e in erros:
                        st.error(e)
                else:
                    cliente_row = clientes[clientes["NOME"].astype(str) == cliente_nome].iloc[0]
                    whatsapp = cliente_row.get("WHATSAPP", "")

                    total_pedido = 0.0
                    novos_itens = []

                    for item in itens_temp:
                        idx = produtos[produtos["PRODUTO"].astype(str) == item["PRODUTO"]].index[0]
                        qtd = int(item["QUANTIDADE"])
                        preco = numero_para_float(item["PREÇO"])
                        custo = numero_para_float(produtos.loc[idx, "CUSTO"])
                        total_item = qtd * preco
                        lucro = total_item - (qtd * custo)
                        produtos.loc[idx, "ESTOQUE"] = int(numero_para_int(produtos.loc[idx, "ESTOQUE"]) - qtd)
                        novos_itens.append({
                            "PEDIDO": pedido_id,
                            "PRODUTO": item["PRODUTO"],
                            "QUANTIDADE": qtd,
                            "PREÇO": round(preco, 2),
                            "TOTAL": round(total_item, 2),
                            "LUCRO": round(lucro, 2),
                        })
                        total_pedido += total_item

                    valor_parcela = calcular_valor_parcela(total_pedido, parcelas)
                    valor_recebido = total_pedido if status_pago(status) else 0.0
                    saldo = 0.0 if status_pago(status) else total_pedido
                    data_pg = agora_brasil().strftime("%d/%m/%Y %H:%M") if status_pago(status) else ""

                    novo_pedido = {
                        "PEDIDO": pedido_id,
                        "DATA": agora_brasil().strftime("%d/%m/%Y %H:%M"),
                        "CLIENTE": cliente_nome,
                        "WHATSAPP": whatsapp,
                        "PAGAMENTO": pagamento,
                        "PARCELAS": parcelas,
                        "VALOR PARCELA": round(valor_parcela, 2),
                        "PLATAFORMA": plataforma,
                        "TOTAL": round(total_pedido, 2),
                        "STATUS": status,
                        "DATA PAGAMENTO": data_pg,
                        "VALOR RECEBIDO": round(valor_recebido, 2),
                        "SALDO A RECEBER": round(saldo, 2),
                    }

                    novas_parcelas = gerar_parcelas_pedido(pedido_id, cliente_nome, whatsapp, parcelas, total_pedido, primeiro_vencimento, status)

                    pedidos = pd.concat([pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
                    itens_pedido = pd.concat([itens_pedido, pd.DataFrame(novos_itens)], ignore_index=True)
                    parcelas_receber = pd.concat([parcelas_receber, novas_parcelas], ignore_index=True)

                    atualizar("PRODUTOS", produtos)
                    atualizar("PEDIDOS", pedidos)
                    atualizar("ITENS_PEDIDO", itens_pedido)
                    atualizar("PARCELAS_RECEBER", parcelas_receber)

                    st.success(f"Pedido {pedido_id} salvo. Total: {formatar_moeda(total_pedido)}")
                    st.rerun()

# ==============================================================================
# HISTÓRICO
# ==============================================================================
elif escolha == "📋 Histórico de Pedidos":
    st.subheader("📋 Histórico de Pedidos")

    pedidos = preparar_pedidos(dados("PEDIDOS"))
    itens_pedido = preparar_itens(dados("ITENS_PEDIDO"))
    parcelas_receber = preparar_parcelas(dados("PARCELAS_RECEBER"))

    if pedidos.empty:
        st.info("Nenhum pedido cadastrado.")
    else:
        st.dataframe(pedidos, use_container_width=True)
        pedido_sel = st.selectbox("Abrir pedido", pedidos["PEDIDO"].astype(str).tolist())
        idx_pedido = pedidos[pedidos["PEDIDO"].astype(str) == pedido_sel].index[0]
        pedido_info = pedidos.loc[idx_pedido].to_dict()
        itens = itens_pedido[itens_pedido["PEDIDO"].astype(str) == pedido_sel]
        parcelas_pedido = parcelas_receber[parcelas_receber["PEDIDO"].astype(str) == pedido_sel]

        st.markdown("### Resumo financeiro")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", formatar_moeda(pedido_info.get("TOTAL", 0)))
        c2.metric("Parcelas", str(pedido_info.get("PARCELAS", "")))
        c3.metric("Valor parcela", formatar_moeda(pedido_info.get("VALOR PARCELA", 0)))
        c4.metric("A receber", formatar_moeda(pedido_info.get("SALDO A RECEBER", 0)))

        st.markdown("### Atualizar status / pagamento")
        novo_status = st.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"], index=1 if pedido_info.get("STATUS") == "Pendente" else 0)
        valor_recebido = st.number_input("Valor recebido até agora", min_value=0.0, value=float(numero_para_float(pedido_info.get("VALOR RECEBIDO", 0))), format="%.2f")

        if st.button("💰 Salvar pagamento/status"):
            total = numero_para_float(pedido_info.get("TOTAL", 0))
            saldo = max(0.0, total - valor_recebido)
            pedidos.loc[idx_pedido, "STATUS"] = "Pago" if saldo <= 0 else novo_status
            pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = round(valor_recebido, 2)
            pedidos.loc[idx_pedido, "SALDO A RECEBER"] = round(saldo, 2)
            if saldo <= 0:
                pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")
                mask = parcelas_receber["PEDIDO"].astype(str) == pedido_sel
                parcelas_receber.loc[mask, "STATUS"] = "Pago"
                parcelas_receber.loc[mask, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")
            atualizar("PEDIDOS", pedidos)
            atualizar("PARCELAS_RECEBER", parcelas_receber)
            st.success("Pedido atualizado.")
            st.rerun()

        st.markdown("### Itens")
        st.dataframe(itens, use_container_width=True)

        st.markdown("### Parcelas")
        st.dataframe(parcelas_pedido, use_container_width=True)

        pdf_bytes = gerar_pdf_recibo(pedido_info, itens, parcelas_pedido)
        if pdf_bytes:
            st.download_button("📄 Baixar Recibo A4 PDF", data=pdf_bytes, file_name=f"recibo_{pedido_sel}.pdf", mime="application/pdf")

        st.markdown("### Excluir pedido")
        confirmar = st.checkbox(f"Confirmo excluir {pedido_sel}")
        if st.button("🗑️ Excluir pedido"):
            if confirmar:
                pedidos = pedidos[pedidos["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                itens_pedido = itens_pedido[itens_pedido["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                parcelas_receber = parcelas_receber[parcelas_receber["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                atualizar("PEDIDOS", pedidos)
                atualizar("ITENS_PEDIDO", itens_pedido)
                atualizar("PARCELAS_RECEBER", parcelas_receber)
                st.success("Pedido excluído.")
                st.rerun()
            else:
                st.error("Confirme antes de excluir.")

# ==============================================================================
# PARCELAS
# ==============================================================================
elif escolha == "💳 Parcelas / Crediário":
    st.subheader("💳 Parcelas / Crediário")

    parcelas_df = preparar_parcelas(dados("PARCELAS_RECEBER"))
    pedidos = preparar_pedidos(dados("PEDIDOS"))

    if parcelas_df.empty:
        st.info("Nenhuma parcela cadastrada.")
    else:
        temp = parcelas_df.copy()
        temp["VENC_DT"] = pd.to_datetime(temp["VENCIMENTO"], dayfirst=True, errors="coerce")
        pendentes = temp[temp["STATUS"].astype(str).str.upper() != "PAGO"]
        vencidas = pendentes[pendentes["VENC_DT"].notna() & (pendentes["VENC_DT"] < pd.Timestamp(hoje_brasil()))]

        c1, c2 = st.columns(2)
        c1.metric("A receber", formatar_moeda(pendentes["VALOR"].sum()))
        c2.metric("Vencidas", formatar_moeda(vencidas["VALOR"].sum()))

        st.markdown("### Parcelas pendentes")
        st.dataframe(pendentes.drop(columns=["VENC_DT"], errors="ignore"), use_container_width=True)

        if not pendentes.empty:
            opcoes = []
            idxs = []
            for idx, row in pendentes.iterrows():
                opcoes.append(f"{row['PEDIDO']} | {row['CLIENTE']} | {row['PARCELA']} | {row['VENCIMENTO']} | {formatar_moeda(row['VALOR'])}")
                idxs.append(idx)
            escolha_parcela = st.selectbox("Marcar parcela como paga", opcoes)
            idx_real = idxs[opcoes.index(escolha_parcela)]

            if st.button("✅ Marcar como paga"):
                pedido_id = parcelas_df.loc[idx_real, "PEDIDO"]
                parcelas_df.loc[idx_real, "STATUS"] = "Pago"
                parcelas_df.loc[idx_real, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                parcelas_pedido = parcelas_df[parcelas_df["PEDIDO"].astype(str) == str(pedido_id)]
                recebido = parcelas_pedido[parcelas_pedido["STATUS"].astype(str).str.upper() == "PAGO"]["VALOR"].sum()
                saldo = parcelas_pedido[parcelas_pedido["STATUS"].astype(str).str.upper() != "PAGO"]["VALOR"].sum()

                if str(pedido_id) in pedidos["PEDIDO"].astype(str).tolist():
                    idxp = pedidos[pedidos["PEDIDO"].astype(str) == str(pedido_id)].index[0]
                    pedidos.loc[idxp, "VALOR RECEBIDO"] = round(recebido, 2)
                    pedidos.loc[idxp, "SALDO A RECEBER"] = round(saldo, 2)
                    pedidos.loc[idxp, "STATUS"] = "Pago" if saldo <= 0 else "Pendente"
                    if saldo <= 0:
                        pedidos.loc[idxp, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                atualizar("PARCELAS_RECEBER", parcelas_df)
                atualizar("PEDIDOS", pedidos)
                st.success("Parcela atualizada.")
                st.rerun()

        st.markdown("### Todas as parcelas")
        st.dataframe(parcelas_df, use_container_width=True)


# ==============================================================================
# AGENDA FINANCEIRA - FASE 1
# ==============================================================================
elif escolha == "📅 Agenda Financeira":
    st.subheader("📅 Agenda Financeira")

    parcelas_df = preparar_parcelas(dados("PARCELAS_RECEBER"))
    compras = preparar_compras(dados("COMPRAS"))
    resumo = gerar_resumo_vencimentos(parcelas_df, compras)

    st.markdown("### Resumo de hoje e do mês")
    c1, c2, c3 = st.columns(3)
    c1.metric("Receber hoje", formatar_moeda(resumo["receber_hoje"]))
    c2.metric("Receber no mês", formatar_moeda(resumo["receber_mes"]))
    c3.metric("Recebimentos vencidos", formatar_moeda(resumo["receber_vencido"]))

    c4, c5, c6 = st.columns(3)
    c4.metric("Pagar hoje", formatar_moeda(resumo["pagar_hoje"]))
    c5.metric("Pagar no mês", formatar_moeda(resumo["pagar_mes"]))
    c6.metric("Pagamentos vencidos", formatar_moeda(resumo["pagar_vencido"]))

    hoje = hoje_brasil()

    st.markdown("---")
    st.markdown("### 📥 Contas a receber / parcelas de clientes")

    if parcelas_df.empty:
        st.info("Nenhuma parcela de cliente cadastrada.")
    else:
        rec = parcelas_df.copy()
        rec["VENC_DT"] = pd.to_datetime(rec["VENCIMENTO"], dayfirst=True, errors="coerce")
        rec["DIAS"] = rec["VENC_DT"].apply(lambda d: (d.date() - hoje).days if pd.notna(d) else "")
        rec_pend = rec[rec["STATUS"].astype(str).str.upper() != "PAGO"].sort_values(by=["VENC_DT"], na_position="last")
        st.dataframe(rec_pend.drop(columns=["VENC_DT"], errors="ignore"), use_container_width=True)

        if not rec_pend.empty:
            opcoes = []
            idxs = []
            for idx, row in rec_pend.iterrows():
                opcoes.append(f"{row['PEDIDO']} | {row['CLIENTE']} | {row['PARCELA']} | {row['VENCIMENTO']} | {formatar_moeda(row['VALOR'])}")
                idxs.append(idx)

            escolha_rec = st.selectbox("Marcar parcela de cliente como paga", [""] + opcoes)
            if escolha_rec:
                idx_real = idxs[opcoes.index(escolha_rec)]
                if st.button("✅ Recebi esta parcela"):
                    pedido_id = parcelas_df.loc[idx_real, "PEDIDO"]
                    parcelas_df.loc[idx_real, "STATUS"] = "Pago"
                    parcelas_df.loc[idx_real, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                    pedidos = preparar_pedidos(dados("PEDIDOS"))
                    parcelas_pedido = parcelas_df[parcelas_df["PEDIDO"].astype(str) == str(pedido_id)]
                    recebido = parcelas_pedido[parcelas_pedido["STATUS"].astype(str).str.upper() == "PAGO"]["VALOR"].sum()
                    saldo = parcelas_pedido[parcelas_pedido["STATUS"].astype(str).str.upper() != "PAGO"]["VALOR"].sum()

                    if str(pedido_id) in pedidos["PEDIDO"].astype(str).tolist():
                        idxp = pedidos[pedidos["PEDIDO"].astype(str) == str(pedido_id)].index[0]
                        pedidos.loc[idxp, "VALOR RECEBIDO"] = round(recebido, 2)
                        pedidos.loc[idxp, "SALDO A RECEBER"] = round(saldo, 2)
                        pedidos.loc[idxp, "STATUS"] = "Pago" if saldo <= 0 else "Pendente"
                        if saldo <= 0:
                            pedidos.loc[idxp, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")
                        atualizar("PEDIDOS", pedidos)

                    atualizar("PARCELAS_RECEBER", parcelas_df)
                    st.success("Parcela recebida e atualizada.")
                    st.rerun()

    st.markdown("---")
    st.markdown("### 📤 Contas a pagar / fornecedores")

    if compras.empty:
        st.info("Nenhuma compra cadastrada.")
    else:
        cp = compras.copy()
        cp["VENC_DT"] = pd.to_datetime(cp["PRIMEIRO VENCIMENTO"], dayfirst=True, errors="coerce")
        cp["DIAS"] = cp["VENC_DT"].apply(lambda d: (d.date() - hoje).days if pd.notna(d) else "")
        cp_pend = cp[cp["STATUS"].astype(str).str.upper() != "PAGO"].sort_values(by=["VENC_DT"], na_position="last")
        st.dataframe(cp_pend.drop(columns=["VENC_DT"], errors="ignore"), use_container_width=True)

        if not cp_pend.empty:
            opcoes_pagar = []
            idxs_pagar = []
            for idx, row in cp_pend.iterrows():
                opcoes_pagar.append(f"{row['NF']} | {row['FORNECEDOR']} | {row['PRIMEIRO VENCIMENTO']} | {formatar_moeda(row['SALDO A PAGAR'])}")
                idxs_pagar.append(idx)

            escolha_pg = st.selectbox("Marcar compra/fornecedor como pago", [""] + opcoes_pagar)
            if escolha_pg:
                idx_real = idxs_pagar[opcoes_pagar.index(escolha_pg)]
                if st.button("✅ Paguei este fornecedor/compra"):
                    compras.loc[idx_real, "STATUS"] = "Pago"
                    compras.loc[idx_real, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")
                    compras.loc[idx_real, "SALDO A PAGAR"] = 0.0
                    atualizar("COMPRAS", compras)
                    st.success("Compra marcada como paga.")
                    st.rerun()


# ==============================================================================
# CALCULADORA PEDIDO
# ==============================================================================
elif escolha == "🛒 Calculadora de Pedido":
    st.subheader("🛒 Calculadora de Pedido do Cliente")
    produtos = preparar_produtos(dados("PRODUTOS"))

    if produtos.empty:
        st.warning("Cadastre produtos primeiro.")
    else:
        itens = []
        lista = produtos["PRODUTO"].astype(str).tolist()
        for i in range(1, 21):
            c1, c2, c3 = st.columns([4, 1, 2])
            prod = c1.selectbox(f"Produto {i}", [""] + lista, key=f"calc_prod_{i}")
            qtd = c2.number_input("Qtd", min_value=0, value=0, step=1, key=f"calc_qtd_{i}")
            preco_padrao = 0.0
            if prod:
                linha = produtos[produtos["PRODUTO"].astype(str) == prod]
                if not linha.empty:
                    preco_padrao = numero_para_float(linha.iloc[0]["PREÇO VENDA"])
            preco = c3.number_input("Preço unitário", min_value=0.0, value=preco_padrao, format="%.2f", key=f"calc_preco_{i}")
            if prod and qtd > 0:
                itens.append({"Produto": prod, "Quantidade": qtd, "Preço Unitário": preco, "Total": qtd * preco})
        if itens:
            df = pd.DataFrame(itens)
            total = df["Total"].sum()
            st.dataframe(df, use_container_width=True)
            st.metric("TOTAL DA CLIENTE", formatar_moeda(total))
            msg = "Olá ❤️ Segue o resumo do seu pedido na LuhVee Stores:\n\n"
            for item in itens:
                msg += f"• {item['Quantidade']}x {item['Produto']} — {formatar_moeda(item['Total'])}\n"
            msg += f"\nTotal: {formatar_moeda(total)}\n\nLuhVee Stores ❤️"
            st.text_area("Mensagem pronta para WhatsApp", msg, height=220)
        else:
            st.info("Escolha pelo menos um produto.")

# ==============================================================================
# CALCULADORA LUHVEE
# ==============================================================================
elif escolha == "🧮 Calculadora LuhVee":
    st.subheader("🧮 Calculadora de Preço")
    c1, c2, c3 = st.columns(3)
    custo = c1.number_input("Custo", min_value=0.0, value=10.0, format="%.2f")
    embalagem = c2.number_input("Embalagem", min_value=0.0, value=0.50, format="%.2f")
    frete = c3.number_input("Frete por item", min_value=0.0, value=0.0, format="%.2f")
    c4, c5, c6 = st.columns(3)
    taxa = c4.number_input("Taxa (%)", min_value=0.0, value=6.0, format="%.2f")
    lucro = c5.number_input("Lucro desejado (%)", min_value=0.0, value=100.0, format="%.2f")
    desconto = c6.number_input("Desconto previsto", min_value=0.0, value=0.0, format="%.2f")

    custo_total = custo + embalagem + frete
    preco_sem_taxa = custo_total * (1 + lucro / 100) + desconto
    preco_final = preco_sem_taxa / (1 - taxa / 100) if taxa < 100 else preco_sem_taxa
    taxa_valor = preco_final * taxa / 100
    lucro_liquido = preco_final - custo_total - taxa_valor - desconto
    r1, r2, r3 = st.columns(3)
    r1.metric("Preço sugerido", formatar_moeda(preco_final))
    r2.metric("Lucro líquido", formatar_moeda(lucro_liquido))
    r3.metric("Custo total", formatar_moeda(custo_total))

# ==============================================================================
# NOTA FISCAL
# ==============================================================================
elif escolha == "📑 Entrada por Nota Fiscal":
    st.subheader("📑 Entrada por Nota Fiscal PDF")
    fornecedor = st.text_input("Fornecedor padrão", "Fornecedor")
    margem = st.number_input("Margem para preço de venda (%)", min_value=0.0, value=120.0, format="%.2f")

    st.markdown("### Dados de pagamento da compra")
    cpg1, cpg2, cpg3 = st.columns(3)
    compra_pagamento = cpg1.selectbox("Forma de pagamento da compra", ["PIX", "Dinheiro", "Débito", "Crédito", "Boleto", "Fiado/Fornecedor", "Outro"])
    compra_parcelas = cpg2.selectbox("Parcelas da compra", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"])
    compra_status = cpg3.selectbox("Status da compra", ["Pago", "Pendente"])
    primeiro_venc_compra = st.date_input("Primeiro vencimento da compra", value=hoje_brasil(), format="DD/MM/YYYY")

    arquivo = st.file_uploader("Envie o PDF da nota fiscal", type=["pdf"])

    if arquivo:
        df_nf = extrair_produtos_nfe_pdf(arquivo)
        if df_nf.empty:
            st.warning("Não consegui extrair produtos automaticamente.")
        else:
            st.success(f"Encontrei {len(df_nf)} produto(s). Confira antes de adicionar.")
            df_nf["FORNECEDOR"] = fornecedor
            df_nf["PREÇO VENDA"] = df_nf["CUSTO UNITÁRIO"].apply(lambda x: round(numero_para_float(x) * (1 + margem / 100), 2))
            editado = st.data_editor(df_nf, use_container_width=True, num_rows="dynamic")

            if st.button("📦 Adicionar ao estoque"):
                produtos = preparar_produtos(dados("PRODUTOS"))
                compras = safe_df(dados("COMPRAS"), COL_COMPRAS)

                for _, row in editado.iterrows():
                    nome = str(row["PRODUTO"]).strip().upper()
                    qtd = numero_para_int(row["QUANTIDADE"])
                    custo = numero_para_float(row["CUSTO UNITÁRIO"])
                    preco = numero_para_float(row["PREÇO VENDA"])
                    forn = str(row.get("FORNECEDOR", fornecedor)).strip()
                    match = produtos["PRODUTO"].astype(str).str.strip().str.upper() == nome if not produtos.empty else pd.Series(dtype=bool)
                    if not produtos.empty and match.any():
                        idx = produtos[match].index[0]
                        produtos.loc[idx, "ESTOQUE"] = int(numero_para_int(produtos.loc[idx, "ESTOQUE"]) + qtd)
                        produtos.loc[idx, "CUSTO"] = float(custo)
                        produtos.loc[idx, "PREÇO VENDA"] = float(preco)
                        produtos.loc[idx, "FORNECEDOR"] = forn
                    else:
                        novo = {
                            "CÓDIGO": novo_id("PROD", produtos, "CÓDIGO"),
                            "PRODUTO": nome,
                            "CATEGORIA": "Cosméticos",
                            "FORNECEDOR": forn,
                            "CUSTO": custo,
                            "PREÇO VENDA": preco,
                            "ESTOQUE": qtd,
                        }
                        produtos = pd.concat([produtos, pd.DataFrame([novo])], ignore_index=True)

                valor_total_compra = round(editado["TOTAL"].apply(numero_para_float).sum(), 2)
                valor_parcela_compra = calcular_valor_parcela(valor_total_compra, compra_parcelas)
                saldo_compra = 0.0 if status_pago(compra_status) else valor_total_compra
                data_pg_compra = agora_brasil().strftime("%d/%m/%Y %H:%M") if status_pago(compra_status) else ""

                compras = pd.concat([compras, pd.DataFrame([{
                    "NF": f"NF-{agora_brasil().strftime('%Y%m%d%H%M')}",
                    "DATA": agora_brasil().strftime("%d/%m/%Y %H:%M"),
                    "FORNECEDOR": fornecedor,
                    "VALOR TOTAL": valor_total_compra,
                    "ARQUIVO PDF": arquivo.name,
                    "FORMA PAGAMENTO": compra_pagamento,
                    "PARCELAS": compra_parcelas,
                    "VALOR PARCELA": valor_parcela_compra,
                    "PRIMEIRO VENCIMENTO": pd.to_datetime(primeiro_venc_compra).strftime("%d/%m/%Y"),
                    "STATUS": compra_status,
                    "DATA PAGAMENTO": data_pg_compra,
                    "SALDO A PAGAR": saldo_compra,
                }])], ignore_index=True)

                atualizar("PRODUTOS", produtos)
                atualizar("COMPRAS", compras)
                st.success("Nota lançada e estoque atualizado.")
                st.rerun()


# ==============================================================================
# EXPORTAR PARA YAMPI
# ==============================================================================
elif escolha == "📤 Exportar para Yampi":
    st.subheader("📤 Exportar Produtos para Yampi")

    st.warning(
        "Importante: antes de importar, cadastre na Yampi a marca que será usada abaixo. "
        "A Yampi exige que a marca já exista e esteja escrita exatamente igual."
    )

    marca_padrao = st.text_input(
        "Marca cadastrada na Yampi",
        value="LuhVee Stores",
        help="Use exatamente o nome da marca que já existe na Yampi. Exemplo: LuhVee Stores."
    )

    categoria_padrao = st.text_input(
        "Categoria cadastrada na Yampi (opcional)",
        value="",
        help="Se a categoria ainda não existir na Yampi, deixe em branco para evitar erro."
    )

    incluir_categorias_do_erp = st.checkbox(
        "Usar categoria do ERP na coluna categorias",
        value=False,
        help="Marque somente se essas categorias já estiverem cadastradas na Yampi."
    )

    produtos = preparar_produtos(dados("PRODUTOS"))

    if produtos.empty:
        st.warning("Nenhum produto cadastrado no estoque.")
    else:
        colunas_yampi = [
            "id", "ativo", "possui_variacoes", "marca", "codigo_erp", "ncm", "nome",
            "buscavel", "produto_digital", "categorias", "colecoes", "filtros",
            "variacoes", "selos", "slug", "video", "descricao", "meses_de_garantia",
            "frete_customizado", "valor_do_frete", "especificacoes", "medidas",
            "valor_de_presente", "categoria_google", "seo_titulo_pagina",
            "seo_descricao", "seo_palavras_chave", "link_canonico", "termos_de_busca",
            "link_produto", "link_foto_principal"
        ]

        exportar = pd.DataFrame(columns=colunas_yampi)

        for _, row in produtos.iterrows():
            nome_produto = str(row.get("PRODUTO", "")).strip()
            if not nome_produto:
                continue

            categoria_erp = str(row.get("CATEGORIA", "")).strip()
            categoria_final = ""

            if incluir_categorias_do_erp and categoria_erp:
                categoria_final = categoria_erp
            elif categoria_padrao.strip():
                categoria_final = categoria_padrao.strip()

            codigo = str(row.get("CÓDIGO", "")).strip()

            descricao_txt = (
                f"{nome_produto}. Produto selecionado com carinho pela LuhVee Stores. "
                f"Confira disponibilidade, fragrância, cor ou variação antes da compra."
            )

            especificacoes_txt = (
                f"SKU: {codigo}. "
                f"Categoria: {categoria_erp}. "
                f"Estoque atual no ERP: {numero_para_int(row.get('ESTOQUE', 0))}."
            )

            exportar.loc[len(exportar)] = {
                "id": "",
                "ativo": "sim",
                "possui_variacoes": "nao",
                "marca": marca_padrao.strip(),
                "codigo_erp": codigo,
                "ncm": "",
                "nome": nome_produto,
                "buscavel": "sim",
                "produto_digital": "nao",
                "categorias": categoria_final,
                "colecoes": "",
                "filtros": "",
                "variacoes": "",
                "selos": "",
                "slug": "",  # deixa a Yampi criar e evita erro de slug duplicado
                "video": "",
                "descricao": descricao_txt,
                "meses_de_garantia": "",
                "frete_customizado": "nao",
                "valor_do_frete": "",
                "especificacoes": especificacoes_txt,
                "medidas": "",
                "valor_de_presente": "",
                "categoria_google": "",
                "seo_titulo_pagina": "",
                "seo_descricao": "",
                "seo_palavras_chave": "",
                "link_canonico": "",
                "termos_de_busca": nome_produto,
                "link_produto": "",
                "link_foto_principal": ""
            }

        st.markdown("### Prévia da planilha no modelo Yampi")
        st.dataframe(exportar, use_container_width=True)

        st.info(
            "Essa planilha cria o cadastro do produto. Preço, estoque, peso, medidas e fotos "
            "podem precisar ser completados depois na Yampi ou por planilha de SKUs."
        )

        csv_virgula = exportar.to_csv(index=False, sep=",", encoding="utf-8-sig").encode("utf-8-sig")

        st.download_button(
            "⬇️ Baixar CSV Yampi seguro",
            data=csv_virgula,
            file_name=f"produtos_yampi_luhvee_seguro_{agora_brasil().strftime('%d-%m-%Y_%H-%M')}.csv",
            mime="text/csv"
        )

        st.caption(
            "Antes de importar: confirme se a marca informada já existe na Yampi. "
            "Se não existir, cadastre a marca primeiro."
        )



# ==============================================================================
# BACKUP
# ==============================================================================
elif escolha == "💾 Backup ERP":
    st.subheader("💾 Backup ERP")
    arquivos = []
    for nome, df in st.session_state.dados.items():
        csv_file = CSV_MAP[nome]
        padronizar_df(nome, df).to_csv(csv_file, index=False)
        arquivos.append(csv_file)

    for csv_file in arquivos:
        if os.path.exists(csv_file):
            with open(csv_file, "rb") as f:
                st.download_button(f"⬇️ Baixar {csv_file}", data=f.read(), file_name=csv_file, mime="text/csv", key=f"b_{csv_file}")

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for csv_file in arquivos:
            if os.path.exists(csv_file):
                zip_file.write(csv_file)
    zip_buffer.seek(0)
    st.download_button("💾 Baixar Backup Completo ZIP", data=zip_buffer.getvalue(), file_name=f"BACKUP_LUHVEE_ERP_{agora_brasil().strftime('%d-%m-%Y_%H-%M')}.zip", mime="application/zip")
