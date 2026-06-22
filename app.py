import streamlit as st
import pandas as pd
import os
import re
import json
import zipfile
from io import BytesIO
from datetime import datetime

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
COL_PEDIDOS = ["PEDIDO", "DATA", "CLIENTE", "WHATSAPP", "PAGAMENTO", "PARCELAS", "PLATAFORMA", "TOTAL", "STATUS"]
COL_ITENS = ["PEDIDO", "PRODUTO", "QUANTIDADE", "PREÇO", "TOTAL", "LUCRO"]
COL_COMPRAS = ["NF", "DATA", "FORNECEDOR", "VALOR TOTAL", "ARQUIVO PDF"]

ABAS = {
    "CLIENTES": COL_CLIENTES,
    "PRODUTOS": COL_PRODUTOS,
    "PEDIDOS": COL_PEDIDOS,
    "ITENS_PEDIDO": COL_ITENS,
    "COMPRAS": COL_COMPRAS,
}

CSV_MAP = {
    "CLIENTES": "clientes_base.csv",
    "PRODUTOS": "estoque_base.csv",
    "PEDIDOS": "pedidos_base.csv",
    "ITENS_PEDIDO": "itens_pedido_base.csv",
    "COMPRAS": "compras_base.csv",
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

def dados(nome):
    return st.session_state.dados[nome]

def atualizar(nome, df):
    st.session_state.dados[nome] = padronizar_df(nome, df)
    salvar_aba(nome, st.session_state.dados[nome])

# ==============================================================================
# PDF RECIBO A6
# ==============================================================================
def gerar_pdf_recibo(pedido_info, itens):
    if canvas is None:
        return None

    buffer = BytesIO()
    largura = 105 * mm
    altura = 148 * mm
    pdf = canvas.Canvas(buffer, pagesize=(largura, altura))

    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#444444")
    margem = 7 * mm
    y = altura - 9 * mm

    def linha():
        nonlocal y
        pdf.setStrokeColor(rosa)
        pdf.setLineWidth(0.6)
        pdf.line(margem, y, largura - margem, y)
        y -= 5 * mm

    def central(txt, fonte="Helvetica-Bold", tamanho=10, cor=preto):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawCentredString(largura / 2, y, str(txt))
        y -= (tamanho * 0.45) * mm

    def esquerda(txt, fonte="Helvetica", tamanho=7.5, cor=preto):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawString(margem, y, str(txt)[:62])
        y -= 4 * mm

    central("LUHVEE STORES", "Helvetica-Bold", 13, rosa)
    central("Curadoria Inteligente & Achadinhos Exclusivos", "Helvetica", 6.5, cinza)
    y -= 2 * mm
    linha()

    central("RECIBO DE VENDA", "Helvetica-Bold", 10, preto)
    esquerda(f"Pedido: {pedido_info.get('PEDIDO','')}", "Helvetica-Bold", 8)
    esquerda(f"Data: {pedido_info.get('DATA','')}", "Helvetica", 7)
    linha()

    esquerda("CLIENTE", "Helvetica-Bold", 8, rosa)
    esquerda(f"Nome: {pedido_info.get('CLIENTE','')}", "Helvetica", 7.5)
    esquerda(f"WhatsApp: {pedido_info.get('WHATSAPP','')}", "Helvetica", 7.5)
    linha()

    esquerda("DETALHES", "Helvetica-Bold", 8, rosa)
    esquerda(f"Plataforma: {pedido_info.get('PLATAFORMA','')}", "Helvetica", 7.5)
    esquerda(f"Pagamento: {pedido_info.get('PAGAMENTO','')} - {pedido_info.get('PARCELAS','')}", "Helvetica", 7.5)
    esquerda(f"Status: {pedido_info.get('STATUS','')}", "Helvetica", 7.5)
    linha()

    esquerda("PRODUTOS", "Helvetica-Bold", 8, rosa)

    for _, item in itens.iterrows():
        qtd = numero_para_int(item.get("QUANTIDADE", 1), 1)
        produto = str(item.get("PRODUTO", ""))[:34]
        valor = formatar_moeda(numero_para_float(item.get("TOTAL", 0)))
        pdf.setFont("Helvetica", 7)
        pdf.setFillColor(preto)
        pdf.drawString(margem, y, f"{qtd}x {produto}")
        pdf.drawRightString(largura - margem, y, valor)
        y -= 4 * mm
        if y < 28 * mm:
            pdf.showPage()
            y = altura - 10 * mm

    y -= 1 * mm
    linha()
    central("TOTAL DO PEDIDO", "Helvetica-Bold", 8, preto)
    central(formatar_moeda(numero_para_float(pedido_info.get("TOTAL", 0))), "Helvetica-Bold", 16, rosa)
    y -= 2 * mm
    linha()
    central("Obrigada pela preferência ❤️", "Helvetica-Oblique", 7, preto)
    central("LuhVee Stores", "Helvetica-Bold", 8, rosa)

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()

# ==============================================================================
# NOTA FISCAL PDF
# ==============================================================================
def extrair_produtos_nfe_pdf(arquivo_pdf):
    if pdfplumber is None:
        return pd.DataFrame(columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])

    texto = ""
    with pdfplumber.open(arquivo_pdf) as pdf:
        for pagina in pdf.pages:
            texto += "\n" + (pagina.extract_text() or "")

    produtos = []
    linhas = texto.splitlines()

    # Padrão para DANFE parecida com a nota enviada
    padrao = re.compile(r"^(.*?)\s+0\s+60\s+5405\s+UN\s+([\d\.,]+)\s+([\d\.,]+)\s+([\d\.,]+)")

    for linha in linhas:
        linha = " ".join(linha.split())
        m = padrao.search(linha)
        if m:
            produto = m.group(1).strip()
            qtd = numero_para_float(m.group(2))
            custo = numero_para_float(m.group(3))
            total = numero_para_float(m.group(4))
            if produto and qtd > 0 and custo > 0:
                produtos.append({
                    "PRODUTO": produto.upper(),
                    "QUANTIDADE": int(round(qtd)),
                    "CUSTO UNITÁRIO": round(custo, 2),
                    "TOTAL": round(total, 2)
                })

    return pd.DataFrame(produtos, columns=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])

