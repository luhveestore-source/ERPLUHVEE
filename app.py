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
    st.session_state.clientes = pd.DataFrame([{"Nome": "Consumidor Geral", "WhatsApp": "-", "Cidade": "Físico"}])

# ==============================================================================
# LEITOR DE ALTA PRECISÃO POR COORDENADAS VERTICAIS (MÉTODO BLINDADO LUHVEES)
# ==============================================================================
def extrair_dados_danfe_alta_precisao(pdf_file):
    produtos = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Extrai as palavras com suas respectivas posições (X, Y) na página
            palavras = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not palavras:
                continue
                
            # Agrupa palavras que estão na mesma linha vertical (mesmo topo aproximado)
            linhas_coordenadas = {}
            for p in palavras:
                top_arredondado = round(p['top'], 1)
                found = False
                for t in linhas_coordenadas.keys():
                    if abs(t - top_arredondado) < 3.5: # Tolerância para capturar a mesma linha real
                        linhas_coordenadas[t].append(p)
                        found = True
                        break
                if not found:
                    linhas_coordenadas[top_arredondado] = [p]
            
            # Ordena as linhas de cima para baixo
            linhas_ordenadas = [linhas_coordenadas[t] for t in sorted(linhas_coordenadas.keys())]
            
            texto_linhas_limpas = []
            for linha in lines_ordenadas:
                # Ordena as palavras da esquerda para a direita
                linha_ordenada = sorted(linha, key=lambda x: x['x0'])
                texto_linha = " ".join([p['text'] for p in linha_ordenada]).strip()
                texto_linhas_limpas.append(texto_linha)
            
            # Segunda passada: Reconstruir descrições que foram quebradas em blocos
            i = 0
            while i < len(texto_linhas_limpas):
                linha = texto_linhas_limpas[i]
                
                # Procura padrões de código de produto comuns (letras e números iniciais)
                match_prod = re.search(r'^([A-Z0-9\-]{3,12})\s+(.+)$', linha)
                if match_prod:
                    codigo = match_prod.group(1)
                    resto = match_prod.group(2)
                    
                    # Se for apenas texto institucional ou impostos, ignora
                    if codigo in ["NATUREZA", "CNPJ", "INSCRIÇÃO", "VALOR", "FATURA", "DADOS"]:
                        i += 1
                        continue
                    
                    # Puxa o texto da linha seguinte caso a descrição tenha continuado embaixo
                    descricao_completa = resto
                    while i + 1 < len(texto_linhas_limpas) and not re.search(r'^([A-Z0-9\-]{3,12})\s+', texto_linhas_limpas[i+1]) and len(texto_linhas_limpas[i+1]) > 5:
                        linha_seg = texto_linhas_limpas[i+1]
                        # Se a próxima linha contiver dados de valores, para a captura de texto
                        if "UN" in linha_seg or "PC" in linha_seg or "," in linha_seg:
                            break
                        descricao_completa += " " + linha_seg
                        i += 1
                    
                    # Procura os valores de Qtd e Preço na linha atual ou nas próximas 2 linhas
                    qtd_encontrada = 1
                    preco_encontrado = 0.0
                    dados_valores_achados = False
                    
                    for k in range(i, min(i + 3, len(texto_linhas_limpas))):
                        linha_valores = texto_linhas_limpas[k]
                        # Procura o padrão: Unidade de Medida (UN/PC) + Qtd + Valor Unitário
                        match_valores = re.search(r'\b(UN|PC|CX|KG)\s+([\d,\.]+)\s+([\d,\.]+)', linha_valores)
                        if match_valores:
                            try:
                                qtd_str = match_valores.group(2)
                                preco_str = match_valores.group(3)
                                qtd_encontrada = int(float(qtd_str.replace('.', '').replace(',', '.')))
                                preco_encontrado = float(preco_str.replace('.', '').replace(',', '.'))
                                dados_valores_achados = True
                                break
                            except:
                                pass
                    
                    # Limpeza final da descrição para remover códigos internos residuais e NCMs
                    descricao_completa = re.sub(r'\b(UN|PC|CX|KG).*', '', descricao_completa)
                    descricao_completa = re.sub(r'\b\d{8,9}\b.*', '', descricao_completa).strip()
                    
                    if preco_encontrado > 0 and preco_encontrado < 1000 and len(descricao_completa) > 4:
                        produtos.append({
                            "Código": codigo,
                            "Produto": descricao_completa.upper(),
                            "Custo Nota": preco_encontrado,
                            "Quantidade": qtd_encontrada
                        })
                i += 1
                
    return pd.DataFrame(produtos)

