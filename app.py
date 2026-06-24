import streamlit as st
import pandas as pd
import os
import re
import json
import zipfile
from io import BytesIO
from datetime import datetime, date
from zoneinfo import ZoneInfo

# Bibliotecas opcionais
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
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
except Exception:
    canvas = None
    colors = None

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
    padding: 10px 24px; font-weight: bold; transition: all 0.2s ease;
}
div.stButton > button:first-child:hover { background-color: #da70d6; color: white; border: none; }
div[data-testid="stMetricValue"] { color: #da70d6 !important; }
.luhvee-card {
    background: #17171c;
    border: 1px solid #2b2b35;
    border-radius: 12px;
    padding: 14px;
}
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='brand-title'>LuhVee Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>ERP 2.0 — Google Sheets, Estoque, Clientes, Pedidos, Nota Fiscal & Precificação</div>", unsafe_allow_html=True)

# ==============================================================================
# ESTRUTURA DAS ABAS GOOGLE SHEETS
# ==============================================================================
COL_CLIENTES = ["ID", "NOME", "WHATSAPP", "CIDADE", "ENDEREÇO", "CPF", "OBSERVAÇÕES", "DATA CADASTRO"]
COL_PRODUTOS = ["CÓDIGO", "PRODUTO", "CATEGORIA", "FORNECEDOR", "CUSTO", "PREÇO VENDA", "ESTOQUE"]
COL_PEDIDOS = ["PEDIDO", "DATA", "CLIENTE", "WHATSAPP", "PAGAMENTO", "PARCELAS", "VALOR PARCELA", "PLATAFORMA", "TOTAL", "STATUS", "DATA PAGAMENTO", "VALOR RECEBIDO", "SALDO A RECEBER"]
COL_ITENS = ["PEDIDO", "PRODUTO", "QUANTIDADE", "PREÇO", "TOTAL", "LUCRO"]
COL_COMPRAS = ["NF", "DATA", "FORNECEDOR", "VALOR TOTAL", "ARQUIVO PDF"]
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
# FUNÇÕES DE CONVERSÃO
# ==============================================================================
def numero_para_float(valor, padrao=0.0):
    try:
        if pd.isna(valor):
            return padrao
        if isinstance(valor, str):
            valor = valor.replace("R$", "").replace(" ", "").strip()
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

def normalizar_texto(txt):
    return str(txt).strip().upper()

def agora_brasil():
    """Horário oficial de São Paulo para pedidos, clientes e compras."""
    return datetime.now(ZoneInfo("America/Sao_Paulo"))

def novo_id(prefixo, df, coluna):
    if df is None or df.empty or coluna not in df.columns:
        return f"{prefixo}-0001"
    numeros = []
    for item in df[coluna].astype(str).tolist():
        try:
            numeros.append(int(item.replace(f"{prefixo}-", "").replace(prefixo, "").replace("-", "")))
        except Exception:
            pass
    prox = max(numeros) + 1 if numeros else 1
    return f"{prefixo}-{prox:04d}"

def quantidade_parcelas(parcelas):
    texto = str(parcelas).strip().lower()
    if "vista" in texto or texto == "" or texto == "nan":
        return 1
    m = re.search(r"(\d+)", texto)
    return max(1, int(m.group(1))) if m else 1

def calcular_valor_parcela(total, parcelas):
    qtd = quantidade_parcelas(parcelas)
    return round(numero_para_float(total) / qtd, 2) if qtd > 0 else numero_para_float(total)

def status_pago(status):
    return str(status).strip().upper() in ["PAGO", "PAGA", "RECEBIDO", "RECEBIDA", "ENTREGUE"]

def calcular_valores_pagamento(total, status):
    total = numero_para_float(total)
    if status_pago(status):
        return total, 0.0
    return 0.0, total

def gerar_datas_vencimento(primeiro_vencimento, qtd_parcelas):
    datas = []
    try:
        base = pd.to_datetime(primeiro_vencimento).date()
    except Exception:
        base = agora_brasil().date()

    for i in range(qtd_parcelas):
        venc = pd.Timestamp(base) + pd.DateOffset(months=i)
        datas.append(venc.strftime("%d/%m/%Y"))
    return datas

def gerar_parcelas_pedido(pedido_id, cliente, whatsapp, parcelas, total, primeiro_vencimento, status_pedido):
    qtd = quantidade_parcelas(parcelas)
    valor_parcela = calcular_valor_parcela(total, parcelas)

    # Se for à vista e já pago, cria uma parcela paga para histórico.
    vencimentos = gerar_datas_vencimento(primeiro_vencimento, qtd)
    linhas = []

    for i in range(1, qtd + 1):
        pago = status_pago(status_pedido)
        linhas.append({
            "PEDIDO": pedido_id,
            "CLIENTE": cliente,
            "WHATSAPP": whatsapp,
            "PARCELA": f"{i}/{qtd}",
            "VENCIMENTO": vencimentos[i - 1],
            "VALOR": round(valor_parcela, 2),
            "STATUS": "Pago" if pago else "Pendente",
            "DATA PAGAMENTO": agora_brasil().strftime("%d/%m/%Y %H:%M") if pago else ""
        })

    return pd.DataFrame(linhas)

def preparar_pedidos_para_calculo(df):
    if df is None:
        df = pd.DataFrame()

    df = pd.DataFrame(df.astype(str).to_dict("records"))

    extras = {
        "VALOR PARCELA": "0",
        "DATA PAGAMENTO": "",
        "VALOR RECEBIDO": "0",
        "SALDO A RECEBER": "0",
    }

    for col, padrao in extras.items():
        if col not in df.columns:
            df[col] = padrao

    if "TOTAL" not in df.columns:
        df["TOTAL"] = "0"

    for col in ["TOTAL", "VALOR PARCELA", "VALOR RECEBIDO", "SALDO A RECEBER"]:
        df[col] = df[col].apply(numero_para_float).astype(float)

    return df.copy()

def preparar_parcelas_para_calculo(df):
    if df is None:
        df = pd.DataFrame(columns=COL_PARCELAS)

    df = pd.DataFrame(df.astype(str).to_dict("records")) if not df.empty else pd.DataFrame(columns=COL_PARCELAS)

    for col in COL_PARCELAS:
        if col not in df.columns:
            df[col] = ""

    df = df[COL_PARCELAS]
    if "VALOR" in df.columns:
        df["VALOR"] = df["VALOR"].apply(numero_para_float).astype(float)

    return df.copy()

def quantidade_parcelas(parcelas):
    texto = str(parcelas).strip().lower()
    if "vista" in texto or texto == "" or texto == "nan":
        return 1
    m = re.search(r"(\d+)", texto)
    return max(1, int(m.group(1))) if m else 1

def calcular_valor_parcela(total, parcelas):
    qtd = quantidade_parcelas(parcelas)
    return round(numero_para_float(total) / qtd, 2) if qtd > 0 else numero_para_float(total)

def status_pago(status):
    return str(status).strip().upper() in ["PAGO", "PAGA", "RECEBIDO", "RECEBIDA", "ENTREGUE"]

def calcular_valores_pagamento(total, status):
    total = numero_para_float(total)
    if status_pago(status):
        return total, 0.0
    return 0.0, total

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
    if not tem_secrets_google():
        return None

    if gspread is None or Credentials is None:
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

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
        ws = ss.add_worksheet(title=nome_aba, rows=1000, cols=30)
        ws.append_row(ABAS[nome_aba])
    return ws

def padronizar_df(nome_aba, df):
    colunas = ABAS[nome_aba]
    df = df.copy() if df is not None else pd.DataFrame()

    # Conversão para compatibilidade com app antigo
    if nome_aba == "PRODUTOS":
        mapa_antigo = {
            "Código": "CÓDIGO",
            "Produto": "PRODUTO",
            "Categoria": "CATEGORIA",
            "Fornecedor": "FORNECEDOR",
            "Custo Real": "CUSTO",
            "Custo Nota": "CUSTO",
            "Preço Venda": "PREÇO VENDA",
            "Estoque Atual": "ESTOQUE",
        }
        for velho, novo in mapa_antigo.items():
            if velho in df.columns and novo not in df.columns:
                df[novo] = df[velho]

    if nome_aba == "CLIENTES":
        mapa_antigo = {
            "Nome": "NOME",
            "WhatsApp": "WHATSAPP",
            "Cidade": "CIDADE",
            "Endereço": "ENDEREÇO",
            "CPF": "CPF",
            "Observações": "OBSERVAÇÕES",
            "Data Cadastro": "DATA CADASTRO",
        }
        for velho, novo in mapa_antigo.items():
            if velho in df.columns and novo not in df.columns:
                df[novo] = df[velho]

    if nome_aba == "PEDIDOS":
        mapa_antigo = {
            "Pedido": "PEDIDO",
            "Data": "DATA",
            "Cliente": "CLIENTE",
            "WhatsApp": "WHATSAPP",
            "Forma Pagamento": "PAGAMENTO",
            "Parcelas": "PARCELAS",
            "Plataforma": "PLATAFORMA",
            "Total Pedido": "TOTAL",
            "Status": "STATUS",
            "Data Pagamento": "DATA PAGAMENTO",
            "Valor Recebido": "VALOR RECEBIDO",
            "Saldo a Receber": "SALDO A RECEBER",
        }
        for velho, novo in mapa_antigo.items():
            if velho in df.columns and novo not in df.columns:
                df[novo] = df[velho]

    if nome_aba == "ITENS_PEDIDO":
        mapa_antigo = {
            "Pedido": "PEDIDO",
            "Produto": "PRODUTO",
            "Quantidade": "QUANTIDADE",
            "Preço Unitário": "PREÇO",
            "Total Item": "TOTAL",
            "Lucro Item": "LUCRO",
        }
        for velho, novo in mapa_antigo.items():
            if velho in df.columns and novo not in df.columns:
                df[novo] = df[velho]

    for c in colunas:
        if c not in df.columns:
            df[c] = ""

    df = df[colunas]
    return df.fillna("")



def preparar_pedidos_para_calculo(df):
    """
    Corrige tipos vindos do Google Sheets/Streamlit.
    Recria o DataFrame para remover Arrow/StringDtype e permitir salvar números.
    """
    if df is None:
        df = pd.DataFrame()

    # Remove dtypes especiais do Streamlit/Arrow
    df = pd.DataFrame(df.astype(str).to_dict("records"))

    colunas_necessarias = {
        "VALOR PARCELA": "0",
        "DATA PAGAMENTO": "",
        "VALOR RECEBIDO": "0",
        "SALDO A RECEBER": "0",
    }

    for col, padrao in colunas_necessarias.items():
        if col not in df.columns:
            df[col] = padrao

    if "TOTAL" not in df.columns:
        df["TOTAL"] = "0"

    for col in ["TOTAL", "VALOR PARCELA", "VALOR RECEBIDO", "SALDO A RECEBER"]:
        df[col] = df[col].apply(numero_para_float)

    # Força tipos normais do Pandas, não Arrow
    df["TOTAL"] = df["TOTAL"].astype(float)
    df["VALOR PARCELA"] = df["VALOR PARCELA"].astype(float)
    df["VALOR RECEBIDO"] = df["VALOR RECEBIDO"].astype(float)
    df["SALDO A RECEBER"] = df["SALDO A RECEBER"].astype(float)

    return df.copy()


def preparar_produtos_para_calculo(df):
    """
    Corrige tipos vindos do Google Sheets.
    O Google Sheets traz tudo como texto; antes de baixar estoque ou calcular lucro,
    precisamos transformar ESTOQUE, CUSTO e PREÇO VENDA em números.
    """
    df = df.copy()
    if "ESTOQUE" in df.columns:
        df["ESTOQUE"] = df["ESTOQUE"].apply(numero_para_int).astype("int64")
    if "CUSTO" in df.columns:
        df["CUSTO"] = df["CUSTO"].apply(numero_para_float).astype("float64")
    if "PREÇO VENDA" in df.columns:
        df["PREÇO VENDA"] = df["PREÇO VENDA"].apply(numero_para_float).astype("float64")
    return df

def carregar_aba(nome_aba):
    colunas = ABAS[nome_aba]
    csv_file = CSV_MAP[nome_aba]

    ws = obter_worksheet(nome_aba)
    if ws is not None:
        try:
            valores = ws.get_all_values()
            if len(valores) <= 1:
                # Se a planilha está vazia, tenta carregar CSV antigo para migrar
                if os.path.exists(csv_file):
                    df_csv = pd.read_csv(csv_file)
                    df_csv = padronizar_df(nome_aba, df_csv)
                    if not df_csv.empty:
                        salvar_aba(nome_aba, df_csv, salvar_csv=True, salvar_google=True)
                    return df_csv
                return pd.DataFrame(columns=colunas)

            headers = valores[0]
            rows = valores[1:]
            df = pd.DataFrame(rows, columns=headers)
            return padronizar_df(nome_aba, df)
        except Exception:
            pass

    if os.path.exists(csv_file):
        try:
            df = pd.read_csv(csv_file)
            return padronizar_df(nome_aba, df)
        except Exception:
            pass

    return pd.DataFrame(columns=colunas)

def salvar_aba(nome_aba, df, salvar_csv=True, salvar_google=True):
    colunas = ABAS[nome_aba]
    csv_file = CSV_MAP[nome_aba]
    df = padronizar_df(nome_aba, df)

    if salvar_csv:
        df.to_csv(csv_file, index=False)

    if salvar_google:
        ws = obter_worksheet(nome_aba)
        if ws is not None:
            ws.clear()
            ws.update([colunas] + df.astype(str).values.tolist())

def carregar_tudo():
    return {nome: carregar_aba(nome) for nome in ABAS.keys()}

if "dados" not in st.session_state:
    st.session_state.dados = carregar_tudo()
else:
    # Quando uma versão nova adiciona abas, garante que elas sejam criadas/carregadas.
    for _nome_aba in ABAS.keys():
        if _nome_aba not in st.session_state.dados:
            st.session_state.dados[_nome_aba] = carregar_aba(_nome_aba)

def dados(nome):
    # Garante que novas abas adicionadas em atualizações sejam carregadas mesmo
    # quando o Streamlit ainda está com a sessão antiga em memória.
    if "dados" not in st.session_state:
        st.session_state.dados = carregar_tudo()

    if nome not in st.session_state.dados:
        st.session_state.dados[nome] = carregar_aba(nome)

    return st.session_state.dados[nome]

def atualizar(nome, df):
    st.session_state.dados[nome] = padronizar_df(nome, df)
    salvar_aba(nome, st.session_state.dados[nome])

# ==============================================================================
# PDF RECIBO A6
# ==============================================================================
def gerar_pdf_recibo(pedido_info, itens, parcelas_do_pedido=None):
    """
    Recibo A6 compacto.
    Mostra itens, total e parcelas do crediário/cartão quando existirem.
    """
    if canvas is None:
        return None

    buffer = BytesIO()
    largura = 105 * mm
    altura = 148 * mm
    pdf = canvas.Canvas(buffer, pagesize=(largura, altura))

    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#444444")
    margem = 6 * mm
    y = altura - 7 * mm

    def linha(espaco=3):
        nonlocal y
        pdf.setStrokeColor(rosa)
        pdf.setLineWidth(0.45)
        pdf.line(margem, y, largura - margem, y)
        y -= espaco * mm

    def central(txt, fonte="Helvetica-Bold", tamanho=8, cor=preto, espaco=None):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawCentredString(largura / 2, y, str(txt))
        y -= ((espaco if espaco is not None else tamanho * 0.38) * mm)

    def esquerda(txt, fonte="Helvetica", tamanho=6.4, cor=preto, espaco=3):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawString(margem, y, str(txt)[:74])
        y -= espaco * mm

    def item_linha(esq, dir_, tamanho=6.0):
        nonlocal y
        pdf.setFont("Helvetica", tamanho)
        pdf.setFillColor(preto)
        pdf.drawString(margem, y, str(esq)[:52])
        pdf.drawRightString(largura - margem, y, str(dir_))
        y -= 2.8 * mm

    def nova_pagina():
        nonlocal y
        pdf.showPage()
        y = altura - 7 * mm
        central("LUHVEE STORES", "Helvetica-Bold", 10, rosa, 4)
        central("Continuação do recibo", "Helvetica", 5.5, cinza, 3)
        linha(3)

    central("LUHVEE STORES", "Helvetica-Bold", 11, rosa, 4)
    central("Curadoria Inteligente & Achadinhos Exclusivos", "Helvetica", 5.5, cinza, 3)
    linha(3)

    central("RECIBO DE VENDA", "Helvetica-Bold", 8, preto, 4)

    esquerda(f"Pedido: {pedido_info.get('PEDIDO','')}", "Helvetica-Bold", 6.5, preto, 3)
    esquerda(f"Data: {pedido_info.get('DATA','')}", "Helvetica", 6.2, preto, 3)
    linha(3)

    esquerda("CLIENTE", "Helvetica-Bold", 6.7, rosa, 3)
    esquerda(f"Nome: {pedido_info.get('CLIENTE','')}", "Helvetica", 6.2, preto, 3)
    esquerda(f"WhatsApp: {pedido_info.get('WHATSAPP','')}", "Helvetica", 6.2, preto, 3)
    linha(3)

    total_pdf = numero_para_float(pedido_info.get("TOTAL", 0))
    parcelas_pdf = pedido_info.get("PARCELAS", "À vista")
    valor_parcela_pdf = numero_para_float(
        pedido_info.get("VALOR PARCELA", calcular_valor_parcela(total_pdf, parcelas_pdf))
    )
    saldo_pdf = numero_para_float(
        pedido_info.get("SALDO A RECEBER", total_pdf if not status_pago(pedido_info.get("STATUS", "")) else 0)
    )

    esquerda("DETALHES", "Helvetica-Bold", 6.7, rosa, 3)
    esquerda(f"Plataforma: {pedido_info.get('PLATAFORMA','')}", "Helvetica", 6.2, preto, 3)
    esquerda(f"Pagamento: {pedido_info.get('PAGAMENTO','')} - {parcelas_pdf}", "Helvetica", 6.2, preto, 3)
    if quantidade_parcelas(parcelas_pdf) > 1:
        esquerda(f"Parcela: {formatar_moeda(valor_parcela_pdf)}", "Helvetica", 6.2, preto, 3)
    esquerda(f"Status: {pedido_info.get('STATUS','')}", "Helvetica", 6.2, preto, 3)
    if saldo_pdf > 0:
        esquerda(f"A receber: {formatar_moeda(saldo_pdf)}", "Helvetica-Bold", 6.2, rosa, 3)
    linha(3)

    esquerda("PRODUTOS", "Helvetica-Bold", 6.7, rosa, 3)

    for _, item in itens.iterrows():
        if y < 30 * mm:
            nova_pagina()
        qtd = numero_para_int(item.get("QUANTIDADE", 1), 1)
        produto = str(item.get("PRODUTO", ""))[:45]
        valor = formatar_moeda(numero_para_float(item.get("TOTAL", 0)))
        item_linha(f"{qtd}x {produto}", valor, 5.8)

    # Parcelas no recibo
    if parcelas_do_pedido is not None and not parcelas_do_pedido.empty:
        if y < 35 * mm:
            nova_pagina()

        linha(3)
        esquerda("PARCELAS", "Helvetica-Bold", 6.7, rosa, 3)

        parcelas_print = parcelas_do_pedido.copy()
        for _, parc in parcelas_print.iterrows():
            if y < 22 * mm:
                nova_pagina()
                esquerda("PARCELAS", "Helvetica-Bold", 6.7, rosa, 3)

            venc = str(parc.get("VENCIMENTO", ""))
            valor = formatar_moeda(numero_para_float(parc.get("VALOR", 0)))
            stat = str(parc.get("STATUS", "Pendente"))
            item_linha(f"{venc} - {valor}", stat, 5.7)

    if y < 26 * mm:
        nova_pagina()

    linha(3)
    central("TOTAL DO PEDIDO", "Helvetica-Bold", 6.5, preto, 3)
    central(formatar_moeda(total_pdf), "Helvetica-Bold", 12, rosa, 5)

    linha(3)
    central("Obrigada pela preferência ❤️", "Helvetica-Oblique", 6, preto, 3)
    central("LuhVee Stores", "Helvetica-Bold", 6.5, rosa, 3)

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# NOTA FISCAL PDF
# ==============================================================================
def extrair_produtos_nfe_pdf(arquivo_pdf):
    """
    Leitor mais flexível de DANFE/NF-e em PDF.
    Tenta ler tabela e também texto corrido.
    Ignora ICMS, IPI e tributos.
    """
    if pdfplumber is None:
        return pd.DataFrame(columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])

    produtos = []

    def adicionar_produto(nome, qtd, custo, total):
        nome = " ".join(str(nome).replace("\n", " ").split()).strip().upper()
        qtd = numero_para_float(qtd)
        custo = numero_para_float(custo)
        total = numero_para_float(total)

        if not nome or qtd <= 0 or custo <= 0:
            return

        ignorar = [
            "DADOS DO PRODUTO", "DESCRIÇÃO DO PRODUTO", "VALOR UNITARIO",
            "VALOR TOTAL", "CÁLCULO DO IMPOSTO", "TRANSPORTADOR",
            "INFORMAÇÕES COMPLEMENTARES", "RESERVADO AO FISCO"
        ]
        if any(x in nome for x in ignorar):
            return

        produtos.append({
            "PRODUTO": nome,
            "QUANTIDADE": int(round(qtd)),
            "CUSTO UNITÁRIO": round(custo, 2),
            "TOTAL": round(total, 2)
        })

    texto_total = ""

    try:
        with pdfplumber.open(arquivo_pdf) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text() or ""
                texto_total += "\n" + texto_pagina

                try:
                    tabelas = pagina.extract_tables()
                except Exception:
                    tabelas = []

                for tabela in tabelas or []:
                    for row in tabela:
                        if not row:
                            continue

                        row_limpa = [("" if c is None else str(c).strip()) for c in row]
                        linha = " ".join(row_limpa)

                        if "UN" not in linha:
                            continue

                        try:
                            idx_un = row_limpa.index("UN")
                        except ValueError:
                            continue

                        if idx_un + 3 < len(row_limpa):
                            qtd = row_limpa[idx_un + 1]
                            custo = row_limpa[idx_un + 2]
                            total = row_limpa[idx_un + 3]

                            desc_partes = []
                            for c in row_limpa[1:idx_un]:
                                if c and not re.fullmatch(r"\d{2,}", c) and c not in ["0", "60", "5405"]:
                                    desc_partes.append(c)

                            nome = " ".join(desc_partes)
                            adicionar_produto(nome, qtd, custo, total)
    except Exception:
        pass

    if not produtos:
        linhas = [" ".join(l.split()) for l in texto_total.splitlines() if l.strip()]
        buffer_nome = ""

        for linha in linhas:
            m = re.search(r"^(.*?)\s+0\s+60\s+5405\s+UN\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)", linha)
            if m:
                nome = (buffer_nome + " " + m.group(1)).strip()
                adicionar_produto(nome, m.group(2), m.group(3), m.group(4))
                buffer_nome = ""
                continue

            m2 = re.search(r"^(.*?)\s+UN\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)", linha)
            if m2:
                nome = (buffer_nome + " " + m2.group(1)).strip()
                adicionar_produto(nome, m2.group(2), m2.group(3), m2.group(4))
                buffer_nome = ""
                continue

            if (
                len(linha) < 80
                and not any(x in linha.upper() for x in ["DANFE", "NF-E", "CHAVE", "PROTOCOLO", "DESTINATÁRIO", "CÁLCULO", "TRANSPORTADOR", "FATURA"])
                and not re.search(r"\d+,\d{2,4}\s+\d+,\d{2}", linha)
            ):
                buffer_nome = (buffer_nome + " " + linha).strip()[-160:]

    if produtos:
        df = pd.DataFrame(produtos)
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
    "💰 Contas a Receber",
    "🧮 Calculadora LuhVee",
    "🛒 Calculadora de Pedido",
    "📑 Entrada por Nota Fiscal",
    "💾 Backup ERP",
    "🔧 Status Google Sheets"
]

escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# ==============================================================================
# STATUS GOOGLE
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
        st.info("Confira se os Secrets estão corretos, se a planilha foi compartilhada como Editor e se o requirements.txt tem gspread e google-auth.")

# ==============================================================================
# DASHBOARD
# ==============================================================================
elif escolha == "Dashboard":
    st.subheader("📊 Dashboard Geral")

    produtos = dados("PRODUTOS")
    pedidos = dados("PEDIDOS")
    clientes = dados("CLIENTES")

    total_estoque = 0.0
    if not produtos.empty:
        for _, row in produtos.iterrows():
            total_estoque += numero_para_float(row.get("CUSTO", 0)) * numero_para_int(row.get("ESTOQUE", 0))

    total_vendido = 0.0
    if not pedidos.empty:
        total_vendido = sum(numero_para_float(v) for v in pedidos["TOTAL"].tolist())

    total_recebido = 0.0
    total_a_receber = 0.0
    if not pedidos.empty:
        if "VALOR RECEBIDO" in pedidos.columns:
            total_recebido = sum(numero_para_float(v) for v in pedidos["VALOR RECEBIDO"].tolist())
        else:
            total_recebido = sum(numero_para_float(row.get("TOTAL", 0)) for _, row in pedidos.iterrows() if status_pago(row.get("STATUS", "")))

        if "SALDO A RECEBER" in pedidos.columns:
            total_a_receber = sum(numero_para_float(v) for v in pedidos["SALDO A RECEBER"].tolist())
        else:
            total_a_receber = sum(numero_para_float(row.get("TOTAL", 0)) for _, row in pedidos.iterrows() if not status_pago(row.get("STATUS", "")))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Produtos", len(produtos))
    col2.metric("Clientes", len(clientes))
    col3.metric("Pedidos", len(pedidos))
    col4.metric("Faturamento", formatar_moeda(total_vendido))

    col5, col6, col7 = st.columns(3)
    col5.metric("Investimento em Estoque", formatar_moeda(total_estoque))
    col6.metric("Recebido", formatar_moeda(total_recebido))
    col7.metric("A Receber", formatar_moeda(total_a_receber))

    st.markdown("### 📦 Produtos com Estoque Baixo")
    if produtos.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        temp = produtos.copy()
        temp["ESTOQUE_NUM"] = temp["ESTOQUE"].apply(numero_para_int)
        baixo = temp[temp["ESTOQUE_NUM"] <= 2].drop(columns=["ESTOQUE_NUM"])
        st.dataframe(baixo, use_container_width=True)

