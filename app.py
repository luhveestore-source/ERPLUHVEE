import streamlit as st
import pandas as pd
import os
import re
import json
import zipfile
import hashlib
import urllib.parse
from io import BytesIO
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ==============================================================================
# BIBLIOTECAS OPCIONAIS
# ==============================================================================
GSPREAD_IMPORT_ERROR = ""
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception as e:
    gspread = None
    Credentials = None
    GSPREAD_IMPORT_ERROR = str(e)

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
COL_PRODUTOS = ["CÓDIGO", "CÓDIGO BARRAS", "PRODUTO", "CATEGORIA", "FORNECEDOR", "CUSTO", "PREÇO VENDA", "ESTOQUE"]
COL_PEDIDOS = [
    "PEDIDO", "DATA", "CLIENTE", "WHATSAPP", "PAGAMENTO", "PARCELAS", "VALOR PARCELA",
    "PLATAFORMA", "TOTAL BRUTO", "DESCONTO", "TOTAL", "STATUS", "DATA PAGAMENTO",
    "VALOR RECEBIDO", "SALDO A RECEBER"
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
    for c in ["TOTAL BRUTO", "DESCONTO", "TOTAL", "VALOR PARCELA", "VALOR RECEBIDO", "SALDO A RECEBER"]:
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
# GOOGLE SHEETS - CONEXÃO SEGURA
# ==============================================================================
def tem_secrets_google():
    try:
        return "SPREADSHEET_ID" in st.secrets and (
            "GCP_SERVICE_ACCOUNT_JSON" in st.secrets or "gcp_service_account" in st.secrets
        )
    except Exception as e:
        st.session_state["google_sheets_erro"] = f"Não foi possível ler os Secrets do Streamlit: {e}"
        return False

def diagnostico_google():
    diagnostico = {
        "secrets_ok": False,
        "spreadsheet_id_ok": False,
        "credencial_ok": False,
        "gspread_ok": gspread is not None,
        "credentials_ok": Credentials is not None,
        "erro_importacao": GSPREAD_IMPORT_ERROR,
    }
    try:
        diagnostico["spreadsheet_id_ok"] = bool(str(st.secrets.get("SPREADSHEET_ID", "")).strip())
        diagnostico["credencial_ok"] = (
            "GCP_SERVICE_ACCOUNT_JSON" in st.secrets or "gcp_service_account" in st.secrets
        )
        diagnostico["secrets_ok"] = diagnostico["spreadsheet_id_ok"] and diagnostico["credencial_ok"]
    except Exception as e:
        diagnostico["erro_secrets"] = str(e)
    return diagnostico

def conectar_google_sheets():
    # Não usa cache: se a conexão falhar uma vez, o ERP pode tentar novamente no próximo rerun.
    st.session_state.pop("google_sheets_erro", None)

    if gspread is None or Credentials is None:
        detalhe = GSPREAD_IMPORT_ERROR or "gspread/google-auth não foram carregados."
        st.session_state["google_sheets_erro"] = f"Bibliotecas do Google indisponíveis: {detalhe}"
        return None

    if not tem_secrets_google():
        st.session_state["google_sheets_erro"] = (
            "Secrets do Google não encontrados. Verifique SPREADSHEET_ID e "
            "GCP_SERVICE_ACCOUNT_JSON (ou gcp_service_account) nas configurações do app."
        )
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    try:
        if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
            raw = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
            if isinstance(raw, str):
                info = json.loads(raw)
            else:
                info = dict(raw)
        else:
            info = dict(st.secrets["gcp_service_account"])

        if "private_key" in info and isinstance(info["private_key"], str):
            info["private_key"] = info["private_key"].replace("\\n", "\n")

        obrigatorios = ["client_email", "private_key", "token_uri"]
        faltando = [campo for campo in obrigatorios if not info.get(campo)]
        if faltando:
            raise ValueError("Credencial incompleta. Campos ausentes: " + ", ".join(faltando))

        spreadsheet_id = str(st.secrets["SPREADSHEET_ID"]).strip()
        if not spreadsheet_id:
            raise ValueError("SPREADSHEET_ID está vazio.")

        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        ss = client.open_by_key(spreadsheet_id)

        # Força uma leitura simples para confirmar que a conta realmente tem acesso.
        _ = ss.title
        st.session_state["google_sheets_conectado"] = True
        return ss

    except Exception as e:
        st.session_state["google_sheets_conectado"] = False
        st.session_state["google_sheets_erro"] = f"{type(e).__name__}: {e}"
        return None

def obter_worksheet(nome_aba, criar_se_nao_existir=False):
    ss = conectar_google_sheets()
    if ss is None:
        return None

    try:
        return ss.worksheet(nome_aba)
    except Exception as e:
        # Só cria uma aba quando isso for explicitamente solicitado.
        # Assim um erro de permissão/conexão nunca cria ou substitui dados por engano.
        worksheet_not_found = getattr(gspread, "WorksheetNotFound", None) if gspread is not None else None
        if criar_se_nao_existir and worksheet_not_found and isinstance(e, worksheet_not_found):
            ws = ss.add_worksheet(title=nome_aba, rows=2000, cols=40)
            ws.append_row(ABAS[nome_aba])
            return ws

        st.session_state["google_sheets_erro"] = f"Erro ao abrir a aba {nome_aba}: {type(e).__name__}: {e}"
        return None

def padronizar_df(nome_aba, df):
    colunas = ABAS[nome_aba]
    df = df.copy() if df is not None else pd.DataFrame()

    # compatibilidade com CSV antigo
    mapas = {
        "PRODUTOS": {
            "Código": "CÓDIGO", "Código de Barras": "CÓDIGO BARRAS", "Codigo de Barras": "CÓDIGO BARRAS", "EAN": "CÓDIGO BARRAS", "Produto": "PRODUTO", "Categoria": "CATEGORIA", "Fornecedor": "FORNECEDOR",
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
    ws = obter_worksheet(nome_aba, criar_se_nao_existir=False)

    if ws is not None:
        try:
            valores = ws.get_all_values()
            if len(valores) > 1:
                df = pd.DataFrame(valores[1:], columns=valores[0])
                df_ok = padronizar_df(nome_aba, df)
                st.session_state.setdefault("fonte_dados", {})[nome_aba] = "Google Sheets"
                st.session_state.setdefault("hash_google_carregado", {})[nome_aba] = _hash_df(nome_aba, df_ok)
                return df_ok

            # Uma aba vazia do Google NUNCA é preenchida automaticamente com CSV local.
            vazio = pd.DataFrame(columns=colunas)
            st.session_state.setdefault("fonte_dados", {})[nome_aba] = "Google Sheets (aba vazia)"
            st.session_state.setdefault("hash_google_carregado", {})[nome_aba] = _hash_df(nome_aba, vazio)
            return vazio
        except Exception as e:
            st.session_state["google_sheets_erro"] = f"Erro ao ler {nome_aba}: {type(e).__name__}: {e}"

    # Fallback local apenas para visualização/continuidade quando o Google estiver indisponível.
    if os.path.exists(csv_file):
        try:
            df_local = padronizar_df(nome_aba, pd.read_csv(csv_file))
            st.session_state.setdefault("fonte_dados", {})[nome_aba] = "CSV local (fallback)"
            return df_local
        except Exception as e:
            st.session_state["erro_csv_local"] = f"Erro ao ler {csv_file}: {e}"

    st.session_state.setdefault("fonte_dados", {})[nome_aba] = "Sem dados"
    return pd.DataFrame(columns=colunas)

def _hash_df(nome_aba, df):
    """Hash estável para detectar sessão antiga antes de sobrescrever o Google Sheets."""
    temp = padronizar_df(nome_aba, df).fillna("").astype(str)
    payload = temp.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _df_do_google(nome_aba, ws):
    valores = ws.get_all_values()
    if len(valores) <= 1:
        return pd.DataFrame(columns=ABAS[nome_aba]), valores
    bruto = pd.DataFrame(valores[1:], columns=valores[0])
    return padronizar_df(nome_aba, bruto), valores


def _chaves_registro(nome_aba, df):
    """Chaves usadas para impedir desaparecimento silencioso de registros."""
    df = padronizar_df(nome_aba, df)
    if df.empty:
        return set()

    if nome_aba == "PEDIDOS":
        return {x.strip() for x in df["PEDIDO"].astype(str) if x.strip()}
    if nome_aba == "PRODUTOS":
        chaves = set()
        for _, r in df.iterrows():
            cod = str(r.get("CÓDIGO", "")).strip()
            prod = str(r.get("PRODUTO", "")).strip()
            if cod or prod:
                chaves.add(cod or f"PRODUTO::{prod}")
        return chaves
    if nome_aba == "CLIENTES":
        chaves = set()
        for _, r in df.iterrows():
            rid = str(r.get("ID", "")).strip()
            nome = str(r.get("NOME", "")).strip()
            whats = str(r.get("WHATSAPP", "")).strip()
            if rid or nome or whats:
                chaves.add(rid or f"CLIENTE::{nome}|{whats}")
        return chaves
    if nome_aba == "PARCELAS_RECEBER":
        return {
            f"{str(r.get('PEDIDO','')).strip()}|{str(r.get('PARCELA','')).strip()}"
            for _, r in df.iterrows()
            if str(r.get("PEDIDO", "")).strip()
        }
    if nome_aba == "COMPRAS":
        return {
            str(r.get("NF", "")).strip()
            for _, r in df.iterrows()
            if str(r.get("NF", "")).strip()
        }
    return set()


def _validar_gravacao(nome_aba, df_novo, df_remoto, permitir_reducao=False):
    """Bloqueia sessão velha, perda maciça e remoções não autorizadas."""
    df_novo = padronizar_df(nome_aba, df_novo)
    df_remoto = padronizar_df(nome_aba, df_remoto)

    if not df_remoto.empty and df_novo.empty:
        raise RuntimeError(
            f"PROTEÇÃO DE DADOS: {nome_aba} tem {len(df_remoto)} registros no Google e o ERP tentou gravar zero. Operação bloqueada."
        )

    # Se os dados da sessão não vieram do Google, nunca deixe essa cópia virar a base principal.
    fonte = st.session_state.get("fonte_dados", {}).get(nome_aba, "")
    if not str(fonte).startswith("Google Sheets"):
        raise RuntimeError(
            f"PROTEÇÃO DE DADOS: {nome_aba} foi carregada de '{fonte or 'fonte desconhecida'}'. "
            "Recarregue os dados do Google Sheets antes de salvar qualquer alteração."
        )

    # Controle de concorrência: se a planilha mudou desde que esta sessão carregou, bloqueia a escrita.
    hash_esperado = st.session_state.get("hash_google_carregado", {}).get(nome_aba)
    hash_atual = _hash_df(nome_aba, df_remoto)
    if hash_esperado and hash_esperado != hash_atual:
        raise RuntimeError(
            f"PROTEÇÃO DE DADOS: a aba {nome_aba} mudou no Google Sheets depois que esta tela foi carregada. "
            "Nada foi sobrescrito. Use 'Recarregar todos os dados do Google Sheets' e tente novamente."
        )

    if permitir_reducao:
        return

    # PRODUTOS: código, nome, custo, preço etc. são campos editáveis.
    # Portanto, NÃO usamos o CÓDIGO como identidade imutável do registro.
    # Em vez disso, bloqueamos exclusão de linhas e códigos duplicados,
    # permitindo editar o código de um produto existente com segurança.
    if nome_aba == "PRODUTOS":
        if len(df_novo) < len(df_remoto):
            raise RuntimeError(
                f"PROTEÇÃO DE DADOS: PRODUTOS passaria de {len(df_remoto)} para {len(df_novo)} registros. "
                "A exclusão de produtos pela grade foi bloqueada. Edite código, custo, preço ou estoque sem remover linhas."
            )

        # Códigos duplicados antigos não podem impedir uma venda.
        # Bloqueamos apenas duplicidades NOVAS introduzidas nesta edição.
        def _duplicados_codigos(df_cod):
            cods = [
                str(x).strip().upper()
                for x in df_cod["CÓDIGO"].astype(str)
                if str(x).strip() and str(x).strip().lower() not in {"nan", "none"}
            ]
            contagem = {}
            for c in cods:
                contagem[c] = contagem.get(c, 0) + 1
            return {c for c, qtd in contagem.items() if qtd > 1}

        duplicados_antes = _duplicados_codigos(df_remoto)
        duplicados_depois = _duplicados_codigos(df_novo)
        novos_duplicados = sorted(duplicados_depois - duplicados_antes)

        if novos_duplicados:
            amostra = ", ".join(novos_duplicados[:5])
            raise RuntimeError(
                f"PROTEÇÃO DE DADOS: esta alteração criaria código(s) duplicado(s) novo(s) ({amostra}). "
                "Os códigos duplicados que já existiam na base não bloqueiam pedidos, mas não crie novas duplicidades."
            )

        # Código de barras deve ser único quando preenchido.
        def _duplicados_barras(df_barras):
            barras = [
                re.sub(r"\s+", "", str(x).strip()).upper()
                for x in df_barras["CÓDIGO BARRAS"].astype(str)
                if str(x).strip() and str(x).strip().lower() not in {"nan", "none"}
            ]
            contagem = {}
            for b in barras:
                contagem[b] = contagem.get(b, 0) + 1
            return {b for b, qtd in contagem.items() if qtd > 1}

        duplicados_barras_antes = _duplicados_barras(df_remoto)
        duplicados_barras_depois = _duplicados_barras(df_novo)
        novos_barras_duplicados = sorted(duplicados_barras_depois - duplicados_barras_antes)
        if novos_barras_duplicados:
            amostra = ", ".join(novos_barras_duplicados[:5])
            raise RuntimeError(
                f"PROTEÇÃO DE DADOS: este código de barras já está vinculado a outro produto ({amostra}). "
                "Cada código de barras deve pertencer a apenas um produto."
            )
    else:
        # Regra estrutural para tabelas com identificadores realmente estáveis:
        # registros já existentes não podem desaparecer silenciosamente.
        chaves_antigas = _chaves_registro(nome_aba, df_remoto)
        chaves_novas = _chaves_registro(nome_aba, df_novo)
        faltantes = chaves_antigas - chaves_novas
        if faltantes:
            amostra = ", ".join(sorted(list(faltantes))[:5])
            raise RuntimeError(
                f"PROTEÇÃO DE DADOS: a gravação em {nome_aba} removeria {len(faltantes)} registro(s) existente(s) "
                f"({amostra}). Operação bloqueada."
            )

    # ITENS_PEDIDO não possui ID único. Por padrão, não pode encolher.
    if nome_aba == "ITENS_PEDIDO" and len(df_novo) < len(df_remoto):
        raise RuntimeError(
            f"PROTEÇÃO DE DADOS: ITENS_PEDIDO passaria de {len(df_remoto)} para {len(df_novo)} linhas. Operação bloqueada."
        )

    # Rede extra contra perdas grandes em qualquer aba.
    if len(df_remoto) >= 10 and len(df_novo) < int(len(df_remoto) * 0.80):
        raise RuntimeError(
            f"PROTEÇÃO DE DADOS: {nome_aba} passaria de {len(df_remoto)} para {len(df_novo)} registros. "
            "Uma redução superior a 20% exige uma operação explicitamente autorizada."
        )


def _gravar_ws(nome_aba, ws, df_novo, valores_atuais):
    valores_novos = [ABAS[nome_aba]] + padronizar_df(nome_aba, df_novo).astype(str).values.tolist()
    ws.update(values=valores_novos, range_name="A1")
    linhas_antigas = len(valores_atuais)
    linhas_novas = len(valores_novos)
    if linhas_antigas > linhas_novas:
        ws.batch_clear([f"A{linhas_novas + 1}:AZ{linhas_antigas}"])


def salvar_aba(nome_aba, df, salvar_csv=True, salvar_google=True, permitir_reducao=False):
    df = padronizar_df(nome_aba, df)

    if not salvar_google:
        if salvar_csv:
            df.to_csv(CSV_MAP[nome_aba], index=False)
        return

    ss = conectar_google_sheets()
    if ss is None:
        raise RuntimeError("Google Sheets desconectado. A alteração foi BLOQUEADA; nenhum CSV principal foi atualizado.")

    ws = obter_worksheet(nome_aba, criar_se_nao_existir=False)
    if ws is None:
        raise RuntimeError(f"Não foi possível abrir a aba {nome_aba} no Google Sheets.")

    try:
        df_remoto, valores_atuais = _df_do_google(nome_aba, ws)
        _validar_gravacao(nome_aba, df, df_remoto, permitir_reducao=permitir_reducao)
        _gravar_ws(nome_aba, ws, df, valores_atuais)
    except Exception as e:
        st.session_state["google_sheets_erro"] = f"Erro ao salvar {nome_aba}: {type(e).__name__}: {e}"
        raise

    # Só atualiza o fallback local DEPOIS que o Google confirmou a gravação.
    if salvar_csv:
        df.to_csv(CSV_MAP[nome_aba], index=False)

    st.session_state.setdefault("hash_google_carregado", {})[nome_aba] = _hash_df(nome_aba, df)
    st.session_state.setdefault("fonte_dados", {})[nome_aba] = "Google Sheets"


def carregar_tudo():
    st.session_state["fonte_dados"] = {}
    st.session_state["hash_google_carregado"] = {}
    return {nome: carregar_aba(nome) for nome in ABAS}


if "dados" not in st.session_state:
    st.session_state.dados = carregar_tudo()
else:
    st.session_state.setdefault("hash_google_carregado", {})
    for nome in ABAS:
        if nome not in st.session_state.dados:
            st.session_state.dados[nome] = carregar_aba(nome)


def dados(nome):
    if nome not in st.session_state.dados:
        st.session_state.dados[nome] = carregar_aba(nome)
    return st.session_state.dados[nome]


def atualizar(nome, df, permitir_reducao=False):
    df_padrao = padronizar_df(nome, df)
    if conectar_google_sheets() is None:
        raise RuntimeError("Google Sheets está desconectado. Por segurança, a alteração foi bloqueada.")

    salvar_aba(nome, df_padrao, salvar_csv=True, salvar_google=True, permitir_reducao=permitir_reducao)
    st.session_state.dados[nome] = df_padrao


def atualizar_multiplas(alteracoes, permitir_reducao=None):
    """
    Grava várias abas como uma transação protegida.
    Se alguma gravação falhar, tenta restaurar no Google as abas já alteradas.
    """
    permitir_reducao = set(permitir_reducao or [])
    ss = conectar_google_sheets()
    if ss is None:
        raise RuntimeError("Google Sheets desconectado. A operação inteira foi bloqueada.")

    preparados = {nome: padronizar_df(nome, df) for nome, df in alteracoes.items()}
    contexto = {}

    # Fase 1: lê e valida TUDO antes de alterar qualquer aba.
    for nome, df_novo in preparados.items():
        ws = obter_worksheet(nome, criar_se_nao_existir=False)
        if ws is None:
            raise RuntimeError(f"Não foi possível abrir a aba {nome} no Google Sheets.")
        df_remoto, valores_atuais = _df_do_google(nome, ws)
        _validar_gravacao(nome, df_novo, df_remoto, permitir_reducao=(nome in permitir_reducao))
        contexto[nome] = (ws, df_remoto, valores_atuais)

    gravadas = []
    try:
        for nome, df_novo in preparados.items():
            ws, _, valores_atuais = contexto[nome]
            _gravar_ws(nome, ws, df_novo, valores_atuais)
            gravadas.append(nome)
    except Exception as erro:
        # Rollback de melhor esforço nas abas que já tinham sido gravadas.
        erros_rollback = []
        for nome in reversed(gravadas):
            try:
                ws, df_antigo, _ = contexto[nome]
                valores_agora = ws.get_all_values()
                _gravar_ws(nome, ws, df_antigo, valores_agora)
            except Exception as er:
                erros_rollback.append(f"{nome}: {er}")
        detalhe = f" Falha no rollback: {'; '.join(erros_rollback)}" if erros_rollback else " Rollback executado."
        raise RuntimeError(f"A operação falhou e foi interrompida.{detalhe} Erro original: {erro}")

    # Fase 3: só depois do Google concluído atualiza sessão e CSVs.
    for nome, df_novo in preparados.items():
        df_novo.to_csv(CSV_MAP[nome], index=False)
        st.session_state.dados[nome] = df_novo
        st.session_state.setdefault("hash_google_carregado", {})[nome] = _hash_df(nome, df_novo)
        st.session_state.setdefault("fonte_dados", {})[nome] = "Google Sheets"

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
    total_bruto_pdf = numero_para_float(pedido_info.get("TOTAL BRUTO", total))
    desconto_pdf = numero_para_float(pedido_info.get("DESCONTO", 0))
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
    if total_bruto_pdf > total and desconto_pdf > 0:
        texto(f"Total dos produtos: {formatar_moeda(total_bruto_pdf)}", tam=9)
        texto(f"Desconto: - {formatar_moeda(desconto_pdf)}", tam=9)
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
    Leitor mais flexível de DANFE/NF-e PDF.
    Tenta ler texto corrido e tabelas do PDF.
    """
    colunas = ["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"]

    if pdfplumber is None:
        return pd.DataFrame(columns=colunas)

    produtos = []

    def limpar_nome(nome):
        nome = str(nome).replace("\n", " ")
        nome = " ".join(nome.split()).strip()
        nome = re.sub(r"^CFOP\s*5102\s*", "", nome, flags=re.IGNORECASE)
        nome = re.sub(r"^CFOP5102\s*", "", nome, flags=re.IGNORECASE)
        nome = re.sub(r"^\d{1,8}\s+", "", nome).strip()
        nome = re.sub(r"\s+\d{1,8}$", "", nome).strip()
        nome = re.sub(r"^C[ÓO]DIGO\s*", "", nome, flags=re.IGNORECASE).strip()
        return nome.upper()

    def add_produto(nome, qtd, custo, total):
        nome = limpar_nome(nome)
        qtd = numero_para_float(qtd)
        custo = numero_para_float(custo)
        total = numero_para_float(total)

        if not nome or qtd <= 0:
            return

        if custo <= 0 and total > 0 and qtd > 0:
            custo = total / qtd

        if custo <= 0 or total <= 0:
            return

        ignorar = [
            "DADOS DO PRODUTO", "DESCRIÇÃO DO PRODUTO", "VALOR TOTAL",
            "CÁLCULO DO IMPOSTO", "TRANSPORTADOR", "DADOS ADICIONAIS",
            "RESERVADO AO FISCO", "CÓDIGO DESCRIÇÃO", "FATURAS",
            "DESTINATÁRIO", "REMETENTE", "DANFE", "NOTA FISCAL"
        ]
        if any(x in nome for x in ignorar):
            return

        if len(nome) < 4:
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
                texto_total += "\n" + (pagina.extract_text() or "")

                try:
                    tabelas = pagina.extract_tables() or []
                    for tabela in tabelas:
                        for row in tabela:
                            if not row:
                                continue
                            linha = " ".join([str(x) for x in row if x not in [None, ""]])
                            texto_total += "\n" + linha
                except Exception:
                    pass
    except Exception:
        return pd.DataFrame(columns=colunas)

    linhas = [" ".join(l.split()) for l in texto_total.splitlines() if l and l.strip()]

    padroes = [
        re.compile(
            r"^(?P<desc>.*?)\s+"
            r"(?P<ncm>\d{8})\s+"
            r"(?P<cst>\d{2,4})\s+"
            r"(?P<cfop>5[\.,]102|5102|5405|6102|6[\.,]102)\s*"
            r"(?P<un>UN|UND|UNID|PC|PÇ|CX|KIT)?\s+"
            r"(?P<qtd>\d+[\.,]\d+|\d+)\s+"
            r"(?P<custo>\d+[\.,]\d+)\s+"
            r"(?P<total>\d+[\.,]\d+)"
        ),
        re.compile(
            r"^(?P<desc>.*?)\s+"
            r"(?P<cfop>5[\.,]102|5102|5405|6102|6[\.,]102)\s*"
            r"(?P<un>UN|UND|UNID|PC|PÇ|CX|KIT)?\s+"
            r"(?P<qtd>\d+[\.,]\d+|\d+)\s+"
            r"(?P<custo>\d+[\.,]\d+)\s+"
            r"(?P<total>\d+[\.,]\d+)"
        ),
        re.compile(
            r"^(?P<desc>[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9\s\-/\.,]{5,}?)\s+"
            r"(?P<qtd>\d+[\.,]\d+|\d+)\s+"
            r"(?P<custo>\d+[\.,]\d+)\s+"
            r"(?P<total>\d+[\.,]\d+)$",
            re.IGNORECASE
        )
    ]

    buffer_nome = ""

    for linha in linhas:
        linha_limpa = linha.replace("CFOP5102", "CFOP5102 ")
        linha_upper = linha_limpa.upper()

        if any(x in linha_upper for x in [
            "RECEBEMOS DE", "DOCUMENTO AUXILIAR", "CHAVE DE ACESSO",
            "CÁLCULO DO IMPOSTO", "TRANSPORTADOR", "DADOS ADICIONAIS",
            "PROTOCOLO", "NATUREZA DA OPERAÇÃO", "VALOR TOTAL DA NOTA",
            "VALOR TOTAL DOS PRODUTOS", "CONSULTA DE AUTENTICIDADE",
            "INSCRIÇÃO ESTADUAL", "NOME / RAZÃO SOCIAL"
        ]):
            continue

        achou = False
        for padrao in padroes:
            m = padrao.search(linha_limpa)
            if m:
                desc = m.groupdict().get("desc", "").strip()
                nome_base = (buffer_nome + " " + desc).strip() if buffer_nome else desc
                add_produto(
                    nome_base,
                    m.groupdict().get("qtd", 0),
                    m.groupdict().get("custo", 0),
                    m.groupdict().get("total", 0)
                )
                buffer_nome = ""
                achou = True
                break

        if achou:
            continue

        parece_nome = (
            4 <= len(linha_limpa) <= 160
            and not re.fullmatch(r"[\d\.,\s\/:-]+", linha_limpa)
            and not re.search(r"\d{2}/\d{2}/\d{4}", linha_limpa)
            and not any(p in linha_upper for p in ["CÓDIGO DESCRIÇÃO", "PREÇO PREÇO", "ITENS DA NOTA"])
        )

        if parece_nome:
            buffer_nome = (buffer_nome + " " + linha_limpa).strip()[-250:]

    if produtos:
        df = pd.DataFrame(produtos)
        df = df[df["PRODUTO"].astype(str).str.len() > 4]
        df = df.drop_duplicates(subset=["PRODUTO", "QUANTIDADE", "CUSTO UNITÁRIO", "TOTAL"])
        return df.reset_index(drop=True)

    return pd.DataFrame(columns=colunas)



def gerar_pdf_relatorio_mensal(
    titulo_periodo,
    resumo_produtos,
    pedidos_periodo,
    faturamento,
    descontos,
    lucro_bruto,
    lucro_liquido,
    quantidade_itens,
):
    """
    Gera relatório mensal A4 para impressão.
    """
    if canvas is None or A4 is None:
        return None

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#555555")
    margem = 15 * mm
    y = altura - 15 * mm

    def cabecalho():
        nonlocal y
        pdf.setFillColor(rosa)
        pdf.setFont("Helvetica-Bold", 17)
        pdf.drawCentredString(largura / 2, y, "LUHVEE STORES")
        y -= 7 * mm

        pdf.setFillColor(preto)
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawCentredString(largura / 2, y, "RELATÓRIO MENSAL DE VENDAS")
        y -= 6 * mm

        pdf.setFont("Helvetica", 10)
        pdf.drawCentredString(largura / 2, y, titulo_periodo)
        y -= 6 * mm

        pdf.setStrokeColor(rosa)
        pdf.line(margem, y, largura - margem, y)
        y -= 6 * mm

    def nova_pagina():
        nonlocal y
        pdf.showPage()
        y = altura - 15 * mm
        cabecalho()

    def garantir_espaco(mm_necessarios):
        if y < mm_necessarios * mm:
            nova_pagina()

    cabecalho()

    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(rosa)
    pdf.drawString(margem, y, "RESUMO DO PERÍODO")
    y -= 6 * mm

    resumo_linhas = [
        ("Pedidos realizados", len(pedidos_periodo)),
        ("Produtos vendidos", quantidade_itens),
        ("Faturamento", formatar_moeda(faturamento)),
        ("Descontos concedidos", formatar_moeda(descontos)),
        ("Lucro bruto dos itens", formatar_moeda(lucro_bruto)),
        ("Lucro após descontos", formatar_moeda(lucro_liquido)),
    ]

    pdf.setFillColor(preto)
    for rotulo, valor in resumo_linhas:
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(margem, y, f"{rotulo}:")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margem + 55 * mm, y, str(valor))
        y -= 5 * mm

    y -= 2 * mm
    pdf.setStrokeColor(rosa)
    pdf.line(margem, y, largura - margem, y)
    y -= 6 * mm

    pdf.setFillColor(rosa)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(margem, y, "PRODUTOS VENDIDOS")
    y -= 6 * mm

    col_prod = margem
    col_qtd = largura - 72 * mm
    col_fat = largura - 43 * mm
    col_lucro = largura - margem

    pdf.setFillColor(preto)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(col_prod, y, "Produto")
    pdf.drawRightString(col_qtd, y, "Qtd.")
    pdf.drawRightString(col_fat, y, "Faturamento")
    pdf.drawRightString(col_lucro, y, "Lucro")
    y -= 3 * mm
    pdf.setStrokeColor(cinza)
    pdf.line(margem, y, largura - margem, y)
    y -= 4 * mm

    if resumo_produtos.empty:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margem, y, "Nenhum produto vendido no período.")
        y -= 6 * mm
    else:
        for _, row in resumo_produtos.iterrows():
            garantir_espaco(25)

            nome = str(row.get("PRODUTO", ""))
            if len(nome) > 52:
                nome = nome[:49] + "..."

            pdf.setFillColor(preto)
            pdf.setFont("Helvetica", 7.5)
            pdf.drawString(col_prod, y, nome)
            pdf.drawRightString(col_qtd, y, str(numero_para_int(row.get("QUANTIDADE", 0))))
            pdf.drawRightString(col_fat, y, formatar_moeda(row.get("FATURAMENTO", 0)))
            pdf.drawRightString(col_lucro, y, formatar_moeda(row.get("LUCRO", 0)))
            y -= 4.5 * mm

    garantir_espaco(35)
    y -= 3 * mm
    pdf.setStrokeColor(rosa)
    pdf.line(margem, y, largura - margem, y)
    y -= 6 * mm

    pdf.setFillColor(rosa)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(margem, y, "PEDIDOS DO MÊS")
    y -= 6 * mm

    pdf.setFillColor(preto)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(margem, y, "Pedido")
    pdf.drawString(margem + 28 * mm, y, "Data")
    pdf.drawString(margem + 62 * mm, y, "Cliente")
    pdf.drawRightString(largura - 50 * mm, y, "Desconto")
    pdf.drawRightString(largura - margem, y, "Total")
    y -= 3 * mm
    pdf.setStrokeColor(cinza)
    pdf.line(margem, y, largura - margem, y)
    y -= 4 * mm

    if pedidos_periodo.empty:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margem, y, "Nenhum pedido no período.")
    else:
        for _, row in pedidos_periodo.iterrows():
            garantir_espaco(22)
            cliente = str(row.get("CLIENTE", ""))
            if len(cliente) > 28:
                cliente = cliente[:25] + "..."

            pdf.setFillColor(preto)
            pdf.setFont("Helvetica", 7.5)
            pdf.drawString(margem, y, str(row.get("PEDIDO", "")))
            pdf.drawString(margem + 28 * mm, y, str(row.get("DATA", ""))[:10])
            pdf.drawString(margem + 62 * mm, y, cliente)
            pdf.drawRightString(largura - 50 * mm, y, formatar_moeda(row.get("DESCONTO", 0)))
            pdf.drawRightString(largura - margem, y, formatar_moeda(row.get("TOTAL", 0)))
            y -= 4.5 * mm

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()



# ==============================================================================
# CLIENTES DEVEDORES / RELATÓRIO DE COBRANÇA
# ==============================================================================
def preparar_clientes_devedores(parcelas_df):
    """Organiza somente parcelas pendentes, com situação e dias para vencer."""
    df = preparar_parcelas(parcelas_df).copy()
    if df.empty:
        return pd.DataFrame(columns=COL_PARCELAS + ["VENC_DT", "DIAS", "SITUAÇÃO"])

    df["VENC_DT"] = pd.to_datetime(df["VENCIMENTO"], dayfirst=True, errors="coerce")
    df = df[df["STATUS"].astype(str).str.strip().str.upper() != "PAGO"].copy()

    hoje_ts = pd.Timestamp(hoje_brasil())
    df["DIAS"] = (df["VENC_DT"].dt.normalize() - hoje_ts.normalize()).dt.days

    def classificar(dias):
        if pd.isna(dias):
            return "Sem data"
        dias = int(dias)
        if dias < 0:
            return "Vencida"
        if dias == 0:
            return "Vence hoje"
        if dias <= 7:
            return "Próxima do vencimento"
        return "A vencer"

    df["SITUAÇÃO"] = df["DIAS"].apply(classificar)
    df = df.sort_values(["VENC_DT", "CLIENTE", "PEDIDO"], na_position="last")
    return df


def gerar_pdf_clientes_devedores(df_relatorio, titulo_filtro="Todas as pendentes"):
    if canvas is None or A4 is None:
        return None

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#555555")
    margem = 12 * mm
    y = altura - 14 * mm

    def cabecalho():
        nonlocal y
        pdf.setFillColor(rosa)
        pdf.setFont("Helvetica-Bold", 17)
        pdf.drawCentredString(largura / 2, y, "LUHVEE STORES")
        y -= 7 * mm
        pdf.setFillColor(preto)
        pdf.setFont("Helvetica-Bold", 13)
        pdf.drawCentredString(largura / 2, y, "RELATÓRIO DE CLIENTES DEVEDORES")
        y -= 6 * mm
        pdf.setFont("Helvetica", 9)
        pdf.drawCentredString(
            largura / 2,
            y,
            f"{titulo_filtro} — emitido em {agora_brasil().strftime('%d/%m/%Y %H:%M')}"
        )
        y -= 5 * mm
        pdf.setStrokeColor(rosa)
        pdf.line(margem, y, largura - margem, y)
        y -= 6 * mm

    def nova_pagina():
        nonlocal y
        pdf.showPage()
        y = altura - 14 * mm
        cabecalho()
        desenhar_titulos()

    def desenhar_titulos():
        nonlocal y
        pdf.setFillColor(preto)
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawString(margem, y, "Cliente")
        pdf.drawString(margem + 52 * mm, y, "Pedido")
        pdf.drawString(margem + 76 * mm, y, "Parcela")
        pdf.drawString(margem + 96 * mm, y, "Vencimento")
        pdf.drawString(margem + 124 * mm, y, "Situação")
        pdf.drawRightString(largura - margem, y, "Valor")
        y -= 3 * mm
        pdf.setStrokeColor(cinza)
        pdf.line(margem, y, largura - margem, y)
        y -= 4 * mm

    cabecalho()

    total = df_relatorio["VALOR"].apply(numero_para_float).sum() if not df_relatorio.empty else 0
    vencido = (
        df_relatorio[df_relatorio["SITUAÇÃO"] == "Vencida"]["VALOR"].apply(numero_para_float).sum()
        if not df_relatorio.empty else 0
    )
    pdf.setFont("Helvetica-Bold", 9)
    pdf.setFillColor(preto)
    pdf.drawString(margem, y, f"Quantidade de parcelas: {len(df_relatorio)}")
    pdf.drawString(margem + 70 * mm, y, f"Total pendente: {formatar_moeda(total)}")
    pdf.drawRightString(largura - margem, y, f"Total vencido: {formatar_moeda(vencido)}")
    y -= 7 * mm
    desenhar_titulos()

    if df_relatorio.empty:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(margem, y, "Nenhuma parcela encontrada para o filtro selecionado.")
    else:
        for _, row in df_relatorio.iterrows():
            if y < 18 * mm:
                nova_pagina()

            cliente = str(row.get("CLIENTE", ""))
            if len(cliente) > 27:
                cliente = cliente[:24] + "..."

            situacao = str(row.get("SITUAÇÃO", ""))
            dias = row.get("DIAS", "")
            if situacao == "Vencida" and pd.notna(dias):
                situacao = f"{abs(int(dias))}d atraso"
            elif situacao in ["A vencer", "Próxima do vencimento"] and pd.notna(dias):
                situacao = f"em {int(dias)}d"

            pdf.setFillColor(preto)
            pdf.setFont("Helvetica", 7.2)
            pdf.drawString(margem, y, cliente)
            pdf.drawString(margem + 52 * mm, y, str(row.get("PEDIDO", "")))
            pdf.drawString(margem + 76 * mm, y, str(row.get("PARCELA", "")))
            pdf.drawString(margem + 96 * mm, y, str(row.get("VENCIMENTO", "")))
            pdf.drawString(margem + 124 * mm, y, situacao)
            pdf.drawRightString(largura - margem, y, formatar_moeda(row.get("VALOR", 0)))
            y -= 4.5 * mm

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


# ==============================================================================
# MENU
# ==============================================================================
menu = [
    "Dashboard",
    "📊 Relatórios Mensais",
    "👥 Clientes",
    "📦 Produtos / Estoque",
    "🧾 Criar Pedido",
    "📋 Histórico de Pedidos",
    "💳 Parcelas / Crediário",
    "📋 Clientes Devedores",
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

    diag = diagnostico_google()
    ss = conectar_google_sheets()

    if ss is not None:
        st.success("✅ Conectado ao Google Sheets com sucesso.")
        st.write("Planilha:", ss.title)
        st.write("Abas esperadas:", list(ABAS.keys()))

        fontes = st.session_state.get("fonte_dados", {})
        if fontes:
            st.markdown("### Fonte atual dos dados")
            for aba in ABAS:
                st.write(f"• {aba}: {fontes.get(aba, 'ainda não carregada')}")

        if st.button("🔄 Recarregar todos os dados do Google Sheets"):
            st.session_state.pop("dados", None)
            st.session_state.dados = carregar_tudo()
            st.success("Dados recarregados diretamente do Google Sheets.")
            st.rerun()
    else:
        st.error("❌ Não conectado ao Google Sheets.")
        st.warning(
            "MODO DE SEGURANÇA: enquanto a conexão estiver indisponível, o ERP não deve gravar alterações na base principal."
        )

        st.write("Secrets encontrados:", "✅ Sim" if diag.get("secrets_ok") else "❌ Não")
        st.write("SPREADSHEET_ID encontrado:", "✅ Sim" if diag.get("spreadsheet_id_ok") else "❌ Não")
        st.write("Credencial Google encontrada:", "✅ Sim" if diag.get("credencial_ok") else "❌ Não")
        st.write("gspread carregado:", "✅ Sim" if diag.get("gspread_ok") else "❌ Não")
        st.write("Google Credentials carregado:", "✅ Sim" if diag.get("credentials_ok") else "❌ Não")

        erro = st.session_state.get("google_sheets_erro", "")
        if erro:
            st.markdown("### Motivo técnico da falha")
            st.code(erro)
        elif diag.get("erro_importacao"):
            st.code(diag["erro_importacao"])
        else:
            st.info("A conexão falhou sem retornar detalhe adicional. Reinicie o app após conferir os Secrets.")

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
# RELATÓRIOS MENSAIS
# ==============================================================================
elif escolha == "📊 Relatórios Mensais":
    st.subheader("📊 Relatórios Mensais da LuhVee Stores")

    pedidos_rel = preparar_pedidos(dados("PEDIDOS"))
    itens_rel = preparar_itens(dados("ITENS_PEDIDO"))

    if pedidos_rel.empty:
        st.info("Ainda não existem pedidos cadastrados para gerar relatórios.")
    else:
        pedidos_rel = pedidos_rel.copy()
        pedidos_rel["DATA_DT"] = pd.to_datetime(
            pedidos_rel["DATA"],
            dayfirst=True,
            errors="coerce"
        )

        anos_disponiveis = sorted(
            pedidos_rel["DATA_DT"].dropna().dt.year.unique().tolist(),
            reverse=True
        )

        if not anos_disponiveis:
            st.warning("Não consegui reconhecer as datas dos pedidos cadastrados.")
        else:
            meses = {
                1: "Janeiro",
                2: "Fevereiro",
                3: "Março",
                4: "Abril",
                5: "Maio",
                6: "Junho",
                7: "Julho",
                8: "Agosto",
                9: "Setembro",
                10: "Outubro",
                11: "Novembro",
                12: "Dezembro",
            }

            hoje_rel = hoje_brasil()
            r1, r2, r3 = st.columns(3)

            ano_padrao = hoje_rel.year if hoje_rel.year in anos_disponiveis else anos_disponiveis[0]
            ano_sel = r1.selectbox(
                "Ano",
                anos_disponiveis,
                index=anos_disponiveis.index(ano_padrao)
            )

            mes_sel = r2.selectbox(
                "Mês",
                list(meses.keys()),
                index=hoje_rel.month - 1,
                format_func=lambda numero: meses[numero]
            )

            incluir_cancelados = r3.checkbox(
                "Incluir pedidos cancelados",
                value=False
            )

            mask_periodo = (
                (pedidos_rel["DATA_DT"].dt.year == ano_sel) &
                (pedidos_rel["DATA_DT"].dt.month == mes_sel)
            )
            pedidos_mes = pedidos_rel[mask_periodo].copy()

            if not incluir_cancelados:
                pedidos_mes = pedidos_mes[
                    pedidos_mes["STATUS"].astype(str).str.strip().str.upper() != "CANCELADO"
                ]

            ids_mes = pedidos_mes["PEDIDO"].astype(str).tolist()
            itens_mes = itens_rel[
                itens_rel["PEDIDO"].astype(str).isin(ids_mes)
            ].copy()

            faturamento_mes = pedidos_mes["TOTAL"].apply(numero_para_float).sum()
            descontos_mes = pedidos_mes["DESCONTO"].apply(numero_para_float).sum()
            total_bruto_mes = pedidos_mes["TOTAL BRUTO"].apply(numero_para_float).sum()
            lucro_bruto_mes = itens_mes["LUCRO"].apply(numero_para_float).sum() if not itens_mes.empty else 0.0
            lucro_liquido_mes = lucro_bruto_mes - descontos_mes
            quantidade_vendida = itens_mes["QUANTIDADE"].apply(numero_para_int).sum() if not itens_mes.empty else 0

            if itens_mes.empty:
                resumo_produtos = pd.DataFrame(
                    columns=["PRODUTO", "QUANTIDADE", "FATURAMENTO", "LUCRO"]
                )
            else:
                itens_mes["QUANTIDADE"] = itens_mes["QUANTIDADE"].apply(numero_para_int)
                itens_mes["TOTAL"] = itens_mes["TOTAL"].apply(numero_para_float)
                itens_mes["LUCRO"] = itens_mes["LUCRO"].apply(numero_para_float)

                resumo_produtos = (
                    itens_mes.groupby("PRODUTO", as_index=False)
                    .agg(
                        QUANTIDADE=("QUANTIDADE", "sum"),
                        FATURAMENTO=("TOTAL", "sum"),
                        LUCRO=("LUCRO", "sum"),
                    )
                    .sort_values(
                        by=["QUANTIDADE", "FATURAMENTO"],
                        ascending=[False, False]
                    )
                    .reset_index(drop=True)
                )

            st.markdown(f"### Resultado de {meses[mes_sel]} de {ano_sel}")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Pedidos", len(pedidos_mes))
            m2.metric("Itens vendidos", int(quantidade_vendida))
            m3.metric("Faturamento", formatar_moeda(faturamento_mes))
            m4.metric("Lucro após descontos", formatar_moeda(lucro_liquido_mes))

            m5, m6, m7 = st.columns(3)
            m5.metric("Total bruto", formatar_moeda(total_bruto_mes))
            m6.metric("Descontos", formatar_moeda(descontos_mes))
            m7.metric("Lucro bruto", formatar_moeda(lucro_bruto_mes))

            if pedidos_mes.empty:
                st.info("Não existem vendas cadastradas nesse mês.")
            else:
                st.markdown("### 🏆 Produtos mais vendidos")
                st.dataframe(
                    resumo_produtos,
                    use_container_width=True,
                    hide_index=True
                )

                st.markdown("### 🧾 Pedidos do período")
                pedidos_exibir = pedidos_mes[
                    [
                        "PEDIDO", "DATA", "CLIENTE", "PAGAMENTO",
                        "PARCELAS", "TOTAL BRUTO", "DESCONTO", "TOTAL", "STATUS"
                    ]
                ].copy()
                st.dataframe(
                    pedidos_exibir,
                    use_container_width=True,
                    hide_index=True
                )

                st.markdown("### 👥 Produção por cliente")
                producao_cliente = (
                    pedidos_mes.groupby("CLIENTE", as_index=False)
                    .agg(
                        PEDIDOS=("PEDIDO", "count"),
                        TOTAL_BRUTO=("TOTAL BRUTO", "sum"),
                        DESCONTOS=("DESCONTO", "sum"),
                        FATURAMENTO=("TOTAL", "sum"),
                    )
                    .sort_values("FATURAMENTO", ascending=False)
                    .reset_index(drop=True)
                )
                st.dataframe(
                    producao_cliente,
                    use_container_width=True,
                    hide_index=True
                )

                periodo_nome = f"{meses[mes_sel]} de {ano_sel}"

                pdf_relatorio = gerar_pdf_relatorio_mensal(
                    periodo_nome,
                    resumo_produtos,
                    pedidos_mes,
                    faturamento_mes,
                    descontos_mes,
                    lucro_bruto_mes,
                    lucro_liquido_mes,
                    int(quantidade_vendida),
                )

                col_b1, col_b2, col_b3 = st.columns(3)

                if pdf_relatorio:
                    col_b1.download_button(
                        "📄 Baixar relatório PDF",
                        data=pdf_relatorio,
                        file_name=f"relatorio_luhvee_{mes_sel:02d}_{ano_sel}.pdf",
                        mime="application/pdf"
                    )

                csv_produtos = resumo_produtos.to_csv(
                    index=False,
                    sep=";",
                    encoding="utf-8-sig"
                ).encode("utf-8-sig")

                col_b2.download_button(
                    "📦 Baixar produtos vendidos CSV",
                    data=csv_produtos,
                    file_name=f"produtos_vendidos_{mes_sel:02d}_{ano_sel}.csv",
                    mime="text/csv"
                )

                csv_pedidos = pedidos_exibir.to_csv(
                    index=False,
                    sep=";",
                    encoding="utf-8-sig"
                ).encode("utf-8-sig")

                col_b3.download_button(
                    "🧾 Baixar pedidos do mês CSV",
                    data=csv_pedidos,
                    file_name=f"pedidos_mes_{mes_sel:02d}_{ano_sel}.csv",
                    mime="text/csv"
                )


# ==============================================================================
# CLIENTES
# ==============================================================================
elif escolha == "👥 Clientes":
    st.subheader("👥 Clientes")
    clientes = safe_df(dados("CLIENTES"), COL_CLIENTES)

    with st.form("form_cliente", clear_on_submit=True, enter_to_submit=False):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome")
        whatsapp = c2.text_input("WhatsApp")
        c3, c4 = st.columns(2)
        cidade = c3.text_input("Cidade")
        cpf = c4.text_input("CPF")
        endereco = st.text_input("Endereço")
        obs = st.text_area("Observações")
        if st.form_submit_button("Salvar Cliente"):
            nome_limpo = nome.strip()
            whatsapp_limpo = whatsapp.strip()

            if not nome_limpo:
                st.error("Informe o nome.")
            else:
                # Proteção contra cadastro duplicado.
                # No Streamlit, apertar ENTER dentro do formulário pode reenviar o cadastro.
                clientes_check = clientes.copy()
                clientes_check["NOME_CHECK"] = clientes_check["NOME"].astype(str).str.strip().str.upper()
                clientes_check["WHATSAPP_CHECK"] = clientes_check["WHATSAPP"].astype(str).str.replace(r"\D", "", regex=True)

                nome_check = nome_limpo.upper()
                whats_check = re.sub(r"\D", "", whatsapp_limpo)

                duplicado_nome = nome_check in clientes_check["NOME_CHECK"].tolist()
                duplicado_whats = whats_check != "" and whats_check in clientes_check["WHATSAPP_CHECK"].tolist()

                if duplicado_nome or duplicado_whats:
                    st.warning("Esse cliente já está cadastrado. Não salvei duplicado.")
                else:
                    novo = {
                        "ID": novo_id("CLI", clientes, "ID"),
                        "NOME": nome_limpo,
                        "WHATSAPP": whatsapp_limpo,
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

    with st.form("form_produto", clear_on_submit=True, enter_to_submit=False):
        c1, c2, c3b = st.columns([1, 1.4, 2])
        codigo = c1.text_input("Código interno")
        codigo_barras = c2.text_input("Código de barras (opcional)", help="Pode passar o leitor aqui ao cadastrar um produto novo.")
        produto = c3b.text_input("Produto")
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
                    "CÓDIGO BARRAS": re.sub(r"\s+", "", codigo_barras.strip()),
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

    st.markdown("### 🔗 Vincular código de barras a produto já cadastrado")
    st.caption("Escolha o produto, clique no campo de código e passe o leitor. O código interno do produto não será alterado.")
    with st.form("form_vincular_barcode", clear_on_submit=True):
        vb1, vb2 = st.columns([2, 1.5])
        produto_vincular = vb1.selectbox(
            "Produto",
            produtos["PRODUTO"].astype(str).tolist(),
            key="produto_vincular_barcode"
        )
        barcode_vincular = vb2.text_input(
            "Código de barras",
            placeholder="Passe o leitor aqui...",
            key="barcode_vincular_input"
        )
        salvar_vinculo = st.form_submit_button("💾 Vincular código de barras")

    if salvar_vinculo:
        barcode_limpo = re.sub(r"\s+", "", str(barcode_vincular or "").strip()).upper()
        if not barcode_limpo:
            st.warning("Nenhum código de barras foi lido.")
        else:
            barras_atuais = produtos["CÓDIGO BARRAS"].astype(str).apply(
                lambda x: re.sub(r"\s+", "", str(x).strip()).upper()
            )
            conflito = produtos[(barras_atuais == barcode_limpo) & (produtos["PRODUTO"].astype(str) != str(produto_vincular))]
            if not conflito.empty:
                st.error(f"Esse código já está vinculado a: {conflito.iloc[0]['PRODUTO']}")
            else:
                idx_vinc = produtos[produtos["PRODUTO"].astype(str) == str(produto_vincular)].index[0]
                produtos.loc[idx_vinc, "CÓDIGO BARRAS"] = barcode_limpo
                atualizar("PRODUTOS", produtos)
                st.success(f"Código {barcode_limpo} vinculado a {produto_vincular}.")
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
        st.info("O Enter do formulário principal foi desativado. O leitor usa Enter apenas no campo de código de barras. Para salvar a venda, clique em Finalizar Pedido.")

        # ----------------------------------------------------------------------
        # LEITOR DE CÓDIGO DE BARRAS
        # O leitor USB funciona como teclado: digita o código e envia ENTER.
        # O carrinho do leitor fica apenas na sessão até o pedido ser finalizado.
        # ----------------------------------------------------------------------
        if st.session_state.get("scanner_pedido_id") != pedido_id:
            st.session_state["scanner_pedido_id"] = pedido_id
            st.session_state["scanner_cart"] = {}

        st.session_state.setdefault("scanner_cart", {})

        def normalizar_codigo_barra(valor):
            return re.sub(r"\s+", "", str(valor or "").strip()).upper()

        st.markdown("### 📷 Leitor de código de barras")
        st.caption(
            "Clique uma vez no campo abaixo e passe o produto no leitor. "
            "O ERP procura primeiro em CÓDIGO BARRAS. Cada leitura adiciona 1 unidade ao pedido."
        )

        def processar_codigo_scanner():
            """Executa automaticamente quando o leitor envia ENTER."""
            codigo_busca = normalizar_codigo_barra(
                st.session_state.get("scanner_codigo_input", "")
            )
            st.session_state["scanner_codigo_input"] = ""

            if not codigo_busca:
                st.session_state["scanner_feedback"] = ("warning", "Nenhum código foi lido.")
                return

            barras_normalizadas = produtos["CÓDIGO BARRAS"].astype(str).apply(normalizar_codigo_barra)
            encontrados = produtos[barras_normalizadas == codigo_busca]

            if encontrados.empty:
                codigos_internos = produtos["CÓDIGO"].astype(str).apply(normalizar_codigo_barra)
                encontrados = produtos[codigos_internos == codigo_busca]

            if encontrados.empty:
                st.session_state["scanner_feedback"] = (
                    "error",
                    f"Código {codigo_busca} não encontrado. "
                    "Vincule esse código em Produtos / Estoque antes de tentar novamente."
                )
                return

            if len(encontrados) > 1:
                nomes = ", ".join(encontrados["PRODUTO"].astype(str).tolist()[:5])
                st.session_state["scanner_feedback"] = (
                    "error",
                    f"O código {codigo_busca} está ligado a mais de um produto ({nomes}). "
                    "Corrija a duplicidade em Produtos / Estoque."
                )
                return

            row = encontrados.iloc[0]
            nome_produto = str(row["PRODUTO"]).strip()
            estoque_disponivel = numero_para_int(row["ESTOQUE"])
            preco_venda = numero_para_float(row["PREÇO VENDA"])

            cart = st.session_state.get("scanner_cart", {})
            chave_item = normalizar_codigo_barra(row.get("CÓDIGO BARRAS", "")) or codigo_busca
            item_atual = cart.get(chave_item, {
                "CÓDIGO": chave_item,
                "PRODUTO": nome_produto,
                "QUANTIDADE": 0,
                "PREÇO": preco_venda,
            })
            nova_qtd = numero_para_int(item_atual.get("QUANTIDADE", 0)) + 1

            if nova_qtd > estoque_disponivel:
                st.session_state["scanner_feedback"] = (
                    "error",
                    f"{nome_produto}: estoque disponível {estoque_disponivel}. "
                    f"A leitura deixaria a quantidade em {nova_qtd}."
                )
                return

            item_atual["QUANTIDADE"] = nova_qtd
            item_atual["PREÇO"] = preco_venda
            cart[chave_item] = item_atual
            st.session_state["scanner_cart"] = cart
            st.session_state["scanner_feedback"] = (
                "success",
                f"✅ {nome_produto} adicionado. Quantidade: {nova_qtd}"
            )

        # Fora de formulário: o ENTER enviado pelo leitor dispara on_change automaticamente.
        codigo_lido = st.text_input(
            "Código de barras",
            placeholder="Clique aqui uma vez e passe os produtos no leitor...",
            key="scanner_codigo_input",
            on_change=processar_codigo_scanner,
            help="O leitor funciona como teclado. Ao terminar a leitura, o ENTER adiciona o produto."
        )

        st.caption(
            "O leitor envia ENTER automaticamente. Depois da primeira leitura, "
            "mantenha este campo selecionado; cada novo código aumenta a quantidade."
        )

        feedback_scanner = st.session_state.pop("scanner_feedback", None)
        if feedback_scanner:
            tipo_feedback, mensagem_feedback = feedback_scanner
            if tipo_feedback == "success":
                st.success(mensagem_feedback)
            elif tipo_feedback == "warning":
                st.warning(mensagem_feedback)
            else:
                st.error(mensagem_feedback)

        cart = st.session_state.get("scanner_cart", {})
        itens_scanner = []

        if cart:
            df_scanner = pd.DataFrame(list(cart.values()))
            df_scanner["TOTAL"] = df_scanner.apply(
                lambda r: numero_para_int(r.get("QUANTIDADE", 0)) * numero_para_float(r.get("PREÇO", 0)),
                axis=1
            )
            st.markdown("#### 🛒 Itens lidos")
            st.dataframe(
                df_scanner[["CÓDIGO", "PRODUTO", "QUANTIDADE", "PREÇO", "TOTAL"]],
                use_container_width=True,
                hide_index=True
            )
            st.metric("Subtotal do leitor", formatar_moeda(df_scanner["TOTAL"].sum()))

            r1, r2 = st.columns([3, 1])
            remover_codigo = r1.selectbox(
                "Remover item lido",
                [""] + list(cart.keys()),
                format_func=lambda cod: "" if not cod else f"{cart[cod]['PRODUTO']} | {cod}",
                key="scanner_remover_select"
            )
            if r2.button("➖ Remover", key="scanner_remover_btn"):
                if remover_codigo:
                    cart.pop(remover_codigo, None)
                    st.session_state["scanner_cart"] = cart
                    st.rerun()

            if st.button("🧹 Limpar todos os itens lidos", key="scanner_limpar_btn"):
                st.session_state["scanner_cart"] = {}
                st.rerun()

            for item in cart.values():
                itens_scanner.append({
                    "PRODUTO": str(item.get("PRODUTO", "")),
                    "QUANTIDADE": numero_para_int(item.get("QUANTIDADE", 0)),
                    "PREÇO": numero_para_float(item.get("PREÇO", 0)),
                })
        else:
            st.caption("Nenhum item lido ainda. Você também pode adicionar produtos manualmente abaixo.")

        st.markdown("---")
        st.markdown("### Dados do pedido e produtos manuais")

        with st.form("form_pedido", enter_to_submit=False):
            c1, c2, c3 = st.columns(3)
            cliente_nome = c1.selectbox("Cliente", clientes["NOME"].astype(str).tolist())
            pagamento = c2.selectbox("Pagamento", ["PIX", "Dinheiro", "Débito", "Crédito", "Crediário LuhVee", "Mercado Pago", "PagBank", "PicPay"])
            parcelas = c3.selectbox("Parcelas", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"])

            c4, c5 = st.columns(2)
            plataforma = c4.selectbox("Plataforma", ["WhatsApp", "Instagram", "Loja Física", "Yampi", "Shopee", "Mercado Livre", "iFood"])
            status = c5.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"])

            primeiro_vencimento = st.date_input("Primeiro vencimento", value=hoje_brasil(), format="DD/MM/YYYY")

            desconto_pedido = st.number_input(
                "Desconto no pedido (R$)",
                min_value=0.0,
                value=0.0,
                format="%.2f",
                help="Digite aqui o desconto dado para a cliente. O total e as parcelas serão calculados com desconto."
            )

            st.markdown("### Produtos manuais")
            st.caption("Use esta parte para produtos sem código de barras ou quando quiser alterar o preço manualmente.")
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

                preco_key = f"preco_{i}"
                produto_anterior_key = f"produto_anterior_{i}"

                if prod and st.session_state.get(produto_anterior_key) != prod:
                    st.session_state[preco_key] = preco_padrao
                    st.session_state[produto_anterior_key] = prod

                if not prod:
                    st.session_state[produto_anterior_key] = ""

                preco = p3.number_input(
                    "Preço",
                    min_value=0.0,
                    value=float(st.session_state.get(preco_key, preco_padrao)),
                    format="%.2f",
                    key=preco_key
                )

                if prod and qtd > 0:
                    itens_temp.append({"PRODUTO": prod, "QUANTIDADE": qtd, "PREÇO": preco})

            finalizar = st.form_submit_button("Finalizar Pedido")

        # Junta leitor + inclusão manual. Nada é baixado do estoque antes de Finalizar Pedido.
        itens_temp = itens_scanner + itens_temp

        if finalizar:
            if pedido_id in pedidos["PEDIDO"].astype(str).tolist():
                st.error("Esse pedido já foi salvo. Atualize a página antes de tentar novamente.")
            elif not itens_temp:
                st.error("Adicione pelo menos 1 produto pelo leitor ou manualmente.")
            else:
                # Valida estoque pelo TOTAL de unidades do mesmo produto, mesmo que ele tenha sido
                # incluído pelo leitor e também manualmente.
                quantidades_por_produto = {}
                for item in itens_temp:
                    nome = str(item["PRODUTO"])
                    quantidades_por_produto[nome] = quantidades_por_produto.get(nome, 0) + int(item["QUANTIDADE"])

                erros = []
                for nome, qtd_total in quantidades_por_produto.items():
                    linha = produtos[produtos["PRODUTO"].astype(str) == nome]
                    estoque_atual = numero_para_int(linha.iloc[0]["ESTOQUE"]) if not linha.empty else 0
                    if estoque_atual < qtd_total:
                        erros.append(f"{nome}: estoque {estoque_atual}, pedido {qtd_total}")

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

                    total_bruto = round(total_pedido, 2)
                    desconto_final = min(numero_para_float(desconto_pedido), total_bruto)
                    total_final = max(0.0, total_bruto - desconto_final)

                    valor_parcela = calcular_valor_parcela(total_final, parcelas)
                    valor_recebido = total_final if status_pago(status) else 0.0
                    saldo = 0.0 if status_pago(status) else total_final
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
                        "TOTAL BRUTO": round(total_bruto, 2),
                        "DESCONTO": round(desconto_final, 2),
                        "TOTAL": round(total_final, 2),
                        "STATUS": status,
                        "DATA PAGAMENTO": data_pg,
                        "VALOR RECEBIDO": round(valor_recebido, 2),
                        "SALDO A RECEBER": round(saldo, 2),
                    }

                    novas_parcelas = gerar_parcelas_pedido(
                        pedido_id, cliente_nome, whatsapp, parcelas, total_final,
                        primeiro_vencimento, status
                    )

                    pedidos = pd.concat([pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
                    itens_pedido = pd.concat([itens_pedido, pd.DataFrame(novos_itens)], ignore_index=True)
                    parcelas_receber = pd.concat([parcelas_receber, novas_parcelas], ignore_index=True)

                    atualizar_multiplas({
                        "PRODUTOS": produtos,
                        "PEDIDOS": pedidos,
                        "ITENS_PEDIDO": itens_pedido,
                        "PARCELAS_RECEBER": parcelas_receber,
                    })

                    # Só limpa o carrinho do leitor depois que o Google Sheets confirmou tudo.
                    st.session_state["scanner_cart"] = {}
                    st.success(f"Pedido {pedido_id} salvo. Total final: {formatar_moeda(total_final)}")
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

        if numero_para_float(pedido_info.get("DESCONTO", 0)) > 0:
            st.info(
                f"Total dos produtos: {formatar_moeda(pedido_info.get('TOTAL BRUTO', pedido_info.get('TOTAL', 0)))} | "
                f"Desconto: {formatar_moeda(pedido_info.get('DESCONTO', 0))} | "
                f"Total final: {formatar_moeda(pedido_info.get('TOTAL', 0))}"
            )

        st.markdown("### Atualizar status / pagamento")
        novo_status = st.selectbox("Status", ["Pago", "Pendente", "Entregue", "Aguardando Retirada", "Cancelado"], index=1 if pedido_info.get("STATUS") == "Pendente" else 0)
        valor_recebido = st.number_input("Valor recebido até agora", min_value=0.0, value=float(numero_para_float(pedido_info.get("VALOR RECEBIDO", 0))), format="%.2f")

        if st.button("💰 Salvar pagamento/status"):
            total = round(numero_para_float(pedido_info.get("TOTAL", 0)), 2)
            recebido_informado = min(max(0.0, numero_para_float(valor_recebido)), total)
            saldo = round(max(0.0, total - recebido_informado), 2)
            agora_pg = agora_brasil().strftime("%d/%m/%Y %H:%M")

            pedidos.loc[idx_pedido, "STATUS"] = "Pago" if saldo <= 0 else novo_status
            pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = round(recebido_informado, 2)
            pedidos.loc[idx_pedido, "SALDO A RECEBER"] = round(saldo, 2)
            pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_pg if saldo <= 0 else ""

            mask_pedido = parcelas_receber["PEDIDO"].astype(str) == str(pedido_sel)
            parcelas_do_pedido = parcelas_receber[mask_pedido].copy()

            if parcelas_do_pedido.empty:
                parcelas_novas = gerar_parcelas_pedido(
                    pedido_sel,
                    pedido_info.get("CLIENTE", ""),
                    pedido_info.get("WHATSAPP", ""),
                    pedido_info.get("PARCELAS", "À vista"),
                    total,
                    hoje_brasil(),
                    "Pendente"
                )
                parcelas_receber = pd.concat(
                    [parcelas_receber, parcelas_novas],
                    ignore_index=True
                )
                mask_pedido = parcelas_receber["PEDIDO"].astype(str) == str(pedido_sel)
                parcelas_do_pedido = parcelas_receber[mask_pedido].copy()

            qtd_linhas = len(parcelas_do_pedido)
            if qtd_linhas <= 0:
                qtd_linhas = quantidade_parcelas(pedido_info.get("PARCELAS", "À vista"))

            valor_base = round(total / qtd_linhas, 2) if qtd_linhas else total
            valores_originais = [valor_base] * qtd_linhas
            if valores_originais:
                valores_originais[-1] = round(total - sum(valores_originais[:-1]), 2)

            restante_pago = round(recebido_informado, 2)
            indices_parcelas = parcelas_do_pedido.index.tolist()

            for posicao, idx_parcela in enumerate(indices_parcelas):
                valor_original = round(valores_originais[posicao], 2)
                parcelas_receber.loc[idx_parcela, "PARCELA"] = f"{posicao + 1}/{qtd_linhas}"

                if restante_pago >= valor_original - 0.009:
                    parcelas_receber.loc[idx_parcela, "VALOR"] = valor_original
                    parcelas_receber.loc[idx_parcela, "STATUS"] = "Pago"
                    parcelas_receber.loc[idx_parcela, "DATA PAGAMENTO"] = agora_pg
                    restante_pago = round(restante_pago - valor_original, 2)
                elif restante_pago > 0:
                    parcelas_receber.loc[idx_parcela, "VALOR"] = round(valor_original - restante_pago, 2)
                    parcelas_receber.loc[idx_parcela, "STATUS"] = "Pendente"
                    parcelas_receber.loc[idx_parcela, "DATA PAGAMENTO"] = ""
                    restante_pago = 0.0
                else:
                    parcelas_receber.loc[idx_parcela, "VALOR"] = valor_original
                    parcelas_receber.loc[idx_parcela, "STATUS"] = "Pendente"
                    parcelas_receber.loc[idx_parcela, "DATA PAGAMENTO"] = ""

            pend_mask = (
                (parcelas_receber["PEDIDO"].astype(str) == str(pedido_sel)) &
                (parcelas_receber["STATUS"].astype(str).str.upper() != "PAGO")
            )
            total_pendente = parcelas_receber.loc[pend_mask, "VALOR"].apply(numero_para_float).sum()
            diferenca = round(saldo - total_pendente, 2)

            if abs(diferenca) >= 0.01:
                idxs_pendentes = parcelas_receber[pend_mask].index.tolist()
                if idxs_pendentes:
                    ultimo_idx = idxs_pendentes[-1]
                    atual = numero_para_float(parcelas_receber.loc[ultimo_idx, "VALOR"])
                    parcelas_receber.loc[ultimo_idx, "VALOR"] = round(max(0.0, atual + diferenca), 2)

            atualizar("PEDIDOS", pedidos)
            atualizar("PARCELAS_RECEBER", parcelas_receber)

            st.success(
                f"Pagamento atualizado. Recebido: {formatar_moeda(recebido_informado)} | "
                f"Saldo restante: {formatar_moeda(saldo)}"
            )
            st.rerun()

        st.markdown("### Itens")
        st.dataframe(itens, use_container_width=True)


        st.markdown("### ✏️ Editar itens / preços do pedido")
        st.warning(
            "Use esta área quando algum preço ou quantidade saiu errado no pedido. "
            "Ao salvar, o sistema recalcula total, desconto, parcelas e saldo."
        )

        itens_editaveis = itens.copy()
        if not itens_editaveis.empty:
            itens_editaveis["QUANTIDADE"] = itens_editaveis["QUANTIDADE"].apply(numero_para_int)
            itens_editaveis["PREÇO"] = itens_editaveis["PREÇO"].apply(numero_para_float)
            itens_editaveis["TOTAL"] = itens_editaveis["TOTAL"].apply(numero_para_float)
            itens_editaveis["LUCRO"] = itens_editaveis["LUCRO"].apply(numero_para_float)

            st.caption("Você pode corrigir principalmente QUANTIDADE e PREÇO. O TOTAL será recalculado ao salvar.")
            itens_corrigidos = st.data_editor(
                itens_editaveis,
                use_container_width=True,
                num_rows="dynamic",
                key=f"editor_itens_{pedido_sel}"
            )

            desconto_atual = numero_para_float(pedido_info.get("DESCONTO", 0))
            desconto_editado = st.number_input(
                "Desconto do pedido",
                min_value=0.0,
                value=float(desconto_atual),
                format="%.2f",
                key=f"desconto_edit_{pedido_sel}"
            )

            if st.button("💾 Salvar alterações do pedido", key=f"salvar_itens_{pedido_sel}"):
                produtos = preparar_produtos(dados("PRODUTOS"))
                itens_antigos = itens.copy()
                itens_novos = preparar_itens(itens_corrigidos)

                for idx_item, row_item in itens_novos.iterrows():
                    produto_nome = str(row_item.get("PRODUTO", "")).strip()
                    qtd_nova = numero_para_int(row_item.get("QUANTIDADE", 0))
                    preco_novo = numero_para_float(row_item.get("PREÇO", 0))
                    total_item_novo = round(qtd_nova * preco_novo, 2)

                    custo_unit = 0.0
                    if produto_nome:
                        match_custo = produtos["PRODUTO"].astype(str).str.strip().str.upper() == produto_nome.upper()
                        if match_custo.any():
                            idx_custo = produtos[match_custo].index[0]
                            custo_unit = numero_para_float(produtos.loc[idx_custo, "CUSTO"])

                    itens_novos.loc[idx_item, "TOTAL"] = total_item_novo
                    itens_novos.loc[idx_item, "LUCRO"] = round(total_item_novo - (qtd_nova * custo_unit), 2)

                def mapa_quantidades(df_itens):
                    mapa = {}
                    if df_itens is None or df_itens.empty:
                        return mapa
                    for _, r in df_itens.iterrows():
                        prod_nome = str(r.get("PRODUTO", "")).strip().upper()
                        qtd_val = numero_para_int(r.get("QUANTIDADE", 0))
                        if prod_nome:
                            mapa[prod_nome] = mapa.get(prod_nome, 0) + qtd_val
                    return mapa

                mapa_antigo = mapa_quantidades(itens_antigos)
                mapa_novo = mapa_quantidades(itens_novos)
                todos_produtos = set(list(mapa_antigo.keys()) + list(mapa_novo.keys()))

                erro_estoque = False
                mensagens_estoque = []

                for prod_nome in todos_produtos:
                    qtd_antiga = mapa_antigo.get(prod_nome, 0)
                    qtd_nova = mapa_novo.get(prod_nome, 0)
                    diferenca = qtd_nova - qtd_antiga

                    if diferenca > 0:
                        match_prod = produtos["PRODUTO"].astype(str).str.strip().str.upper() == prod_nome
                        if match_prod.any():
                            idx_prod = produtos[match_prod].index[0]
                            estoque_atual = numero_para_int(produtos.loc[idx_prod, "ESTOQUE"])
                            if estoque_atual < diferenca:
                                erro_estoque = True
                                mensagens_estoque.append(
                                    f"{prod_nome}: estoque atual {estoque_atual}, aumento necessário {diferenca}"
                                )

                if erro_estoque:
                    for msg in mensagens_estoque:
                        st.error(msg)
                    st.stop()

                for prod_nome in todos_produtos:
                    qtd_antiga = mapa_antigo.get(prod_nome, 0)
                    qtd_nova = mapa_novo.get(prod_nome, 0)
                    diferenca = qtd_nova - qtd_antiga

                    match_prod = produtos["PRODUTO"].astype(str).str.strip().str.upper() == prod_nome
                    if match_prod.any():
                        idx_prod = produtos[match_prod].index[0]
                        estoque_atual = numero_para_int(produtos.loc[idx_prod, "ESTOQUE"])
                        produtos.loc[idx_prod, "ESTOQUE"] = int(estoque_atual - diferenca)

                itens_pedido_sem_pedido = itens_pedido[itens_pedido["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                itens_novos["PEDIDO"] = pedido_sel
                itens_pedido_atualizado = pd.concat([itens_pedido_sem_pedido, itens_novos[COL_ITENS]], ignore_index=True)

                total_bruto_novo = round(itens_novos["TOTAL"].apply(numero_para_float).sum(), 2)
                desconto_final_novo = min(numero_para_float(desconto_editado), total_bruto_novo)
                total_final_novo = max(0.0, total_bruto_novo - desconto_final_novo)

                parcelas_texto = pedido_info.get("PARCELAS", "À vista")
                valor_parcela_novo = calcular_valor_parcela(total_final_novo, parcelas_texto)

                parcelas_atualizadas = parcelas_receber.copy()
                mask_parc = parcelas_atualizadas["PEDIDO"].astype(str) == pedido_sel
                if mask_parc.any():
                    parcelas_atualizadas.loc[mask_parc, "VALOR"] = round(valor_parcela_novo, 2)

                parcelas_pedido_novo = parcelas_atualizadas[parcelas_atualizadas["PEDIDO"].astype(str) == pedido_sel]
                if not parcelas_pedido_novo.empty:
                    valor_recebido_novo = parcelas_pedido_novo[
                        parcelas_pedido_novo["STATUS"].astype(str).str.upper() == "PAGO"
                    ]["VALOR"].apply(numero_para_float).sum()
                else:
                    valor_recebido_novo = total_final_novo if status_pago(pedido_info.get("STATUS", "")) else 0.0

                saldo_novo = max(0.0, total_final_novo - valor_recebido_novo)
                status_novo = "Pago" if saldo_novo <= 0 else pedido_info.get("STATUS", "Pendente")

                pedidos.loc[idx_pedido, "TOTAL BRUTO"] = round(total_bruto_novo, 2)
                pedidos.loc[idx_pedido, "DESCONTO"] = round(desconto_final_novo, 2)
                pedidos.loc[idx_pedido, "TOTAL"] = round(total_final_novo, 2)
                pedidos.loc[idx_pedido, "VALOR PARCELA"] = round(valor_parcela_novo, 2)
                pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = round(valor_recebido_novo, 2)
                pedidos.loc[idx_pedido, "SALDO A RECEBER"] = round(saldo_novo, 2)
                pedidos.loc[idx_pedido, "STATUS"] = status_novo

                atualizar_multiplas(
                    {
                        "PRODUTOS": produtos,
                        "ITENS_PEDIDO": itens_pedido_atualizado,
                        "PEDIDOS": pedidos,
                        "PARCELAS_RECEBER": parcelas_atualizadas,
                    },
                    permitir_reducao={"ITENS_PEDIDO"}
                )

                st.success("Pedido corrigido com sucesso. Total, parcelas e estoque foram atualizados.")
                st.rerun()


        st.markdown("### Parcelas")
        st.dataframe(parcelas_pedido, use_container_width=True)

        pdf_bytes = gerar_pdf_recibo(pedido_info, itens, parcelas_pedido)
        if pdf_bytes:
            st.download_button("📄 Baixar Recibo A4 PDF", data=pdf_bytes, file_name=f"recibo_{pedido_sel}.pdf", mime="application/pdf")

        st.markdown("### Excluir pedido")
        st.warning("Ao excluir um pedido, o sistema devolve automaticamente os itens ao estoque.")
        confirmar = st.checkbox(f"Confirmo excluir {pedido_sel} e devolver os produtos ao estoque")
        if st.button("🗑️ Excluir pedido e devolver estoque"):
            if confirmar:
                produtos = preparar_produtos(dados("PRODUTOS"))
                itens_excluir = itens_pedido[itens_pedido["PEDIDO"].astype(str) == pedido_sel].copy()

                # Devolve os itens ao estoque
                for _, item_del in itens_excluir.iterrows():
                    nome_prod = str(item_del.get("PRODUTO", "")).strip()
                    qtd_devolver = numero_para_int(item_del.get("QUANTIDADE", 0))

                    if nome_prod and qtd_devolver > 0:
                        match = produtos["PRODUTO"].astype(str).str.strip().str.upper() == nome_prod.upper()
                        if match.any():
                            idx_prod = produtos[match].index[0]
                            produtos.loc[idx_prod, "ESTOQUE"] = int(numero_para_int(produtos.loc[idx_prod, "ESTOQUE"]) + qtd_devolver)

                pedidos = pedidos[pedidos["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                itens_pedido = itens_pedido[itens_pedido["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)
                parcelas_receber = parcelas_receber[parcelas_receber["PEDIDO"].astype(str) != pedido_sel].reset_index(drop=True)

                atualizar_multiplas(
                    {
                        "PRODUTOS": produtos,
                        "PEDIDOS": pedidos,
                        "ITENS_PEDIDO": itens_pedido,
                        "PARCELAS_RECEBER": parcelas_receber,
                    },
                    permitir_reducao={"PEDIDOS", "ITENS_PEDIDO", "PARCELAS_RECEBER"}
                )

                st.success("Pedido excluído e estoque devolvido com sucesso.")
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
# CLIENTES DEVEDORES
# ==============================================================================
elif escolha == "📋 Clientes Devedores":
    st.subheader("📋 Clientes Devedores")

    parcelas_df = preparar_parcelas(dados("PARCELAS_RECEBER"))
    pedidos = preparar_pedidos(dados("PEDIDOS"))
    devedores = preparar_clientes_devedores(parcelas_df)

    if devedores.empty:
        st.success("✅ Não há parcelas pendentes no momento.")
    else:
        hoje_ts = pd.Timestamp(hoje_brasil())
        total_pendente = devedores["VALOR"].sum()
        total_vencido = devedores[devedores["DIAS"] < 0]["VALOR"].sum()
        total_hoje = devedores[devedores["DIAS"] == 0]["VALOR"].sum()
        total_7_dias = devedores[(devedores["DIAS"] > 0) & (devedores["DIAS"] <= 7)]["VALOR"].sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total pendente", formatar_moeda(total_pendente))
        m2.metric("Total vencido", formatar_moeda(total_vencido))
        m3.metric("Vence hoje", formatar_moeda(total_hoje))
        m4.metric("Próximos 7 dias", formatar_moeda(total_7_dias))

        st.markdown("### Filtros")
        f1, f2 = st.columns([1, 2])
        filtro_situacao = f1.selectbox(
            "Mostrar",
            [
                "Todas as pendentes",
                "Vencidas",
                "Vence hoje",
                "Próximos 7 dias",
                "Próximos 15 dias",
                "Próximos 30 dias",
            ],
            key="devedores_filtro"
        )
        busca_cliente = f2.text_input(
            "Pesquisar nome, WhatsApp ou pedido",
            placeholder="Digite parte do nome, telefone ou número do pedido",
            key="devedores_busca"
        ).strip()

        filtrado = devedores.copy()
        if filtro_situacao == "Vencidas":
            filtrado = filtrado[filtrado["DIAS"] < 0]
        elif filtro_situacao == "Vence hoje":
            filtrado = filtrado[filtrado["DIAS"] == 0]
        elif filtro_situacao == "Próximos 7 dias":
            filtrado = filtrado[(filtrado["DIAS"] > 0) & (filtrado["DIAS"] <= 7)]
        elif filtro_situacao == "Próximos 15 dias":
            filtrado = filtrado[(filtrado["DIAS"] > 0) & (filtrado["DIAS"] <= 15)]
        elif filtro_situacao == "Próximos 30 dias":
            filtrado = filtrado[(filtrado["DIAS"] > 0) & (filtrado["DIAS"] <= 30)]

        if busca_cliente:
            busca_norm = busca_cliente.upper()
            mascara = (
                filtrado["CLIENTE"].astype(str).str.upper().str.contains(busca_norm, na=False)
                | filtrado["WHATSAPP"].astype(str).str.upper().str.contains(busca_norm, na=False)
                | filtrado["PEDIDO"].astype(str).str.upper().str.contains(busca_norm, na=False)
            )
            filtrado = filtrado[mascara]

        exibicao = filtrado.copy()
        exibicao["DIAS / ATRASO"] = exibicao["DIAS"].apply(
            lambda d: (
                "Sem data" if pd.isna(d)
                else f"{abs(int(d))} dia(s) em atraso" if int(d) < 0
                else "Vence hoje" if int(d) == 0
                else f"Vence em {int(d)} dia(s)"
            )
        )
        colunas_exibir = [
            "CLIENTE", "WHATSAPP", "PEDIDO", "PARCELA", "VENCIMENTO",
            "DIAS / ATRASO", "SITUAÇÃO", "VALOR"
        ]
        st.dataframe(
            exibicao[colunas_exibir],
            use_container_width=True,
            hide_index=True
        )
        st.metric("Total do filtro", formatar_moeda(filtrado["VALOR"].sum()))

        st.markdown("### Total devido por cliente")
        resumo_cliente = (
            filtrado.groupby(["CLIENTE", "WHATSAPP"], dropna=False)
            .agg(
                PARCELAS_PENDENTES=("VALOR", "size"),
                TOTAL_DEVIDO=("VALOR", "sum"),
                VENCIMENTO_MAIS_PRÓXIMO=("VENC_DT", "min"),
            )
            .reset_index()
            .sort_values("TOTAL_DEVIDO", ascending=False)
        )
        resumo_cliente["VENCIMENTO MAIS PRÓXIMO"] = resumo_cliente["VENCIMENTO_MAIS_PRÓXIMO"].dt.strftime("%d/%m/%Y").fillna("")
        resumo_cliente = resumo_cliente.drop(columns=["VENCIMENTO_MAIS_PRÓXIMO"])
        st.dataframe(resumo_cliente, use_container_width=True, hide_index=True)

        st.markdown("### Baixar relatório")
        arquivo_csv = exibicao[colunas_exibir].copy()
        arquivo_csv["VALOR"] = arquivo_csv["VALOR"].apply(lambda v: f"{numero_para_float(v):.2f}".replace(".", ","))
        csv_bytes = arquivo_csv.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")

        d1, d2 = st.columns(2)
        d1.download_button(
            "⬇️ Baixar planilha CSV",
            data=csv_bytes,
            file_name=f"clientes_devedores_{agora_brasil().strftime('%d-%m-%Y_%H-%M')}.csv",
            mime="text/csv",
            key="baixar_devedores_csv"
        )

        pdf_devedores = gerar_pdf_clientes_devedores(filtrado, filtro_situacao)
        if pdf_devedores:
            d2.download_button(
                "📄 Baixar relatório PDF A4",
                data=pdf_devedores,
                file_name=f"clientes_devedores_{agora_brasil().strftime('%d-%m-%Y_%H-%M')}.pdf",
                mime="application/pdf",
                key="baixar_devedores_pdf"
            )

        st.markdown("---")
        st.markdown("### Cobrança e baixa de pagamento")

        opcoes_devedor = []
        indices_devedor = []
        for idx_devedor, row in filtrado.iterrows():
            opcoes_devedor.append(
                f"{row['CLIENTE']} | {row['PEDIDO']} | Parcela {row['PARCELA']} | "
                f"{row['VENCIMENTO']} | {formatar_moeda(row['VALOR'])}"
            )
            indices_devedor.append(idx_devedor)

        if not opcoes_devedor:
            st.info("Nenhuma parcela encontrada para este filtro.")
        else:
            parcela_escolhida = st.selectbox(
                "Selecione a parcela",
                opcoes_devedor,
                key="devedor_parcela_escolhida"
            )
            idx_real = indices_devedor[opcoes_devedor.index(parcela_escolhida)]
            row_devedor = parcelas_df.loc[idx_real]

            cliente_msg = str(row_devedor.get("CLIENTE", "")).strip()
            venc_msg = str(row_devedor.get("VENCIMENTO", "")).strip()
            valor_msg = formatar_moeda(row_devedor.get("VALOR", 0))
            pedido_msg = str(row_devedor.get("PEDIDO", "")).strip()
            whatsapp_limpo = re.sub(r"\D", "", str(row_devedor.get("WHATSAPP", "")))
            if whatsapp_limpo and len(whatsapp_limpo) <= 11:
                whatsapp_limpo = "55" + whatsapp_limpo

            mensagem_cobranca = (
                f"Olá, {cliente_msg}. Tudo bem? ❤️\n\n"
                f"Identificamos uma parcela pendente do pedido {pedido_msg}, "
                f"no valor de {valor_msg}, com vencimento em {venc_msg}.\n\n"
                "Caso já tenha realizado o pagamento, por favor, desconsidere esta mensagem.\n\n"
                "LuhVee Stores ❤️"
            )
            st.text_area(
                "Mensagem pronta para WhatsApp",
                value=mensagem_cobranca,
                height=180,
                key="mensagem_cobranca_devedor"
            )

            if whatsapp_limpo:
                link_whatsapp = (
                    f"https://wa.me/{whatsapp_limpo}?text="
                    f"{urllib.parse.quote(mensagem_cobranca)}"
                )
                st.link_button("💬 Abrir cobrança no WhatsApp", link_whatsapp)
            else:
                st.warning("Esse cliente não possui um WhatsApp válido cadastrado.")

            confirmar_pg = st.checkbox(
                "Confirmo que recebi esta parcela",
                key="confirmar_baixa_devedor"
            )
            if st.button("✅ Marcar parcela como paga", key="baixar_parcela_devedor"):
                if not confirmar_pg:
                    st.error("Marque a confirmação antes de dar baixa.")
                else:
                    pedido_id = str(parcelas_df.loc[idx_real, "PEDIDO"])
                    parcelas_df.loc[idx_real, "STATUS"] = "Pago"
                    parcelas_df.loc[idx_real, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                    parcelas_pedido = parcelas_df[
                        parcelas_df["PEDIDO"].astype(str) == pedido_id
                    ]
                    recebido = parcelas_pedido[
                        parcelas_pedido["STATUS"].astype(str).str.upper() == "PAGO"
                    ]["VALOR"].sum()
                    saldo = parcelas_pedido[
                        parcelas_pedido["STATUS"].astype(str).str.upper() != "PAGO"
                    ]["VALOR"].sum()

                    if pedido_id in pedidos["PEDIDO"].astype(str).tolist():
                        idx_pedido = pedidos[
                            pedidos["PEDIDO"].astype(str) == pedido_id
                        ].index[0]
                        pedidos.loc[idx_pedido, "VALOR RECEBIDO"] = round(recebido, 2)
                        pedidos.loc[idx_pedido, "SALDO A RECEBER"] = round(saldo, 2)
                        pedidos.loc[idx_pedido, "STATUS"] = "Pago" if saldo <= 0 else "Pendente"
                        if saldo <= 0:
                            pedidos.loc[idx_pedido, "DATA PAGAMENTO"] = agora_brasil().strftime("%d/%m/%Y %H:%M")

                    atualizar_multiplas({
                        "PARCELAS_RECEBER": parcelas_df,
                        "PEDIDOS": pedidos,
                    })
                    st.success("Parcela marcada como paga e Dashboard atualizado.")
                    st.rerun()


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
    st.markdown("### ✏️ Editar compra / fornecedor")

    if compras.empty:
        st.info("Nenhuma compra cadastrada para editar.")
    else:
        compras_edit = preparar_compras(compras)

        lista_compras = []
        for idx, row in compras_edit.iterrows():
            lista_compras.append(
                f"{row.get('NF', '')} | {row.get('FORNECEDOR', '')} | "
                f"{row.get('DATA', '')} | {formatar_moeda(row.get('VALOR TOTAL', 0))}"
            )

        compra_escolhida = st.selectbox(
            "Selecione a compra para editar",
            [""] + lista_compras,
            key="editar_compra_select"
        )

        if compra_escolhida:
            idx_compra = lista_compras.index(compra_escolhida)
            idx_real = compras_edit.index[idx_compra]

            st.info("Edite apenas o que estiver errado e depois clique em salvar.")

            e1, e2 = st.columns(2)
            nf_edit = e1.text_input("NF / Identificação", value=str(compras_edit.loc[idx_real, "NF"]))
            fornecedor_edit = e2.text_input("Fornecedor", value=str(compras_edit.loc[idx_real, "FORNECEDOR"]))

            e3, e4, e5 = st.columns(3)
            valor_total_edit = e3.number_input(
                "Valor total da compra",
                min_value=0.0,
                value=float(numero_para_float(compras_edit.loc[idx_real, "VALOR TOTAL"])),
                format="%.2f"
            )
            saldo_edit = e4.number_input(
                "Saldo a pagar",
                min_value=0.0,
                value=float(numero_para_float(compras_edit.loc[idx_real, "SALDO A PAGAR"])),
                format="%.2f"
            )
            valor_parcela_edit = e5.number_input(
                "Valor da parcela",
                min_value=0.0,
                value=float(numero_para_float(compras_edit.loc[idx_real, "VALOR PARCELA"])),
                format="%.2f"
            )

            e6, e7, e8 = st.columns(3)
            forma_opcoes = ["PIX", "Dinheiro", "Débito", "Crédito", "Boleto", "Fiado/Fornecedor", "Outro"]
            forma_atual = str(compras_edit.loc[idx_real, "FORMA PAGAMENTO"])
            forma_idx = forma_opcoes.index(forma_atual) if forma_atual in forma_opcoes else 0
            forma_edit = e6.selectbox("Forma de pagamento", forma_opcoes, index=forma_idx)

            parcelas_opcoes = ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"]
            parcelas_atual = str(compras_edit.loc[idx_real, "PARCELAS"])
            parcelas_idx = parcelas_opcoes.index(parcelas_atual) if parcelas_atual in parcelas_opcoes else 0
            parcelas_edit = e7.selectbox("Parcelas", parcelas_opcoes, index=parcelas_idx)

            status_opcoes = ["Pago", "Pendente"]
            status_atual = str(compras_edit.loc[idx_real, "STATUS"])
            status_idx = status_opcoes.index(status_atual) if status_atual in status_opcoes else 1
            status_edit = e8.selectbox("Status", status_opcoes, index=status_idx)

            venc_atual = pd.to_datetime(
                compras_edit.loc[idx_real, "PRIMEIRO VENCIMENTO"],
                dayfirst=True,
                errors="coerce"
            )
            if pd.isna(venc_atual):
                venc_atual = pd.Timestamp(hoje_brasil())

            venc_edit = st.date_input(
                "Primeiro vencimento",
                value=venc_atual.date(),
                format="DD/MM/YYYY",
                key="editar_venc_compra"
            )

            data_pg_atual = str(compras_edit.loc[idx_real, "DATA PAGAMENTO"])
            data_pg_edit = st.text_input(
                "Data de pagamento",
                value=data_pg_atual,
                help="Pode deixar em branco se ainda estiver pendente."
            )

            arquivo_pdf_edit = st.text_input(
                "Nome do arquivo PDF",
                value=str(compras_edit.loc[idx_real, "ARQUIVO PDF"])
            )

            recalcular = st.checkbox(
                "Recalcular valor da parcela e saldo automaticamente",
                value=False,
                help="Use quando alterar valor total, parcelas ou status."
            )

            if recalcular:
                valor_parcela_edit = calcular_valor_parcela(valor_total_edit, parcelas_edit)
                saldo_edit = 0.0 if status_pago(status_edit) else valor_total_edit
                if status_pago(status_edit) and not data_pg_edit.strip():
                    data_pg_edit = agora_brasil().strftime("%d/%m/%Y %H:%M")
                st.write("Valor da parcela recalculado:", formatar_moeda(valor_parcela_edit))
                st.write("Saldo recalculado:", formatar_moeda(saldo_edit))

            if st.button("💾 Salvar edição da compra/fornecedor"):
                compras_edit.loc[idx_real, "NF"] = nf_edit.strip()
                compras_edit.loc[idx_real, "FORNECEDOR"] = fornecedor_edit.strip()
                compras_edit.loc[idx_real, "VALOR TOTAL"] = round(valor_total_edit, 2)
                compras_edit.loc[idx_real, "ARQUIVO PDF"] = arquivo_pdf_edit.strip()
                compras_edit.loc[idx_real, "FORMA PAGAMENTO"] = forma_edit
                compras_edit.loc[idx_real, "PARCELAS"] = parcelas_edit
                compras_edit.loc[idx_real, "VALOR PARCELA"] = round(valor_parcela_edit, 2)
                compras_edit.loc[idx_real, "PRIMEIRO VENCIMENTO"] = pd.to_datetime(venc_edit).strftime("%d/%m/%Y")
                compras_edit.loc[idx_real, "STATUS"] = status_edit
                compras_edit.loc[idx_real, "DATA PAGAMENTO"] = data_pg_edit.strip()
                compras_edit.loc[idx_real, "SALDO A PAGAR"] = round(saldo_edit, 2)

                atualizar("COMPRAS", compras_edit)
                st.success("Compra/fornecedor atualizado com sucesso.")
                st.rerun()

            st.markdown("#### Edição em tabela")
            st.caption("Use esta tabela apenas se quiser corrigir várias linhas de uma vez.")
            tabela_editada = st.data_editor(compras_edit, use_container_width=True, num_rows="dynamic", key="compras_editor_completo")
            if st.button("💾 Salvar tabela completa de compras"):
                atualizar("COMPRAS", tabela_editada)
                st.success("Tabela de compras atualizada.")
                st.rerun()



    st.markdown("---")
    st.markdown("### ➕ Cadastrar fornecedor/conta manual sem nota")

    with st.expander("Abrir cadastro manual de fornecedor/conta a pagar"):
        st.info(
            "Use este campo para lançar fornecedores ou compras que não têm nota fiscal, "
            "como compras manuais, frete, Uber, embalagens, sacolas, etiquetas ou outras despesas."
        )

        mf1, mf2 = st.columns(2)
        manual_id = mf1.text_input(
            "Identificação da compra/conta",
            value=f"MANUAL-{agora_brasil().strftime('%Y%m%d%H%M')}",
            key="manual_fornecedor_id"
        )
        manual_fornecedor = mf2.text_input(
            "Fornecedor / Descrição",
            value="",
            placeholder="Ex.: Uber, Embalagens, Fornecedor sem nota, Sacolas",
            key="manual_fornecedor_nome"
        )

        mf3, mf4, mf5 = st.columns(3)
        manual_valor_total = mf3.number_input(
            "Valor total",
            min_value=0.0,
            value=0.0,
            format="%.2f",
            key="manual_fornecedor_valor"
        )
        manual_forma_pagamento = mf4.selectbox(
            "Forma de pagamento",
            ["PIX", "Dinheiro", "Débito", "Crédito", "Boleto", "Fiado/Fornecedor", "Outro"],
            key="manual_fornecedor_forma"
        )
        manual_parcelas = mf5.selectbox(
            "Parcelas",
            ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"],
            key="manual_fornecedor_parcelas"
        )

        mf6, mf7, mf8 = st.columns(3)
        manual_valor_parcela = calcular_valor_parcela(manual_valor_total, manual_parcelas)
        mf6.metric("Valor da parcela", formatar_moeda(manual_valor_parcela))

        manual_vencimento = mf7.date_input(
            "Primeiro vencimento",
            value=hoje_brasil(),
            format="DD/MM/YYYY",
            key="manual_fornecedor_vencimento"
        )

        manual_status = mf8.selectbox(
            "Status",
            ["Pendente", "Pago"],
            key="manual_fornecedor_status"
        )

        manual_obs = st.text_area(
            "Observação",
            placeholder="Ex.: Compra sem nota, valor de frete, embalagem, Uber, reposição de estoque...",
            key="manual_fornecedor_obs"
        )

        saldo_manual = 0.0 if status_pago(manual_status) else manual_valor_total
        data_pg_manual = agora_brasil().strftime("%d/%m/%Y %H:%M") if status_pago(manual_status) else ""

        if st.button("💾 Salvar fornecedor/conta manual", key="salvar_fornecedor_manual"):
            if not manual_fornecedor.strip():
                st.error("Informe o fornecedor ou descrição da conta.")
            elif manual_valor_total <= 0:
                st.error("Informe um valor maior que zero.")
            else:
                compras = preparar_compras(dados("COMPRAS"))

                nova_compra_manual = {
                    "NF": manual_id.strip() or f"MANUAL-{agora_brasil().strftime('%Y%m%d%H%M')}",
                    "DATA": agora_brasil().strftime("%d/%m/%Y %H:%M"),
                    "FORNECEDOR": manual_fornecedor.strip(),
                    "VALOR TOTAL": round(manual_valor_total, 2),
                    "ARQUIVO PDF": f"LANÇAMENTO MANUAL - {manual_obs.strip()}",
                    "FORMA PAGAMENTO": manual_forma_pagamento,
                    "PARCELAS": manual_parcelas,
                    "VALOR PARCELA": round(manual_valor_parcela, 2),
                    "PRIMEIRO VENCIMENTO": pd.to_datetime(manual_vencimento).strftime("%d/%m/%Y"),
                    "STATUS": manual_status,
                    "DATA PAGAMENTO": data_pg_manual,
                    "SALDO A PAGAR": round(saldo_manual, 2),
                }

                compras = pd.concat([compras, pd.DataFrame([nova_compra_manual])], ignore_index=True)
                atualizar("COMPRAS", compras)
                st.success("Fornecedor/conta manual cadastrado com sucesso.")
                st.rerun()



    st.markdown("---")
    st.markdown("### 📚 Todas as compras / fornecedores cadastrados")

    compras_todas = preparar_compras(dados("COMPRAS"))
    if compras_todas.empty:
        st.info("Ainda não há compras/fornecedores cadastrados.")
    else:
        st.caption("Aqui aparecem compras pagas e pendentes. A tabela abaixo de Contas a pagar mostra apenas as pendentes.")
        st.dataframe(compras_todas, use_container_width=True)


        st.markdown("### 🗑️ Excluir compra/fornecedor duplicado ou errado")

        opcoes_excluir = []
        idxs_excluir = []

        for idx, row in compras_todas.iterrows():
            texto_excluir = (
                f"{row.get('NF', '')} | "
                f"{row.get('FORNECEDOR', '')} | "
                f"{row.get('DATA', '')} | "
                f"{formatar_moeda(row.get('VALOR TOTAL', 0))} | "
                f"{row.get('STATUS', '')}"
            )
            opcoes_excluir.append(texto_excluir)
            idxs_excluir.append(idx)

        compra_excluir = st.selectbox(
            "Selecione a compra/fornecedor para excluir",
            [""] + opcoes_excluir,
            key="excluir_compra_fornecedor_select"
        )

        confirmar_excluir = st.checkbox(
            "Confirmo que desejo excluir esta compra/fornecedor",
            key="confirmar_excluir_compra_fornecedor"
        )

        if st.button("🗑️ Excluir compra/fornecedor selecionado", key="botao_excluir_compra_fornecedor"):
            if not compra_excluir:
                st.error("Selecione uma compra/fornecedor para excluir.")
            elif not confirmar_excluir:
                st.error("Marque a confirmação antes de excluir.")
            else:
                idx_real = idxs_excluir[opcoes_excluir.index(compra_excluir)]
                compras_todas = compras_todas.drop(index=idx_real).reset_index(drop=True)

                atualizar("COMPRAS", compras_todas)

                st.success("Compra/fornecedor excluído com sucesso.")
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
            calc_preco_key = f"calc_preco_{i}"
            calc_produto_anterior_key = f"calc_produto_anterior_{i}"

            if prod and st.session_state.get(calc_produto_anterior_key) != prod:
                st.session_state[calc_preco_key] = preco_padrao
                st.session_state[calc_produto_anterior_key] = prod

            if not prod:
                st.session_state[calc_produto_anterior_key] = ""

            preco = c3.number_input(
                "Preço unitário",
                min_value=0.0,
                value=float(st.session_state.get(calc_preco_key, preco_padrao)),
                format="%.2f",
                key=calc_preco_key
            )

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
    st.subheader("📑 Entrada de Compra / Nota Fiscal")

    modo_entrada = st.radio(
        "Como deseja lançar a compra?",
        ["📄 Ler nota fiscal PDF", "✍️ Lançar compra manual sem nota"],
        horizontal=True
    )

    fornecedor = st.text_input("Fornecedor padrão", "Fornecedor")
    margem = st.number_input("Margem para preço de venda (%)", min_value=0.0, value=120.0, format="%.2f")

    st.markdown("### Dados de pagamento da compra")
    cpg1, cpg2, cpg3 = st.columns(3)
    compra_pagamento = cpg1.selectbox("Forma de pagamento da compra", ["PIX", "Dinheiro", "Débito", "Crédito", "Boleto", "Fiado/Fornecedor", "Outro"])
    compra_parcelas = cpg2.selectbox("Parcelas da compra", ["À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"])
    compra_status = cpg3.selectbox("Status da compra", ["Pago", "Pendente"])
    primeiro_venc_compra = st.date_input("Primeiro vencimento da compra", value=hoje_brasil(), format="DD/MM/YYYY")

    def registrar_compra_no_estoque(df_entrada, identificacao, nome_arquivo):
        produtos = preparar_produtos(dados("PRODUTOS"))
        compras = safe_df(dados("COMPRAS"), COL_COMPRAS)

        for _, row in df_entrada.iterrows():
            nome = str(row.get("PRODUTO", "")).strip().upper()
            qtd = numero_para_int(row.get("QUANTIDADE", 0))
            custo = numero_para_float(row.get("CUSTO UNITÁRIO", 0))
            preco = numero_para_float(row.get("PREÇO VENDA", 0))
            forn = str(row.get("FORNECEDOR", fornecedor)).strip()
            categoria = str(row.get("CATEGORIA", "Cosméticos")).strip() or "Cosméticos"

            if not nome or qtd <= 0:
                continue

            match = produtos["PRODUTO"].astype(str).str.strip().str.upper() == nome if not produtos.empty else pd.Series(dtype=bool)

            if not produtos.empty and match.any():
                idx = produtos[match].index[0]
                produtos.loc[idx, "ESTOQUE"] = int(numero_para_int(produtos.loc[idx, "ESTOQUE"]) + qtd)
                produtos.loc[idx, "CUSTO"] = float(custo)
                produtos.loc[idx, "PREÇO VENDA"] = float(preco)
                produtos.loc[idx, "FORNECEDOR"] = forn
                produtos.loc[idx, "CATEGORIA"] = categoria
            else:
                novo = {
                    "CÓDIGO": novo_id("PROD", produtos, "CÓDIGO"),
                    "PRODUTO": nome,
                    "CATEGORIA": categoria,
                    "FORNECEDOR": forn,
                    "CUSTO": custo,
                    "PREÇO VENDA": preco,
                    "ESTOQUE": qtd,
                }
                produtos = pd.concat([produtos, pd.DataFrame([novo])], ignore_index=True)

        valor_total_compra = round(df_entrada["TOTAL"].apply(numero_para_float).sum(), 2)
        valor_parcela_compra = calcular_valor_parcela(valor_total_compra, compra_parcelas)
        saldo_compra = 0.0 if status_pago(compra_status) else valor_total_compra
        data_pg_compra = agora_brasil().strftime("%d/%m/%Y %H:%M") if status_pago(compra_status) else ""

        compras = pd.concat([compras, pd.DataFrame([{
            "NF": identificacao,
            "DATA": agora_brasil().strftime("%d/%m/%Y %H:%M"),
            "FORNECEDOR": fornecedor,
            "VALOR TOTAL": valor_total_compra,
            "ARQUIVO PDF": nome_arquivo,
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

    if modo_entrada == "📄 Ler nota fiscal PDF":
        arquivo = st.file_uploader("Envie o PDF da nota fiscal", type=["pdf"])

        if arquivo:
            df_nf = extrair_produtos_nfe_pdf(arquivo)
            if df_nf.empty:
                st.warning("Não consegui extrair produtos automaticamente.")
            else:
                st.success(f"Encontrei {len(df_nf)} produto(s). Confira antes de adicionar.")
                df_nf["FORNECEDOR"] = fornecedor
                df_nf["CATEGORIA"] = "Cosméticos"
                df_nf["PREÇO VENDA"] = df_nf["CUSTO UNITÁRIO"].apply(lambda x: round(numero_para_float(x) * (1 + margem / 100), 2))
                editado = st.data_editor(df_nf, use_container_width=True, num_rows="dynamic")

                if st.button("📦 Adicionar ao estoque"):
                    registrar_compra_no_estoque(
                        editado,
                        f"NF-{agora_brasil().strftime('%Y%m%d%H%M')}",
                        arquivo.name
                    )
                    st.success("Nota lançada e estoque atualizado.")
                    st.rerun()

    else:
        st.info("Use essa opção quando a compra veio sem nota fiscal ou quando quiser lançar tudo manualmente.")

        identificacao_compra = st.text_input(
            "Identificação da compra",
            value=f"MANUAL-{agora_brasil().strftime('%Y%m%d%H%M')}",
            help="Exemplo: Compra Brás, Compra fornecedor X, Sem Nota 01."
        )

        categoria_padrao = st.text_input("Categoria padrão dos produtos", "Cosméticos")

        st.markdown("### Produtos da compra manual")
        linhas_manual = []

        for i in range(1, 21):
            c1, c2, c3, c4 = st.columns([4, 1, 2, 2])
            nome_prod = c1.text_input(f"Produto {i}", key=f"manual_prod_{i}")
            qtd = c2.number_input("Qtd", min_value=0, value=0, step=1, key=f"manual_qtd_{i}")
            custo = c3.number_input("Custo unitário", min_value=0.0, value=0.0, format="%.2f", key=f"manual_custo_{i}")
            preco_sugerido = round(custo * (1 + margem / 100), 2) if custo > 0 else 0.0
            preco_venda = c4.number_input("Preço venda", min_value=0.0, value=preco_sugerido, format="%.2f", key=f"manual_preco_{i}")

            if nome_prod.strip() and qtd > 0:
                linhas_manual.append({
                    "PRODUTO": nome_prod.strip().upper(),
                    "QUANTIDADE": int(qtd),
                    "CUSTO UNITÁRIO": round(custo, 2),
                    "TOTAL": round(qtd * custo, 2),
                    "FORNECEDOR": fornecedor.strip(),
                    "PREÇO VENDA": round(preco_venda, 2),
                    "CATEGORIA": categoria_padrao.strip(),
                })

        if linhas_manual:
            df_manual = pd.DataFrame(linhas_manual)
            st.markdown("### Conferência da compra manual")
            st.dataframe(df_manual, use_container_width=True)
            st.metric("Total da compra manual", formatar_moeda(df_manual["TOTAL"].sum()))

            if st.button("📦 Registrar compra manual e adicionar ao estoque"):
                registrar_compra_no_estoque(
                    df_manual,
                    identificacao_compra.strip() or f"MANUAL-{agora_brasil().strftime('%Y%m%d%H%M')}",
                    "COMPRA MANUAL / SEM NOTA"
                )
                st.success("Compra manual registrada e estoque atualizado.")
                st.rerun()
        else:
            st.warning("Preencha pelo menos 1 produto com quantidade maior que zero.")



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
