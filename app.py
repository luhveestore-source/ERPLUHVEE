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
# LEITOR DE PDF ULTRA-UNIVERSAL E FLEXÍVEL
# ==============================================================================
def extrair_dados_danfe_universal(texto_completo):
    produtos_extraidos = []
    linhas = [l.strip() for l in texto_completo.split("\n") if l.strip()]
    
    for i, linha in enumerate(linhas):
        # Captura códigos de produtos comuns no início das linhas (letras e números misturados)
        match_codigo = re.search(r'^([A-Z0-9\-]{3,15})\b', linha)
        if match_codigo:
            codigo = match_codigo.group(1)
            
            # Remove o código da linha para isolar a descrição do produto
            descricao_suja = linha.replace(codigo, "").strip()
            # Limpa números de impostos repetitivos comuns no fim da linha (ex: NCM, CFOP)
            descricao = re.sub(r'\b\d{4,8}\b.*', '', descricao_suja).strip()
            
            if not descricao and i + 1 < len(linhas):
                descricao = linhas[i+1]
                
            # Valores padrão de segurança para o sistema nunca travar a tela
            qtd = 1
            custo = 10.00
            
            # Tenta encontrar números decimais de preço na linha atual (Ex: 12,50)
            valores_decimais = re.findall(r'\b\d+,\d{2}\b', linha)
            if valores_decimais:
                try:
                    # Geralmente o preço unitário fica entre os primeiros valores após a descrição
                    custo = float(valores_decimais[0].replace(',', '.'))
                except:
                    pass
            
            # Filtro para ignorar códigos falsos (como datas ou números de telefone capturados por engano)
            if len(codigo) >= 3 and not codigo.replace("-","").isdigit():
                if custo > 1500: # Evita capturar o número do NCM como se fosse preço
                    custo = 10.00
                    
                produtos_extraidos.append({
                    "Código": codigo,
                    "Produto": descricao if descricao else f"Produto - Código {codigo}",
                    "Custo Nota": custo,
                    "Quantidade": qtd
                })
                
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

# --- 2. IMPORTAR NOTA FISCAL (UNIVERSAL E EDITÁVEL) ---
elif escolha == "Importar Nota Fiscal":
    st.subheader("📄 Entrada de Estoque Automatizada")
    c1, c2 = st.columns(2)
    valor_uber = c1.number_input("Quanto pagou de Uber/Frete para esta compra? (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c2.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    arquivo_pdf = st.file_uploader("Anexe aqui o PDF da sua Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        try:
            with pdfplumber.open(arquivo_pdf) as pdf:
                texto_nota = ""
                for page in pdf.pages:
                    txt = page.extract_text()
                    if txt:
                        texto_nota += txt + "\n"
                        
            df_nota = extrair_dados_danfe_universal(texto_nota)
            
            if not df_nota.empty:
                st.info("📝 Verifique os produtos abaixo. Você pode ajustar a quantidade e o preço de custo real direto nas caixinhas caso o PDF mude de formato!")
                
                with st.form("salvar_estoque_form_novo"):
                    novos_produtos = []
                    for idx, row in df_nota.iterrows():
                        # Cria uma chave limpa e totalmente livre de erros de duplicação
                        chave_item = f"item_{idx}_{row['Código']}"
                        
                        st.markdown(f"📦 **Código: {row['Código']}** — {row['Produto']}")
                        col_qtd, col_custo, col_pv, col_tx, col_emb = st.columns(5)
                        
                        qtd_f = col_qtd.number_input("Qtd", min_value=1, value=int(row["Quantidade"]), key=f"q_{chave_item}")
                        custo_f = col_custo.number_input("Custo NF (R$)", min_value=0.0, value=float(row['Custo Nota']), step=0.10, key=f"c_{chave_item}")
                        
                        # Preço de venda padrão sugerido baseado no custo
                        preco_sugerido = custo_f * 2 if custo_f > 0 else 20.0
                        pv_f = col_pv.number_input("Preço Venda (R$)", min_value=0.0, value=preco_sugerido, key=f"v_{chave_item}")
                        tx_f = col_tx.number_input("Taxa Canal (R$)", min_value=0.0, value=pv_f * 0.06, key=f"t_{chave_item}")
                        emb_f = col_emb.number_input("Embalagem (R$)", min_value=0.0, value=0.50, key=f"e_{chave_item}")
                        st.write("---")
                        
                        novos_produtos.append({
                            "Código": row["Código"], "Produto": row["Produto"], "Quantidade": qtd_f, 
                            "Custo Nota": custo_f, "Preço Venda": pv_f, "Taxa/Canal": tx_f, "Embalagem": emb_f
                        })
                        
                    if st.form_submit_button("Confirmar e Adicionar Tudo ao Estoque 🚀"):
                        total_nota_produtos = sum([p["Custo Nota"] * p["Quantidade"] for p in novos_produtos])
                        
                        lista_final = []
                        for p in novos_produtos:
                            peso = (p["Custo Nota"] * p["Quantidade"]) / total_nota_produtos if total_nota_produtos > 0 else 0
                            uber_proporcional = (valor_uber * peso) / p["Quantidade"] if p["Quantidade"] > 0 else 0
                            custo_real = p["Custo Nota"] + uber_proporcional
                            
                            lista_final.append({
                                "Código": p["Código"], "Produto": p["Produto"], "Categoria": "Cosméticos",
                                "Fornecedor": fornecedor_input, "Custo Nota": p["Custo Nota"], "Custo Real": custo_real,
                                "Preço Venda": p["Preço Venda"], "Taxa/Canal": p["Taxa/Canal"], "Embalagem": p["Embalagem"], "Estoque Atual": p["Quantidade"]
                            })
                            
                        st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(lista_final)], ignore_index=True)
                        st.success("Estoque alimentado perfeitamente! Os produtos já estão disponíveis.")
            else:
                st.warning("Não conseguimos ler os produtos automáticos desse arquivo. Verifique o arquivo enviado.")
        except Exception as e:
            st.error(f"Erro ao processar PDF: {e}")

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
                st.success(f"Cliente '{fast_nome}' adicionado com sucesso!")

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
                st.success(f"Venda efetuada! Valor de R$ {valor_total_venda:.2f} registrado com sucesso.")

# --- 5. CADASTRO DE CLIENTES ---
elif escolha == "Cadastro de Clientes":
    st.subheader("👥 Gestão de Clientes da Marca")
    
    st.markdown("### 📝 Adicionar Novo Cliente")
    nome = st.text_input("Nome Completo do Cliente", placeholder="Ex: Luana Avelino")
    whatsapp = st.text_input("Número do WhatsApp / Contato", placeholder="Ex: 11999999999")
    cidade = st.text_input("Cidade / Região", placeholder="Ex: São Paulo - SP")
    
    if st.button("Gravar Registro do Cliente 💾"):
        if nome:
            st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([{"Nome": nome, "WhatsApp": whatsapp, "Cidade": cidade}])], ignore_index=True)
            st.success(f"Sucesso! O cliente '{nome}' foi salvo na base de dados.")
        else:
            st.error("Por favor, preencha pelo menos o campo 'Nome' para conseguir salvar.")
            
    st.write("---")
    st.markdown("### 📋 Clientes Cadastrados")
    st.dataframe(st.session_state.clientes, use_container_width=True)