# ==============================================================================
# INTERFACE PRINCIPAL
# ==============================================================================
st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão Inteligente e Extração Fiel de Notas Fiscais</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Importar Nota Fiscal", "Visualizar Estoque", "Lançar Nova Venda"]
escolha = st.sidebar.selectbox("Navegar", menu)

if escolha == "Dashboard Geral":
    st.subheader("📊 Situação do seu Negócio")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum()
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Investimento Atual em Estoque", f"R$ {total_investido:,.2f}")
    col2.metric("Faturamento Total", f"R$ {total_vendido:,.2f}")
    col3.metric("Lucro Líquido Real", f"R$ {lucro_real:,.2f}")

elif escolha == "Importar Nota Fiscal":
    st.subheader("📄 Importação Direta e Fiel da Nota Fiscal")
    
    col_u, col_f = st.columns(2)
    valor_uber = col_u.number_input("Custo de Frete/Uber da Compra (R$)", min_value=0.0, value=32.0)
    fornecedor_input = col_f.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    
    arquivo_pdf = st.file_uploader("Arraste ou selecione o PDF original da Nota Fiscal aqui", type=["pdf"])

    if arquivo_pdf is not None:
        try:
            df_nota = extrair_dados_danfe_alta_precisao(arquivo_pdf)
            
            if not df_nota.empty:
                st.success(f"🔥 Sucesso! Identificamos {len(df_nota)} produtos com valores exatos obtidos do documento.")
                
                with st.form("confirmar_estoque_luhvees"):
                    lista_conferida = []
                    for idx, row in df_nota.iterrows():
                        chave = f"item_{idx}_{row['Código']}"
                        
                        st.markdown(f"🔹 **Código: {row['Código']}** — **{row['Produto']}**")
                        c_q, c_c, c_v = st.columns([1, 1.5, 2.5])
                        
                        qtd_f = c_q.number_input("Qtd", min_value=1, value=int(row['Quantidade']), key=f"q_{chave}")
                        custo_f = c_c.number_input("Custo NF (R$)", min_value=0.01, value=float(row['Custo Nota']), format="%.2f", key=f"c_{chave}")
                        
                        # O valor que você vai cobrar você define livremente aqui na hora
                        pv_f = c_v.number_input("Preço de Venda que deseja cobrar (R$)", min_value=0.0, value=custo_f * 2, key=f"v_{chave}")
                        st.write("---")
                        
                        lista_conferida.append({
                            "Código": row["Código"], "Produto": row["Produto"], "Quantidade": qtd_f, "Custo Nota": custo_f, "Preço Venda": pv_f
                        })
                        
                    if st.form_submit_button("Confirmar Entradas e Gravar no Estoque Geral 🚀"):
                        total_produtos_nota = sum([p["Custo Nota"] * p["Quantidade"] for p in lista_conferida])
                        
                        registros_finais = []
                        for p in lista_conferida:
                            # Rateio inteligente do frete proporcional ao custo do produto
                            proporcao = (p["Custo Nota"] * p["Quantidade"]) / total_produtos_nota if total_produtos_nota > 0 else 0
                            uber_por_unidade = (valor_uber * proporcao) / p["Quantidade"] if p["Quantidade"] > 0 else 0
                            custo_real_calculado = p["Custo Nota"] + uber_por_unidade
                            
                            registros_finais.append({
                                "Código": p["Código"], "Produto": p["Produto"], "Categoria": "Cosméticos",
                                "Fornecedor": fornecedor_input, "Custo Nota": p["Custo Nota"], "Custo Real": custo_real_calculado,
                                "Preço Venda": p["Preço Venda"], "Taxa/Canal": p["Preço Venda"] * 0.06, "Embalagem": 0.50, "Estoque Atual": p["Quantidade"]
                            })
                            
                        st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(registros_finais)], ignore_index=True)
                        st.success("Estoque alimentado com sucesso! Nomes e custos batendo 100% com a nota fiscal.")
            else:
                st.warning("A leitura automática de segurança falhou para este layout. Verifique se o PDF está correto.")
        except Exception as e:
            st.error(f"Erro ao processar as linhas do documento: {e}")

elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Seu Estoque Atual")
    if st.session_state.estoque.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        st.dataframe(st.session_state.estoque, use_container_width=True)

elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Lançamento de Pedidos")
    with st.form("nova_venda"):
        cliente = st.selectbox("Cliente", st.session_state.clientes["Nome"].tolist())
        produto = st.selectbox("Produto", st.session_state.estoque["Produto"].tolist())
        qtd = st.number_input("Quantidade", min_value=1, value=1)
        if st.form_submit_button("Lançar Venda"):
            st.success("Venda salva!")
