import streamlit as st
import pandas as pd
import pdfplumber
import re

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA E IDENTIDADE VISUAL (LUHVEES: PRETO, ROSA E LILÁS)
# ==============================================================================
st.set_page_config(page_title="ERP Luhvees Stores", page_icon="🛍️", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #0b0b0d; color: #e0e0e6; }
    h1, h2, h3 { color: #ffffff !important; font-family: 'Arial', sans-serif; }
    .brand-title { color: #ff007f; font-weight: bold; letter-spacing: 1px; }
    .brand-subtitle { color: #da70d6; font-size: 14px; margin-top: -15px; margin-bottom: 25px; }
    div.stButton > button:first-child {
        background-color: #ff007f; color: white; border: none; border-radius: 6px;
        padding: 10px 24px; font-weight: bold; transition: all 0.3s ease;
    }
    div.stButton > button:first-child:hover { background-color: #da70d6; color: white; border: none; }
    div[data-testid="stMetricValue"] { color: #da70d6 !important; }
    
    /* Layout profissional de impressão de etiquetas (Fundo branco e texto preto) */
    @media print {
        body * { visibility: hidden; }
        .print-section, .print-section * { visibility: visible; }
        .print-section { position: absolute; left: 0; top: 0; width: 100%; background: white !important; }
    }
    .etiqueta-box {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 2px dashed #000000 !important;
        padding: 15px;
        border-radius: 4px;
        text-align: center;
        margin-bottom: 15px;
        font-family: 'Arial', sans-serif;
    }
    .etiqueta-brand { font-size: 16px; font-weight: bold; text-transform: uppercase; margin-bottom: 5px; color: #000000 !important; }
    .etiqueta-prod { font-size: 11px; max-height: 35px; overflow: hidden; margin-bottom: 8px; line-height: 1.2; color: #333333 !important; }
    .etiqueta-price { font-size: 22px; font-weight: bold; color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# INICIALIZAÇÃO DE DADOS EM MEMÓRIA
# ==============================================================================
if 'estoque' not in st.session_state:
    st.session_state.estoque = pd.DataFrame([
        {"Código": "LV038", "Produto": "Hidratante Corporal Babasoul Tutti-Frutti 240ml Soul", "Categoria": "Cosméticos", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 11.40, "Custo Real": 12.13, "Preço Venda": 21.90, "Taxa/Canal": 1.31, "Embalagem": 0.50, "Estoque Atual": 12},
        {"Código": "LV039", "Produto": "Kit Capilar 3 Itens 312 VIP Charmelle", "Categoria": "Cosméticos", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 25.70, "Custo Real": 27.35, "Preço Venda": 39.90, "Taxa/Canal": 2.39, "Embalagem": 0.50, "Estoque Atual": 6}
    ])

if 'vendas' not in st.session_state:
    st.session_state.vendas = pd.DataFrame(columns=[
        "Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total Venda", "Parcelas", "Forma Pagamento", "Canal Venda", "Lucro Líquido"
    ])

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame([
        {"Nome": "Consumidor Geral", "WhatsApp": "-", "Cidade": "Físico"},
        {"Nome": "Maria Silva", "WhatsApp": "11999998888", "Cidade": "São Paulo"}
    ])

# ==============================================================================
# LEITOR BLINDADO E CORRIGIDO DE NOTA FISCAL
# ==============================================================================
def extrair_produtos_da_nota_luhvees(pdf_file):
    produtos = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            palavras = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not palavras:
                continue
                
            linhas_coordenadas = {}
            for p in palavras:
                top_arredondado = round(p['top'], 1)
                found = False
                for t in linhas_coordenadas.keys():
                    if abs(t - top_arredondado) < 3.5:
                        linhas_coordenadas[t].append(p)
                        found = True
                        break
                if not found:
                    linhas_coordenadas[top_arredondado] = [p]
            
            linhas_ordenadas = [linhas_coordenadas[t] for t in sorted(linhas_coordenadas.keys())]
            
            texto_linhas_limpas = []
            for linha in linhas_ordenadas:
                linha_ordenada = sorted(linha, key=lambda x: x['x0'])
                texto_linha = " ".join([p['text'] for p in linha_ordenada]).strip()
                texto_linhas_limpas.append(texto_linha)
            
            area_de_produtos = False
            
            i = 0
            while i < len(texto_linhas_limpas):
                linha = texto_linhas_limpas[i].upper()
                
                # Filtro rígido para ignorar o canhoto de recebimento do topo da nota
                if "RECEBEMOS" in linha or "CONSTATES NA NOTA" in linha or "IDENTIFICAÇÃO DO EMITENTE" in linha or "RECEBIMENTO" in linha:
                    i += 1
                    continue
                
                if "DADOS DO PRODUTO" in linha or "DADOS DOS PRODUTOS" in linha or "PROD./SERV." in linha or "CÓD. PROD." in linha:
                    area_de_produtos = True
                    i += 1
                    continue
                
                if "DADOS ADICIONAIS" in linha or "INFORMAÇÕES COMPLEMENTARES" in linha or "CÁLCULO DO ISSQN" in linha:
                    area_de_produtos = False
                    break
                
                if area_de_produtos:
                    match_prod = re.search(r'^([A-Z0-9\-]{3,15})\s+(.+)$', texto_linhas_limpas[i])
                    if match_prod:
                        codigo = match_prod.group(1)
                        resto = match_prod.group(2)
                        
                        if codigo in ["NCM", "CFOP", "VALOR", "QUANT", "UN", "ST", "TOTAL", "CÓDIGO", "ITEM", "CNPJ"]:
                            i += 1
                            continue
                        
                        descricao_completa = resto
                        while i + 1 < len(texto_linhas_limpas) and not re.search(r'^([A-Z0-9\-]{3,15})\s+', texto_linhas_limpas[i+1]) and len(texto_linhas_limpas[i+1]) > 5:
                            linha_seg = texto_linhas_limpas[i+1]
                            if "UN" in linha_seg or "PC" in linha_seg or "CX" in linha_seg or "," in linha_seg:
                                break
                            descricao_completa += " " + linha_seg
                            i += 1
                        
                        qtd_encontrada = 1
                        preco_sugerido = 10.00
                        
                        for k in range(i, min(i + 3, len(texto_linhas_limpas))):
                            linha_val = texto_linhas_limpas[k]
                            match_valores = re.search(r'\b(UN|PC|CX|KG)\s+([\d,\.]+)\s+([\d,\.]+)', linha_val.upper())
                            if match_valores:
                                try:
                                    qtd_encontrada = int(float(match_valores.group(2).replace('.', '').replace(',', '.')))
                                    preco_sugerido = float(match_valores.group(3).replace('.', '').replace(',', '.'))
                                    break
                                except:
                                    pass
                        
                        descricao_completa = re.sub(r'\b(UN|PC|CX|KG).*', '', descricao_completa)
                        descricao_completa = re.sub(r'\b\d{8}\b.*', '', descricao_completa).strip()
                        
                        if len(descricao_completa) > 4:
                            produtos.append({
                                "Código": codigo,
                                "Produto": descricao_completa.upper(),
                                "Custo Nota": preco_sugerido if preco_sugerido < 1500 else 10.00,
                                "Quantidade": qtd_encontrada if qtd_encontrada < 500 else 1
                            })
                i += 1
                
    return pd.DataFrame(produtos)

# ==============================================================================
# INTERFACE E NAVEGAÇÃO COMPLETA
# ==============================================================================
st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão Automatizada e Inteligente de Estoque</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Importar Nota Fiscal", "Visualizar Estoque", "Gerador de Etiquetas", "Lançar Nova Venda", "Cadastro de Clientes"]
escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# --- 1. DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro da Sessão")
    total_investido = 0.0
    if not st.session_state.estoque.empty:
        total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum()
        
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    col1, col2, col3 = st.columns(3
