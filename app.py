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
        "Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total Venda", "Parcelas", "Forma Pagamento", "Canal Venda", "Lucro Líquido"
    ])

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame([
        {"Nome": "Consumidor Geral", "WhatsApp": "-", "Cidade": "Físico"},
        {"Nome": "Maria Silva", "WhatsApp": "11999998888", "Cidade": "São Paulo"}
    ])

# ==============================================================================
# LEITOR DE DANFE REVISADO
# ==============================================================================
def extrair_dados_danfe_blindado(texto_completo):
    produtos_extraidos = []
    linhas = [l.strip() for l in texto_completo.split("\n") if l.strip()]
    
    i = 0
    while i < len(linhas):
        linha_atual = linhas[i]
        # Pega padrões comuns de códigos de produtos (letras seguidas de números ou sequências alfanuméricas)
        match_codigo = re.search(r'^([A-Z]{2,4}\d{3,5}|[A-Z0-9]{4,10})\b', linha_atual)
        
        if match_codigo:
            codigo = match_codigo.group(1)
            descricao = linha_atual.replace(codigo, "").strip()
            
            qtd = 1
            custo_unit = 0.0
            dados_encontrados = False
            
            # Analisa as linhas imediatamente abaixo procurando os valores de Qtde e Preço
            j = i
            while j < min(i + 4, len(linhas)):
                linha_analise = linhas[j]
                match_valores = re.search(r'\b(UN|PC|CX|KG)\s+([\d,\.]+)\s+([\d,\.]+)', linha_analise)
                if match_valores:
                    try:
                        qtd_str = match_valores.group(2)
                        custo_str = match_valores.group(3)
                        qtd = int(float(qtd_str.replace('.', '').replace(',', '.')))
                        custo_unit = float(custo_str.replace('.', '').replace(',', '.'))
                        dados_encontrados = True
                        descricao = re.sub(r'\b(UN|PC|CX|KG).*', '', descricao).strip()
                        break
                    except:
                        pass
                j += 1
            
            if not dados_encontrados or custo_unit <= 0:
                # Procura valores decimais na própria linha como alternativa
                numeros = re.findall(r'\b\d+,\d{2}\b', linha_atual)
                if numeros:
                    try:
                        custo_unit = float(numeros[0].replace(',', '.'))
                        dados_encontrados = True
                    except:
                        custo_unit = 5.00 # Valor padrão amigável caso falhe
                else:
                    custo_unit = 5.00
            
            if custo_unit > 2000: # Proteção contra capturar o NCM ou impostos por erro
                custo_unit = 5.00
                
            if codigo:
                if not descricao and i + 1 < len(linhas):
                    descricao = linhas[i+1]
                descricao = re.sub(r'\d{8,9}.*', '', descricao).strip()
                produtos_extraidos.append({
                    "Código": codigo, 
                    "Produto": descricao if descricao else f"Produto Código {codigo}",
                    "Custo Nota": custo_unit, 
                    "Quantidade": max(1, qtd)
                })
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
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
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