# ==============================================================================
# MENU
# ==============================================================================
menu = [
    "Dashboard",
    "👥 Clientes",
    "📦 Produtos / Estoque",
    "🧾 Criar Pedido",
    "📋 Histórico de Pedidos",
    "🧮 Calculadora LuhVee",
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

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Produtos", len(produtos))
    col2.metric("Clientes", len(clientes))
    col3.metric("Pedidos", len(pedidos))
    col4.metric("Faturamento", formatar_moeda(total_vendido))

    st.metric("Investimento em Estoque", formatar_moeda(total_estoque))

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
                        "DATA CADASTRO": datetime.now().strftime("%d/%m/%Y %H:%M")
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
    produtos = dados("PRODUTOS")
    pedidos = dados("PEDIDOS")
    itens_pedido = dados("ITENS_PEDIDO")

    if clientes.empty or produtos.empty:
        st.warning("Cadastre pelo menos 1 cliente e 1 produto antes de criar pedido.")
    else:
        pedido_id = novo_id("PED", pedidos, "PEDIDO")
        st.markdown(f"### Pedido: **{pedido_id}**")

        with st.form("form_pedido"):
            c1, c2, c3 = st.columns(3)
            cliente_nome = c1.selectbox("Cliente", clientes["NOME"].astype(str).tolist())
            pagamento = c2.selectbox("Pagamento", ["PIX", "Dinheiro", "Débito", "Crédito", "Mercado Pago", "PagBank", "PicPay"])
            parcelas = c3.selectbox("Parcelas", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "10x", "12x"])

            c4, c5 = st.columns(2)
            plataforma = c4.selectbox("Plataforma", ["WhatsApp", "Instagram", "Loja Física", "Yampi", "Shopee", "Mercado Livre", "iFood"])
            status = c5.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"])

            st.markdown("### Produtos")
            produtos_lista = produtos["PRODUTO"].astype(str).tolist()
            itens_temp = []

            for i in range(1, 11):
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

                        produtos.loc[idx, "ESTOQUE"] = numero_para_int(produtos.loc[idx, "ESTOQUE"]) - qtd

                        novos_itens.append({
                            "PEDIDO": pedido_id,
                            "PRODUTO": prod,
                            "QUANTIDADE": qtd,
                            "PREÇO": round(preco, 2),
                            "TOTAL": round(total_item, 2),
                            "LUCRO": round(lucro, 2)
                        })
                        total_pedido += total_item

                    novo_pedido = {
                        "PEDIDO": pedido_id,
                        "DATA": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "CLIENTE": cliente_nome,
                        "WHATSAPP": whatsapp,
                        "PAGAMENTO": pagamento,
                        "PARCELAS": parcelas,
                        "PLATAFORMA": plataforma,
                        "TOTAL": round(total_pedido, 2),
                        "STATUS": status
                    }

                    pedidos = pd.concat([pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
                    itens_pedido = pd.concat([itens_pedido, pd.DataFrame(novos_itens)], ignore_index=True)

                    atualizar("PRODUTOS", produtos)
                    atualizar("PEDIDOS", pedidos)
                    atualizar("ITENS_PEDIDO", itens_pedido)

                    st.success(f"Pedido {pedido_id} salvo. Total: {formatar_moeda(total_pedido)}")
                    st.rerun()

# ==============================================================================
# HISTÓRICO
# ==============================================================================
elif escolha == "📋 Histórico de Pedidos":
    st.subheader("📋 Histórico de Pedidos")
    pedidos = dados("PEDIDOS")
    itens_pedido = dados("ITENS_PEDIDO")

    if pedidos.empty:
        st.info("Nenhum pedido cadastrado.")
    else:
        st.dataframe(pedidos, use_container_width=True)

        pedido_sel = st.selectbox("Abrir pedido", pedidos["PEDIDO"].astype(str).tolist())
        pedido_info = pedidos[pedidos["PEDIDO"].astype(str) == pedido_sel].iloc[0].to_dict()
        itens = itens_pedido[itens_pedido["PEDIDO"].astype(str) == pedido_sel]

        st.markdown("### Itens do pedido")
        st.dataframe(itens, use_container_width=True)

        pdf_bytes = gerar_pdf_recibo(pedido_info, itens)
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
                produtos = dados("PRODUTOS")
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
                        produtos.loc[idx, "ESTOQUE"] = numero_para_int(produtos.loc[idx, "ESTOQUE"]) + qtd
                        produtos.loc[idx, "CUSTO"] = custo
                        produtos.loc[idx, "PREÇO VENDA"] = preco
                        produtos.loc[idx, "FORNECEDOR"] = forn
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
                    "NF": f"NF-{datetime.now().strftime('%Y%m%d%H%M')}",
                    "DATA": datetime.now().strftime("%d/%m/%Y %H:%M"),
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
        file_name=f"BACKUP_LUHVEE_ERP_{datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip",
        mime="application/zip"
    )

    st.success("Salve esse ZIP no computador ou Google Drive.")
