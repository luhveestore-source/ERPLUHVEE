import streamlit as st
import pandas as pd
import pdfplumber
import re

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA E IDENTIDADE VISUAL (LUHVEES: PRETO, ROSA E LILÁS)
# ==============================================================================
st.set_page_config(page_title="ERP Luhvees", page_icon="🛍️", layout="wide")

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
        "Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total a Pagar", "Forma Pagamento", "Canal Venda", "Lucro Líquido"
    ])

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame([
        {"Nome": "Consumidor Geral", "WhatsApp": "-", "Cidade": "Físico"},
        {"Nome": "Maria Silva", "WhatsApp": "11999998888", "Cidade": "São Paulo"}
    ])

# ==============================================================================
# NOVO LEITOR DE DANFE INTELIGENTE E ANTI-ERROS
# ==============================================================================
def extrair_dados_danfe_blindado(texto_completo):
    produtos_extraidos = []
    # Normaliza quebras de linha e remove espaços extras
    linhas = [l.strip() for l in texto_completo.split("\n") if l.strip()]
    
    i = 0
    while i < len(linhas):
        linha_atual = linhas[i]
        
        # Identifica o início de um produto pelo código (Ex: EC0233, AP0059, LV001)
        match_codigo = re.search(r'^([A-Z]{2}\d{3,5}|[A-Z0-9]{4,10})\b', linha_atual)
        
        if match_codigo:
            codigo = match_codigo.group(1)
            # Remove o código do início para tentar pegar a descrição
            descricao = linha_atual.replace(codigo, "").strip()
            
            # Como a descrição pode quebrar em várias linhas, avançamos até achar os dados de valores
            qtd = 1
            custo_unit = 0.0
            dados_encontrados = False
            
            j = i
            while j < min(i + 4, len(linhas)):  # Procura nas próximas 4 linhas no máximo
                linha_analise = linhas[j]
                
                # Procura o padrão clássico de valores de DANFE: UN/PC/CX + Quantidade + Valor Unitário
                match_valores = re.search(r'\b(UN|PC|CX|KG)\s+([\d,\.]+)\s+([\d,\.]+)', linha_analise)
                if match_valores:
                    try:
                        qtd_str = match_valores.group(2)
                        custo_str = match_valores.group(3)
                        
                        qtd = int(float(qtd_str.replace('.', '').replace(',', '.')))
                        custo_unit = float(custo_str.replace('.', '').replace(',', '.'))
                        dados_encontrados = True
                        
                        # Limpa qualquer fragmento de valores que tenha ficado na descrição
                        descricao = re.sub(r'\b(UN|PC|CX|KG).*', '', descricao).strip()
                        break
                    except:
                        pass
                j += 1
            
            # Se não encontrou o formato com "UN", faz uma busca secundária por números na linha
            if not dados_encontrados:
                numeros = re.findall(r'[\d,\.]+', linha_atual)
                if len(numeros) >= 2:
                    try:
                        custo_unit = float(numeros[-1].replace('.', '').replace(',', '.'))
                        qtd = 1
                        dados_encontrados = True
                    except:
                        pass
            
            # Se conseguimos capturar um preço de custo válido, adicionamos o produto
            if dados_encontrados and custo_unit > 0:
                # Se a descrição ficou vazia por quebra de linha, puxa a linha seguinte
                if not descricao and i + 1 < len(linhas):
                    descricao = linhas[i+1]
                
                # Limpa sujeiras comuns de códigos fiscais na descrição
                descricao = re.sub(r'\d{8,9}.*', '', descricao).strip()
                
                produtos_extraidos.append({
                    "Código": codigo,
                    "Produto": descricao if descricao else f"Produto Código {codigo}",
                    "Custo Nota": custo_unit,
                    "Quantidade": max(1, qtd),
                    "Fornecedor": "Distribuidor"
                })
                # Avança o índice principal para onde os dados foram encontrados
                i = max(i, j)
        i += 1
        
    return pd.DataFrame(produtos_extraidos)