# --- 2. IMPORTAR NOTA FISCAL (COMPLETAMENTE ANTI-ERROS) ---
elif escolha == "Importar Nota Fiscal":
    st.subheader("📄 Entrada de Estoque Automatizada")
    c1, c2 = st.columns(2)
    valor_uber = c1.number_input("Quanto pagou de Uber/Frete para esta compra? (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c2.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    arquivo_pdf = st.file_uploader("Anexe aqui o PDF da sua Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        try:
            with pdfplumber.open(arquivo_pdf) as pdf:
                paginas_texto = [page.extract_text() for page in pdf.pages if page.extract_text()]
                texto_nota = "\n".join(paginas_texto)
            df_nota = extrair_dados_danfe_blindado(texto_nota)
            
            if not df_nota.empty:
                st.info("💡 Confira e mude os valores se necessário nas caixinhas abaixo antes de clicar no botão final!")
                
                with st.form("salvar_estoque_form"):
                    novos_produtos = []
                    for idx, row in df_nota.iterrows():
                        # Gerando chaves 100% únicas mesclando o índice com o código do item
                        chave_unica = f"{idx}_{row['Código']}"
                        
                        st.markdown(f"📦 **Item {idx+1}: Código {row['Código']}** - *{row['Produto']}*")
                        col_qtd, col_custo_nf, col_pv, col_tx, col_emb = st.columns(5)
                        
                        qtd_real = col_qtd.number_input(f"Qtd Comprada", min_value=1, value=int(row["Quantidade"]), key=f"qtd_{chave_unica}")
                        custo_nota_real = col_custo_nf.number_input(f"Custo na Nota (R$)", min_value=0.01, value=float(row["Custo Nota"]), step=0.50, key=f"cn_{chave_unica}")
                        
                        # Valores estimados automáticos baseados no que você digitar
                        preco_venda = col_pv.number_input(f"Preço de Venda (R$)", min_value=0.0, value=custo_nota_real * 2, key=f"pv_{chave_unica}")
                        taxa_canal = col_tx.number_input(f"Taxa Canal (R$)", min_value=0.0, value=preco_venda * 0.06, key=f"tx_{chave_unica}")
                        embalagem = col_emb.number_input(f"Custo Embalagem (R$)", min_value=0.0, value=0.50, key=f"emb_{chave_unica}")
                        
                        st.write("---")
                        
                        novos_produtos.append({
                            "Código": row["Código"], "Produto": row["Produto"], "Quantidade": qtd_real, "Custo Nota": custo_nota_real,
                            "Preço Venda": preco_venda, "Taxa/Canal": taxa_canal, "Embalagem": embalagem
                        })
                        
                    if st.form_submit_button("Confirmar e Inserir no Estoque Geral 🚀"):
                        total_nota_corrigido = sum([p["Custo Nota"] * p["Quantidade"] for p in novos_produtos])
                        
                        produtos_finais_inserir = []
                        for p in novos_produtos:
                            peso = (p["Custo Nota"] * p["Quantidade"]) / total_nota_corrigido if total_nota_corrigido > 0 else 0
                            uber_proporcional = (valor_uber * peso) / p["Quantidade"] if p["Quantidade"] > 0 else 0
                            custo_real_com_uber = p["Custo Nota"] + uber_proporcional
                            
                            produtos_finais_inserir.append({
                                "Código": p["Código"], "Produto": p["Produto"], "Categoria": "Cosméticos",
                                "Fornecedor": fornecedor_input, "Custo Nota": p["Custo Nota"], "Custo Real": custo_real_com_uber,
                                "Preço Venda": p["Preço Venda"], "Taxa/Canal": p["Taxa/Canal"], "Embalagem": p["Embalagem"], "Estoque Atual": p["Quantidade"]
                            })
                            
                        st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(produtos_finais_inserir)], ignore_index=True)
                        st.success("Tudo pronto! O estoque foi atualizado com sucesso.")
            else:
                st.warning("Não conseguimos localizar a lista de produtos no formato automático desse PDF.")
        except Exception as e:
            st.error(f"Erro ao processar o arquivo: {e}")

# --- 3. VISUALIZAR ESTOQUE ---
elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Inventário de Produtos Disponíveis")
    if st.session_state.estoque.empty:
        st.info("Estoque vazio.")
    else:
        df_vis = st.session_state.estoque.copy()
        df_vis["Lucro Unit."] = df_vis["Preço Venda"] - df_vis["Custo Real"] - df_vis["Taxa/Canal"] - df_vis["Embalagem"]
        df_vis["Margem Líquida (%)"] = (df_vis["Lucro Unit."] / df_vis["Preço Venda"]) * 100
        st.dataframe(df_vis, use_container_width=True)