# ==============================================================================
# CLIENTES
# ==============================================================================
elif escolha == "👥 Clientes":
    st.subheader("👥 Cadastro de Clientes")
    clientes = dados("CLIENTES")

    with st.form("form_cliente", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome")
        whatsapp = c2.text_input("WhatsApp")

        c3, c4 = st.columns(2)
        cidade = c3.text_input("Cidade")
        cpf = c4.text_input("CPF opcional")

        endereco = st.text_input("Endereço")
        obs = st.text_area("Observações")

        if st.form_submit_button("Salvar Cliente"):
            if not nome.strip():
                st.error("Informe o nome.")
            else:
                nome_up = nome.strip().upper()
                whats = whatsapp.strip()

                duplicado = False
                if not clientes.empty:
                    if nome_up in clientes["NOME"].astype(str).str.strip().str.upper().tolist():
                        duplicado = True
                    if whats and whats in clientes["WHATSAPP"].astype(str).str.strip().tolist():
                        duplicado = True

                if duplicado:
                    st.warning("Esse cliente parece já estar cadastrado.")
                else:
                    novo = {
                        "ID": novo_id("CLI", clientes, "ID"),
                        "NOME": nome.strip(),
                        "WHATSAPP": whats,
                        "CIDADE": cidade.strip(),
                        "ENDEREÇO": endereco.strip(),
                        "CPF": cpf.strip(),
                        "OBSERVAÇÕES": obs.strip(),
                        "DATA CADASTRO": agora_brasil().strftime("%d/%m/%Y %H:%M")
                    }
                    clientes = pd.concat([clientes, pd.DataFrame([novo])], ignore_index=True)
                    atualizar("CLIENTES", clientes)
                    st.success("Cliente salvo.")
                    st.rerun()

    st.markdown("### Clientes cadastrados")
    editado = st.data_editor(clientes, use_container_width=True, num_rows="dynamic")
    if st.button("Salvar alterações dos clientes"):
        atualizar("CLIENTES", editado)
        st.success("Clientes atualizados.")
        st.rerun()

# ==============================================================================
# PRODUTOS / ESTOQUE
# ==============================================================================
elif escolha == "📦 Produtos / Estoque":
    st.subheader("📦 Produtos / Estoque")
    produtos = dados("PRODUTOS")

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
                    "ESTOQUE": int(estoque)
                }
                produtos = pd.concat([produtos, pd.DataFrame([novo])], ignore_index=True)
                atualizar("PRODUTOS", produtos)
                st.success("Produto salvo.")
                st.rerun()

    st.markdown("### Estoque atual")
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

    clientes = dados("CLIENTES")
    produtos = preparar_produtos_para_calculo(dados("PRODUTOS"))
    pedidos = preparar_pedidos_para_calculo(dados("PEDIDOS"))
    itens_pedido = dados("ITENS_PEDIDO")

    if clientes.empty or produtos.empty:
        st.warning("Cadastre pelo menos 1 cliente e 1 produto antes de criar pedido.")
    else:
        pedido_id = novo_id("PED", pedidos, "PEDIDO")
        st.markdown(f"### Pedido: **{pedido_id}**")

        with st.form("form_pedido"):
            c1, c2, c3 = st.columns(3)
            cliente_nome = c1.selectbox("Cliente", clientes["NOME"].astype(str).tolist())
            pagamento = c2.selectbox("Pagamento", ["PIX", "Dinheiro", "Débito", "Crédito", "Crediário LuhVee", "Mercado Pago", "PagBank", "PicPay"])
            parcelas = c3.selectbox("Parcelas", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "10x", "12x"])

            c4, c5 = st.columns(2)
            plataforma = c4.selectbox("Plataforma", ["WhatsApp", "Instagram", "Loja Física", "Yampi", "Shopee", "Mercado Livre", "iFood"])
            status = c5.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"])

            qtd_parcelas_preview = quantidade_parcelas(parcelas)
            primeiro_vencimento = st.date_input(
                "Primeiro vencimento das parcelas",
                value=agora_brasil().date(),
                help="Use principalmente para Crediário LuhVee ou vendas parceladas."
            )

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
                        preco_padrao = numero_para_float(linha.iloc[0].get("PREÇO VENDA", 0))

                preco = p3.number_input("Preço", min_value=0.0, value=preco_padrao, format="%.2f", key=f"preco_{i}")

                if prod and qtd > 0:
                    itens_temp.append({"PRODUTO": prod, "QUANTIDADE": qtd, "PREÇO": preco})

            finalizar = st.form_submit_button("Finalizar Pedido")

        if finalizar:
            if not itens_temp:
                st.error("Adicione pelo menos 1 produto.")
            else:
                erro = False
                mensagens = []

                for item in itens_temp:
                    prod = item["PRODUTO"]
                    qtd = item["QUANTIDADE"]
                    linha = produtos[produtos["PRODUTO"].astype(str) == prod]
                    estoque_atual = numero_para_int(linha.iloc[0].get("ESTOQUE", 0)) if not linha.empty else 0
                    if estoque_atual < qtd:
                        erro = True
                        mensagens.append(f"{prod}: estoque {estoque_atual}, pedido {qtd}")

                if erro:
                    for m in mensagens:
                        st.error(m)
                else:
                    cliente_row = clientes[clientes["NOME"].astype(str) == cliente_nome].iloc[0]
                    whatsapp = cliente_row.get("WHATSAPP", "")

                    total_pedido = 0.0
                    novos_itens = []

                    for item in itens_temp:
                        prod = item["PRODUTO"]
                        qtd = int(item["QUANTIDADE"])
                        preco = numero_para_float(item["PREÇO"])
                        idx = produtos[produtos["PRODUTO"].astype(str) == prod].index[0]
                        custo = numero_para_float(produtos.loc[idx, "CUSTO"])
                        total_item = qtd * preco
                        lucro = total_item - (qtd * custo)

                        produtos.at[idx, "ESTOQUE"] = int(numero_para_int(produtos.at[idx, "ESTOQUE"]) - qtd)

                        novos_itens.append({
                            "PEDIDO": pedido_id,
                            "PRODUTO": prod,
                            "QUANTIDADE": qtd,
                            "PREÇO": round(preco, 2),
                            "TOTAL": round(total_item, 2),
                            "LUCRO": round(lucro, 2)
                        })
                        total_pedido += total_item

                    valor_parcela = calcular_valor_parcela(total_pedido, parcelas)
                    valor_recebido, saldo_a_receber = calcular_valores_pagamento(total_pedido, status)
                    data_pagamento = agora_brasil().strftime("%d/%m/%Y %H:%M") if status_pago(status) else ""

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
                        "DATA PAGAMENTO": data_pagamento,
                        "VALOR RECEBIDO": round(valor_recebido, 2),
                        "SALDO A RECEBER": round(saldo_a_receber, 2)
                    }

                    pedidos = pd.concat([pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
                    itens_pedido = pd.concat([itens_pedido, pd.DataFrame(novos_itens)], ignore_index=True)

                    novas_parcelas = gerar_parcelas_pedido(
                        pedido_id,
                        cliente_nome,
                        whatsapp,
                        parcelas,
                        total_pedido,
                        primeiro_vencimento,
                        status
                    )
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
    pedidos = dados("PEDIDOS")
    itens_pedido = dados("ITENS_PEDIDO")
    parcelas_receber = preparar_parcelas_para_calculo(dados("PARCELAS_RECEBER"))

    if pedidos.empty:
        st.info("Nenhum pedido cadastrado.")
    else:
        st.dataframe(pedidos, use_container_width=True)

        pedido_sel = st.selectbox("Abrir pedido", pedidos["PEDIDO"].astype(str).tolist())
        pedido_info = pedidos[pedidos["PEDIDO"].astype(str) == pedido_sel].iloc[0].to_dict()
        itens = itens_pedido[itens_pedido["PEDIDO"].astype(str) == pedido_sel]

        st.markdown("### Resumo financeiro do pedido")
        total_pedido_atual = numero_para_float(pedido_info.get("TOTAL", 0))
        parcelas_atual = pedido_info.get("PARCELAS", "À vista")
        valor_parcela_atual = numero_para_float(pedido_info.get("VALOR PARCELA", calcular_valor_parcela(total_pedido_atual, parcelas_atual)))
        valor_recebido_atual = numero_para_float(pedido_info.get("VALOR RECEBIDO", 0))
        saldo_atual = numero_para_float(pedido_info.get("SALDO A RECEBER", total_pedido_atual if not status_pago(pedido_info.get("STATUS", "")) else 0))

        cfin1, cfin2, cfin3, cfin4 = st.columns(4)
        cfin1.metric("Total", formatar_moeda(total_pedido_atual))
        cfin2.metric("Parcelas", str(parcelas_atual))
        cfin3.metric("Valor da parcela", formatar_moeda(valor_parcela_atual))
        cfin4.metric("A receber", formatar_moeda(saldo_atual))

        st.markdown("### Atualizar pagamento / status")
        opcoes_status = ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"]
        status_atual = pedido_info.get("STATUS", "Pendente")
        idx_status = opcoes_status.index(status_atual) if status_atual in opcoes_status else 1

        novo_status = st.selectbox(
            "Status do pedido",
            opcoes_status,
            index=idx_status,
            key=f"status_update_{pedido_sel}"
        )

        valor_sugerido = valor_recebido_atual if valor_recebido_atual > 0 else (total_pedido_atual if status_pago(novo_status) else 0.0)
        valor_recebido_manual = st.number_input(
            "Valor recebido até agora",
            min_value=0.0,
            value=float(valor_sugerido),
            format="%.2f",
            key=f"valor_recebido_{pedido_sel}"
        )

        if st.button("💰 Salvar pagamento/status"):
            pedidos = preparar_pedidos_para_calculo(pedidos)
            idx_pedido = pedidos[pedidos["PEDIDO"].astype(str) == pedido_sel].index[0]
            saldo_novo = max(0.0, total_pedido_atual - valor_recebido_manual)

            pedidos.loc[idx_pedido, "STATUS"] = novo_status
            pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = float(round(valor_recebido_manual, 2))
            pedidos.loc[idx_pedido, "SALDO A RECEBER"] = float(round(saldo_novo, 2))
            pedidos.loc[idx_pedido, "VALOR PARCELA"] = float(round(calcular_valor_parcela(total_pedido_atual, parcelas_atual), 2))

            if status_pago(novo_status) and not str(pedidos.at[idx_pedido, "DATA PAGAMENTO"]).strip():
                pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

            if saldo_novo <= 0 and novo_status == "Pendente":
                pedidos.at[idx_pedido, "STATUS"] = "Pago"
                if not str(pedidos.at[idx_pedido, "DATA PAGAMENTO"]).strip():
                    pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

            atualizar("PEDIDOS", pedidos)
            st.success("Pagamento/status atualizado com sucesso.")
            st.rerun()

        st.markdown("### Itens do pedido")
        st.dataframe(itens, use_container_width=True)

        parcelas_pdf = parcelas_receber[parcelas_receber["PEDIDO"].astype(str) == str(pedido_sel)] if not parcelas_receber.empty else pd.DataFrame(columns=COL_PARCELAS)
        pdf_bytes = gerar_pdf_recibo(pedido_info, itens, parcelas_pdf)
        if pdf_bytes:
            st.download_button("📄 Baixar Recibo A6 PDF", data=pdf_bytes, file_name=f"recibo_{pedido_sel}.pdf", mime="application/pdf")

        st.markdown("### Excluir pedido errado")
        confirmar = st.checkbox(f"Confirmo excluir o pedido {pedido_sel}")
        if st.button("🗑️ Excluir pedido"):
            if confirmar:
                pedidos = pedidos[pedidos["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                itens_pedido = itens_pedido[itens_pedido["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                atualizar("PEDIDOS", pedidos)
                atualizar("ITENS_PEDIDO", itens_pedido)
                st.success("Pedido excluído.")
                st.rerun()
            else:
                st.error("Confirme antes de excluir.")


# ==============================================================================
# CONTAS A RECEBER
# ==============================================================================
elif escolha == "💰 Contas a Receber":
    st.subheader("💰 Contas a Receber")

    pedidos = preparar_pedidos_para_calculo(dados("PEDIDOS"))
    if pedidos.empty:
        st.info("Nenhum pedido cadastrado.")
    else:
        temp = pedidos.copy()

        if "SALDO A RECEBER" not in temp.columns:
            temp["SALDO A RECEBER"] = temp.apply(lambda r: numero_para_float(r.get("TOTAL", 0)) if not status_pago(r.get("STATUS", "")) else 0, axis=1)
        if "VALOR RECEBIDO" not in temp.columns:
            temp["VALOR RECEBIDO"] = temp.apply(lambda r: numero_para_float(r.get("TOTAL", 0)) if status_pago(r.get("STATUS", "")) else 0, axis=1)
        if "VALOR PARCELA" not in temp.columns:
            temp["VALOR PARCELA"] = temp.apply(lambda r: calcular_valor_parcela(r.get("TOTAL", 0), r.get("PARCELAS", "À vista")), axis=1)

        temp["SALDO_NUM"] = temp["SALDO A RECEBER"].apply(numero_para_float)
        pendentes = temp[temp["SALDO_NUM"] > 0].drop(columns=["SALDO_NUM"])

        total_pendente = temp["SALDO A RECEBER"].apply(numero_para_float).sum()
        total_recebido = temp["VALOR RECEBIDO"].apply(numero_para_float).sum()

        c1, c2 = st.columns(2)
        c1.metric("Total recebido", formatar_moeda(total_recebido))
        c2.metric("Total a receber", formatar_moeda(total_pendente))

        st.markdown("### Pedidos pendentes / fiado")
        if pendentes.empty:
            st.success("Nenhum pedido pendente no momento.")
        else:
            st.dataframe(pendentes, use_container_width=True)

            pedido_receber = st.selectbox("Escolha um pedido para receber", pendentes["PEDIDO"].astype(str).tolist())
            linha = pendentes[pendentes["PEDIDO"].astype(str) == pedido_receber].iloc[0]
            saldo = numero_para_float(linha.get("SALDO A RECEBER", 0))
            valor = st.number_input("Valor recebido agora", min_value=0.0, value=float(saldo), format="%.2f")

            if st.button("✅ Registrar recebimento"):
                pedidos = preparar_pedidos_para_calculo(pedidos)
                idx = pedidos[pedidos["PEDIDO"].astype(str) == pedido_receber].index[0]
                recebido_atual = numero_para_float(pedidos.at[idx, "VALOR RECEBIDO"]) if "VALOR RECEBIDO" in pedidos.columns else 0.0
                total = numero_para_float(pedidos.at[idx, "TOTAL"])

                novo_recebido = recebido_atual + valor
                novo_saldo = max(0.0, total - novo_recebido)

                pedidos.loc[idx, "VALOR RECEBIDO"] = float(round(novo_recebido, 2))
                pedidos.loc[idx, "SALDO A RECEBER"] = float(round(novo_saldo, 2))

                if novo_saldo <= 0:
                    pedidos.loc[idx, "STATUS"] = "Pago"
                    pedidos.loc[idx, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")
                else:
                    pedidos.loc[idx, "STATUS"] = "Pendente"

                atualizar("PEDIDOS", pedidos)
                st.success("Recebimento registrado.")
                st.rerun()



# ==============================================================================
# PARCELAS / CREDIÁRIO
# ==============================================================================
elif escolha == "💳 Parcelas / Crediário":
    st.subheader("💳 Parcelas / Crediário LuhVee")

    parcelas_df = preparar_parcelas_para_calculo(dados("PARCELAS_RECEBER"))
    pedidos = preparar_pedidos_para_calculo(dados("PEDIDOS"))

    if parcelas_df.empty:
        st.info("Nenhuma parcela cadastrada ainda.")
    else:
        hoje = agora_brasil().date()

        temp = parcelas_df.copy()
        temp["VENC_DT"] = pd.to_datetime(temp["VENCIMENTO"], dayfirst=True, errors="coerce").dt.date
        temp["VALOR_NUM"] = temp["VALOR"].apply(numero_para_float)

        pendentes = temp[temp["STATUS"].astype(str).str.upper() != "PAGO"]
        vencidas = pendentes[pendentes["VENC_DT"].notna() & (pendentes["VENC_DT"] < hoje)]
        hoje_df = pendentes[pendentes["VENC_DT"].notna() & (pendentes["VENC_DT"] == hoje)]

        c1, c2, c3 = st.columns(3)
        c1.metric("A receber total", formatar_moeda(pendentes["VALOR_NUM"].sum()))
        c2.metric("Vencidas", formatar_moeda(vencidas["VALOR_NUM"].sum()))
        c3.metric("Vencem hoje", formatar_moeda(hoje_df["VALOR_NUM"].sum()))

        st.markdown("### Parcelas pendentes")
        mostrar = pendentes.drop(columns=["VENC_DT", "VALOR_NUM"], errors="ignore")
        st.dataframe(mostrar, use_container_width=True)

        if not pendentes.empty:
            lista_parcelas = [
                f"{row['PEDIDO']} | {row['CLIENTE']} | {row['PARCELA']} | {row['VENCIMENTO']} | {formatar_moeda(row['VALOR_NUM'])}"
                for _, row in pendentes.iterrows()
            ]

            escolha_parcela = st.selectbox("Escolha a parcela para marcar como paga", lista_parcelas)
            idx_sel = lista_parcelas.index(escolha_parcela)
            idx_real = pendentes.index[idx_sel]

            if st.button("✅ Marcar parcela como paga"):
                pedido_id = parcelas_df.loc[idx_real, "PEDIDO"]
                parcelas_df.loc[idx_real, "STATUS"] = "Pago"
                parcelas_df.loc[idx_real, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                # Atualiza pedido principal
                parcelas_pedido = parcelas_df[parcelas_df["PEDIDO"].astype(str) == str(pedido_id)]
                total_recebido = parcelas_pedido[
                    parcelas_pedido["STATUS"].astype(str).str.upper() == "PAGO"
                ]["VALOR"].apply(numero_para_float).sum()
                saldo = parcelas_pedido[
                    parcelas_pedido["STATUS"].astype(str).str.upper() != "PAGO"
                ]["VALOR"].apply(numero_para_float).sum()

                if not pedidos.empty and str(pedido_id) in pedidos["PEDIDO"].astype(str).tolist():
                    idx_pedido = pedidos[pedidos["PEDIDO"].astype(str) == str(pedido_id)].index[0]
                    pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = float(round(total_recebido, 2))
                    pedidos.loc[idx_pedido, "SALDO A RECEBER"] = float(round(saldo, 2))
                    pedidos.loc[idx_pedido, "STATUS"] = "Pago" if saldo <= 0 else "Pendente"
                    if saldo <= 0:
                        pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                atualizar("PARCELAS_RECEBER", parcelas_df)
                atualizar("PEDIDOS", pedidos)
                st.success("Parcela marcada como paga.")
                st.rerun()

        st.markdown("### Todas as parcelas")
        st.dataframe(parcelas_df, use_container_width=True)


# ==============================================================================
# CALCULADORA
# ==============================================================================
elif escolha == "🧮 Calculadora LuhVee":
    st.subheader("🧮 Calculadora LuhVee")

    c1, c2, c3 = st.columns(3)
    custo = c1.number_input("Custo do produto", min_value=0.0, value=10.0, format="%.2f")
    embalagem = c2.number_input("Embalagem", min_value=0.0, value=0.50, format="%.2f")
    frete_rateado = c3.number_input("Frete por item", min_value=0.0, value=0.0, format="%.2f")

    c4, c5, c6 = st.columns(3)
    taxa_percentual = c4.number_input("Taxa canal/cartão (%)", min_value=0.0, value=6.0, format="%.2f")
    lucro_percentual = c5.number_input("Lucro desejado (%)", min_value=0.0, value=100.0, format="%.2f")
    desconto = c6.number_input("Desconto previsto", min_value=0.0, value=0.0, format="%.2f")

    custo_total = custo + embalagem + frete_rateado
    preco_sem_taxa = custo_total * (1 + lucro_percentual / 100) + desconto
    preco_final = preco_sem_taxa / (1 - taxa_percentual / 100) if taxa_percentual < 100 else preco_sem_taxa
    taxa_valor = preco_final * taxa_percentual / 100
    lucro_liquido = preco_final - custo_total - taxa_valor - desconto

    r1, r2, r3 = st.columns(3)
    r1.metric("Preço sugerido", formatar_moeda(preco_final))
    r2.metric("Lucro líquido", formatar_moeda(lucro_liquido))
    r3.metric("Custo total", formatar_moeda(custo_total))


# ==============================================================================
# CALCULADORA DE PEDIDO DO CLIENTE
# ==============================================================================
elif escolha == "🛒 Calculadora de Pedido":
    st.subheader("🛒 Calculadora de Pedido do Cliente")
    st.info("Use para somar os produtos da cliente antes de fechar o pedido. Não baixa estoque e não salva venda.")

    produtos = dados("PRODUTOS")

    if produtos.empty:
        st.warning("Cadastre produtos no estoque antes de usar a calculadora.")
    else:
        produtos_lista = produtos["PRODUTO"].astype(str).tolist()
        itens_calc = []

        st.markdown("### Selecione os produtos")

        for i in range(1, 21):
            c1, c2, c3 = st.columns([4, 1, 2])

            prod = c1.selectbox(f"Produto {i}", [""] + produtos_lista, key=f"calc_prod_{i}")
            qtd = c2.number_input("Qtd", min_value=0, value=0, step=1, key=f"calc_qtd_{i}")

            preco_padrao = 0.0
            if prod:
                linha = produtos[produtos["PRODUTO"].astype(str) == prod]
                if not linha.empty:
                    preco_padrao = numero_para_float(linha.iloc[0].get("PREÇO VENDA", 0))

            preco = c3.number_input("Preço unitário", min_value=0.0, value=preco_padrao, format="%.2f", key=f"calc_preco_{i}")

            if prod and qtd > 0:
                total_item = qtd * preco
                itens_calc.append({
                    "Produto": prod,
                    "Quantidade": qtd,
                    "Preço Unitário": preco,
                    "Total": total_item
                })

        st.markdown("---")

        if itens_calc:
            df_calc = pd.DataFrame(itens_calc)
            total_geral = df_calc["Total"].sum()

            st.markdown("### Resumo da compra")
            st.dataframe(df_calc, use_container_width=True)

            st.metric("TOTAL DA CLIENTE", formatar_moeda(total_geral))

            mensagem = "Olá ❤️ Segue o resumo do seu pedido na LuhVee Stores:\n\n"
            for item in itens_calc:
                mensagem += f"• {item['Quantidade']}x {item['Produto']} — {formatar_moeda(item['Total'])}\n"
            mensagem += f"\nTotal: {formatar_moeda(total_geral)}\n\nLuhVee Stores ❤️"

            st.markdown("### Mensagem pronta para WhatsApp")
            st.text_area("Copie e envie para a cliente", mensagem, height=220)

            st.success("Depois de confirmar com a cliente, vá em 🧾 Criar Pedido para salvar oficialmente e baixar o estoque.")
        else:
            st.info("Escolha pelo menos um produto e quantidade para calcular.")

# ==============================================================================
# NOTA FISCAL
# ==============================================================================
elif escolha == "📑 Entrada por Nota Fiscal":
    st.subheader("📑 Entrada por Nota Fiscal PDF")
    st.info("Envia a DANFE em PDF. O sistema tenta ler produto, quantidade e custo, ignorando impostos.")

    fornecedor = st.text_input("Fornecedor padrão", "Atacadão dos Kits")
    margem_venda = st.number_input("Margem para sugerir preço de venda (%)", min_value=0.0, value=120.0, format="%.2f")
    arquivo = st.file_uploader("Envie o PDF da nota fiscal", type=["pdf"])

    if arquivo:
        df_nf = extrair_produtos_nfe_pdf(arquivo)

        if df_nf.empty:
            st.warning("Não consegui extrair produtos automaticamente desse PDF. Talvez seja imagem/escaneado ou layout diferente.")
        else:
            st.success(f"Encontrei {len(df_nf)} produto(s). Confira antes de adicionar ao estoque.")
            df_nf["FORNECEDOR"] = fornecedor
            df_nf["PREÇO VENDA"] = df_nf["CUSTO UNITÁRIO"].apply(lambda x: round(numero_para_float(x) * (1 + margem_venda / 100), 2))

            editado = st.data_editor(df_nf, use_container_width=True, num_rows="dynamic")

            if st.button("📦 Adicionar ao estoque"):
                produtos = preparar_produtos_para_calculo(dados("PRODUTOS"))
                compras = dados("COMPRAS")

                for _, row in editado.iterrows():
                    nome_prod = str(row["PRODUTO"]).strip().upper()
                    qtd = numero_para_int(row["QUANTIDADE"])
                    custo = numero_para_float(row["CUSTO UNITÁRIO"])
                    preco = numero_para_float(row["PREÇO VENDA"])
                    forn = str(row.get("FORNECEDOR", fornecedor)).strip()

                    if not produtos.empty:
                        match = produtos["PRODUTO"].astype(str).str.strip().str.upper() == nome_prod
                    else:
                        match = pd.Series(dtype=bool)

                    if not produtos.empty and match.any():
                        idx = produtos[match].index[0]
                        produtos.at[idx, "ESTOQUE"] = int(numero_para_int(produtos.at[idx, "ESTOQUE"]) + qtd)
                        produtos.at[idx, "CUSTO"] = float(custo)
                        produtos.at[idx, "PREÇO VENDA"] = float(preco)
                        produtos.at[idx, "FORNECEDOR"] = forn
                    else:
                        novo = {
                            "CÓDIGO": novo_id("PROD", produtos, "CÓDIGO"),
                            "PRODUTO": nome_prod,
                            "CATEGORIA": "Cosméticos",
                            "FORNECEDOR": forn,
                            "CUSTO": custo,
                            "PREÇO VENDA": preco,
                            "ESTOQUE": qtd
                        }
                        produtos = pd.concat([produtos, pd.DataFrame([novo])], ignore_index=True)

                valor_total = editado["TOTAL"].apply(numero_para_float).sum()
                compra = {
                    "NF": f"NF-{agora_brasil().strftime('%Y%m%d%H%M')}",
                    "DATA": agora_brasil().strftime("%d/%m/%Y %H:%M"),
                    "FORNECEDOR": fornecedor,
                    "VALOR TOTAL": round(valor_total, 2),
                    "ARQUIVO PDF": arquivo.name
                }
                compras = pd.concat([compras, pd.DataFrame([compra])], ignore_index=True)

                atualizar("PRODUTOS", produtos)
                atualizar("COMPRAS", compras)

                st.success("Nota lançada e estoque atualizado com sucesso.")
                st.rerun()

# ==============================================================================
# BACKUP
# ==============================================================================
elif escolha == "💾 Backup ERP":
    st.subheader("💾 Backup ERP")

    arquivos = []
    for nome, df in st.session_state.dados.items():
        csv_file = CSV_MAP[nome]
        df.to_csv(csv_file, index=False)
        arquivos.append(csv_file)

    st.markdown("### Baixar arquivos separados")
    for arquivo_csv in arquivos:
        if os.path.exists(arquivo_csv):
            with open(arquivo_csv, "rb") as f:
                st.download_button(
                    f"⬇️ Baixar {arquivo_csv}",
                    data=f.read(),
                    file_name=arquivo_csv,
                    mime="text/csv",
                    key=f"baixar_{arquivo_csv}"
                )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for arquivo_csv in arquivos:
            if os.path.exists(arquivo_csv):
                zip_file.write(arquivo_csv)

    zip_buffer.seek(0)
    st.download_button(
        "💾 Baixar Backup Completo ZIP",
        data=zip_buffer.getvalue(),
        file_name=f"BACKUP_LUHVEE_ERP_{agora_brasil().strftime('%d-%m-%Y_%H-%M')}.zip",
        mime="application/zip"
    )

    st.success("Salve esse ZIP no computador ou Google Drive.")