# ==============================================================================
# INTERFACE E NAVEGAÇÃO
# ==============================================================================
st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão Automatizada e Inteligente de Estoque</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Importar Nota Fiscal", "Visualizar Estoque", "Lançar Nova Venda", "Cadastro de Clientes"]
escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# --- 1. DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro da Sessão")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum()
    total_vendido = st.session_state.vendas["Total a Pagar"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Investimento Total em Estoque (c/ Uber)", f"R$ {total_investido:,.2f}")
    col2.metric("Faturamento de Vendas", f"R$ {total_vendido:,.2f}")
    col3.metric("Lucro Líquido Real", f"R$ {lucro_real:,.2f}")

    st.write("---")
    st.subheader("📋 Histórico Recente de Vendas")
    if st.session_state.vendas.empty:
        st.info("Nenhuma venda realizada nesta sessão.")
    else:
        st.dataframe(st.session_state.vendas, use_container_width=True)

# --- 2. IMPORTAR NOTA FISCAL (CÓDIGO INTEGRADO COM O NOVO LEITOR) ---
elif escolha == "Importar Nota Fiscal":
    st.subheader("📄 Entrada de Stock Automatizada")
    
    c1, c2 = st.columns(2)
    valor_uber = c1.number_input("Quanto pagou de Uber/Frete para esta compra? (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c2.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    
    arquivo_pdf = st.file_uploader("Anexe aqui o PDF da sua Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        try:
            with pdfplumber.open(arquivo_pdf) as pdf:
                paginas_texto = [page.extract_text() for page in pdf.pages if page.extract_text()]
                texto_nota = "\n".join(paginas_texto)
            
            # Executa o nosso novo leitor inteligente
            df_nota = extrair_dados_danfe_blindado(texto_nota)
            
            if not df_nota.empty:
                valor_total_nota_produtos = (df_nota["Custo Nota"] * df_nota["Quantidade"]).sum()
                st.success(f"Nota Fiscal processada com sucesso! Total em produtos: R$ {valor_total_nota_produtos:.2f}")
                st.info(f"O valor de R$ {valor_uber:.2f} do Uber será diluído proporcionalmente em cada um dos {len(df_nota)} itens.")
                
                with st.form("salvar_estoque_form"):
                    novos_produtos = []
                    for idx, row in df_nota.iterrows():
                        # Lógica financeira de rateio do Uber proporcional ao custo do produto
                        peso = (row["Custo Nota"] * row["Quantidade"]) / valor_total_nota_produtos if valor_total_nota_produtos > 0 else 0
                        uber_proporcional = (valor_uber * peso) / row["Quantidade"] if row["Quantidade"] > 0 else 0
                        custo_real_com_uber = row["Custo Nota"] + uber_proporcional
                        
                        st.write(f"📦 **{row['Produto']}**")
                        st.write(f"Qtd: {row['Quantidade']} un | Custo Nota: R$ {row['Custo Nota']:.2f} | **Custo Real c/ Uber: R$ {custo_real_com_uber:.2f}**")
                        
                        cx1, cx2, cx3 = st.columns(3)
                        preco_venda = cx1.number_input(f"Preço de Venda Final (R$)", min_value=0.0, value=custo_real_com_uber * 2, key=f"pv_{idx}")
                        taxa_canal = cx2.number_input(f"Taxa Canal/Yampi (R$)", min_value=0.0, value=preco_venda * 0.06, key=f"tx_{idx}")
                        embalagem = cx3.number_input(f"Custo Embalagem (R$)", min_value=0.0, value=0.50, key=f"emb_{idx}")
                        
                        lucro_unitario = preco_venda - custo_real_com_uber - taxa_canal - packaging_val := embalagem
                        st.markdown(f"<span style='color:#da70d6;'>Comissão líquida estimada por unidade: R$ {lucro_unitario:.2f}</span>", unsafe_allow_html=True)
                        st.write("---")
                        
                        novos_produtos.append({
                            "Código": row["Código"], "Produto": row["Produto"], "Categoria": "Cosméticos",
                            "Fornecedor": fornecedor_input, "Custo Nota": row["Custo Nota"], "Custo Real": custo_real_com_uber,
                            "Preço Venda": preco_venda, "Taxa/Canal": taxa_canal, "Embalagem": packaging_val, "Estoque Atual": row["Quantidade"]
                        })
                    
                    if st.form_submit_button("Confirmar e Inserir no Estoque Geral 🚀"):
                        st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(novos_produtos)], ignore_index=True)
                        st.success("Tudo pronto! Estoque alimentado com os custos reais atualizados.")
            else:
                st.warning("Não conseguimos extrair os produtos estruturados deste PDF. Verifique se o arquivo está correto ou tente copiar o texto manualmente.")
        except Exception as e:
            st.error(f"Erro crítico ao ler o ficheiro: {e}. Certifique-se de que o PDF é uma cópia digital limpa.")

# --- 3. VISUALIZAR ESTOQUE ---
elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Inventário de Produtos Disponíveis")
    df_vis = st.session_state.estoque.copy()
    df_vis["Lucro Unit."] = df_vis["Preço Venda"] - df_vis["Custo Real"] - df_vis["Taxa/Canal"] - df_vis["Embalagem"]
    df_vis["Margem Líquida (%)"] = (df_vis["Lucro Unit."] / df_vis["Preço Venda"]) * 100
    st.dataframe(df_vis, use_container_width=True)

# --- 4. LANÇAR NOVA VENDA ---
elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Ponto de Venda / Registro de Pedidos")
    
    with st.form("venda_form"):
        cliente = st.selectbox("Quem comprou?", st.session_state.clientes["Nome"].tolist())
        produto_nome = st.selectbox("Qual o produto vendido?", st.session_state.estoque["Produto"].tolist())
        qtd = st.number_input("Quantidade vendida", min_value=1, value=1)
        
        canal = st.selectbox("Canal de Venda", ["Yampi", "WhatsApp", "Instagram", "Shopee", "Loja Física (Pessoalmente)"])
        forma_pagamento = st.selectbox("Forma de Pagamento Utilizada", ["PIX", "Dinheiro", "Cartão de Crédito", "Cartão de Débito", "Link de Pagamento"])
        
        if st.form_submit_button("Concluir Transação 🎯"):
            prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
            
            if prod_info["Estoque Atual"] < qtd:
                st.error(f"Erro: Stock insuficiente! Possui apenas {prod_info['Estoque Atual']} unidades deste cosmético.")
            else:
                total_pagar = qtd * prod_info["Preço Venda"]
                custo_total = qtd * prod_info["Custo Real"]
                lucro_total = total_pagar - custo_total - (prod_info["Taxa/Canal"] * qtd) - (prod_info["Embalagem"] * qtd)
                
                nova_venda = {
                    "Data": pd.Timestamp.now().strftime("%d/%m/%Y"), "Cliente": cliente, "Produto": produto_nome, "Qtde": qtd,
                    "Preço Unit.": prod_info["Preço Venda"], "Total a Pagar": total_pagar, "Forma Pagamento": forma_pagamento,
                    "Canal Venda": canal, "Lucro Líquido": lucro_total
                }
                st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
                st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
                st.success(f"Venda efetuada! Valor de R$ {total_pagar:.2f} registado com sucesso para a conta de {cliente}.")

# --- 5. CADASTRO DE CLIENTES ---
elif escolha == "Cadastro de Clientes":
    st.subheader("👥 Gestão de Clientes da Marca")
    with st.form("form_cliente"):
        nome = st.text_input("Nome do Cliente")
        whatsapp = st.text_input("Contacto / WhatsApp")
        cidade = st.text_input("Cidade / Localidade")
        if st.form_submit_button("Gravar Registo"):
            if nome:
                st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([{"Nome": nome, "WhatsApp": whatsapp, "Cidade": cidade}])], ignore_index=True)
                st.success(f"Cliente {nome} guardado na base de dados!")
    st.dataframe(st.session_state.clientes, use_container_width=True)