# --- 4. LANÇAR NOVA VENDA ---
elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Ponto de Venda / Registro de Pedidos")
    
    with st.expander("➕ Atalho: Cadastrar Novo Cliente sem sair desta tela"):
        fast_nome = st.text_input("Nome do Cliente", key="fast_nome")
        fast_whats = st.text_input("WhatsApp", key="fast_whats")
        fast_cid = st.text_input("Cidade", key="fast_cid")
        if st.button("Cadastrar Cliente e Atualizar Lista 🔄"):
            if fast_nome:
                st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([{"Nome": fast_nome, "WhatsApp": fast_whats, "Cidade": fast_cid}])], ignore_index=True)
                st.success(f"Cliente '{fast_nome}' adicionado com sucesso! Já pode selecioná-lo no campo abaixo.")

    st.write("---")
    
    with st.form("venda_form"):
        cliente = st.selectbox("Quem comprou? (Selecione na lista)", st.session_state.clientes["Nome"].tolist())
        produto_nome = st.selectbox("Qual o produto vendido?", st.session_state.estoque["Produto"].tolist())
        qtd = st.number_input("Quantidade vendida", min_value=1, value=1)
        
        preco_sugerido = 0.0
        if not st.session_state.estoque.empty and produto_nome in st.session_state.estoque["Produto"].tolist():
            preco_sugerido = float(st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]["Preço Venda"])
        
        valor_total_venda = st.number_input("Valor Total da Venda (R$)", min_value=0.0, value=preco_sugerido * qtd, step=1.0)
        parcelas = st.selectbox("Quantidade de Parcelas", ["1x (À vista)", "2x", "3x", "4x", "5x", "6x"])
        
        canal = st.selectbox("Canal de Venda", ["Yampi", "WhatsApp", "Instagram", "Shopee", "Loja Física (Pessoalmente)"])
        forma_pagamento = st.selectbox("Forma de Pagamento Utilizada", ["PIX", "Dinheiro", "Cartão de Crédito", "Cartão de Débito", "Link de Pagamento"])
        
        if st.form_submit_button("Concluir Transação 🎯"):
            prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
            
            if prod_info["Estoque Atual"] < qtd:
                st.error(f"Erro: Estoque insuficiente! Possui apenas {prod_info['Estoque Atual']} unidades.")
            else:
                custo_total = qtd * prod_info["Custo Real"]
                lucro_total = valor_total_venda - custo_total - (prod_info["Taxa/Canal"] * qtd) - (prod_info["Embalagem"] * qtd)
                
                nova_venda = {
                    "Data": pd.Timestamp.now().strftime("%d/%m/%Y"), "Cliente": cliente, "Produto": produto_nome, "Qtde": qtd,
                    "Preço Unit.": valor_total_venda / qtd if qtd > 0 else 0, "Total Venda": valor_total_venda, "Parcelas": parcelas,
                    "Forma Pagamento": forma_pagamento, "Canal Venda": canal, "Lucro Líquido": lucro_total
                }
                st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
                st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
                st.success(f"Venda efetuada! Valor de R$ {valor_total_venda:.2f} registrado com sucesso para {cliente}.")

# --- 5. CADASTRO DE CLIENTES ---
elif escolha == "Cadastro de Clientes":
    st.subheader("👥 Gestão de Clientes da Marca")
    
    st.markdown("### 📝 Adicionar Novo Cliente")
    nome = st.text_input("Nome Completo do Cliente", placeholder="Ex: Luana Avelino")
    whatsapp = st.text_input("Número do WhatsApp / Contato", placeholder="Ex: 11999999999")
    cidade = st.text_input("Cidade / Região", placeholder="Ex: São Paulo - SP")
    
    if st.button("Gravar Registro do Cliente 💾"):
        if nome:
            st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([{"Nome": nome, "WhatsApp": whatsapp, "Cidade": city := cidade}])], ignore_index=True)
            st.success(f"Sucesso! O cliente '{nome}' foi salvo na base de dados.")
        else:
            st.error("Por favor, preencha pelo menos o campo 'Nome' para conseguir salvar.")
            
    st.write("---")
    st.markdown("### 📋 Clientes Cadastrados")
    st.dataframe(st.session_state.clientes, use_container_width=True)
