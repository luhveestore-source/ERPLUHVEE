import streamlit as st
import pandas as pd
import os

# ==============================================================================
# CONFIGURAÇÃO DE AMBIENTE E IDENTIDADE VISUAL (LUHVEES STORES)
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
    
    @media print {
        body * { visibility: hidden; }
        .print-section, .print-section * { visibility: visible; }
        .print-section { position: absolute; left: 0; top: 0; width: 100%; background: white !important; }
    }
    .etiqueta-box {
        background-color: #ffffff !important; color: #000000 !important;
        border: 2px dashed #000000 !important; padding: 15px; border-radius: 4px;
        text-align: center; margin-bottom: 15px; font-family: 'Arial', sans-serif;
    }
    .etiqueta-brand { font-size: 16px; font-weight: bold; text-transform: uppercase; margin-bottom: 5px; color: #000000 !important; }
    .etiqueta-prod { font-size: 11px; max-height: 35px; overflow: hidden; margin-bottom: 8px; line-height: 1.2; color: #333333 !important; }
    .etiqueta-price { font-size: 22px; font-weight: bold; color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# DESTRAVA AUTOMÁTICA DO BANCO DE DADOS (FORÇA ATUALIZAÇÃO PARA COSMÉTICOS)
# ==============================================================================
# Se o arquivo antigo existir e contiver a palavra 'Calçados', nós o removemos para limpar o erro de R$ 2300
if os.path.exists("estoque_base.csv"):
    try:
        df_teste = pd.read_csv("estoque_base.csv")
        if not df_teste.empty and "Calçados" in str(df_teste.from_dict_to_string if hasattr(df_teste, 'from_dict_to_string') else df_teste.values):
            os.remove("estoque_base.csv") # Apaga o arquivo com erro
            if os.path.exists("vendas_base.csv"):
                os.remove("vendas_base.csv")
    except:
        pass

# Inicializa as bases do zero, agora com as colunas corretas de Cosméticos
if 'dados_inicializados' not in st.session_state:
    if os.path.exists("estoque_base.csv"):
        st.session_state.estoque = pd.read_csv("estoque_base.csv")
    else:
        st.session_state.estoque = pd.DataFrame(columns=[
            "Código", "Produto", "Categoria", "Fornecedor", "Custo Nota", "Custo Real", "Preço Venda", "Taxa/Canal", "Embalagem", "Estoque Atual"
        ])
        
    if os.path.exists("clientes_base.csv"):
        st.session_state.clientes = pd.read_csv("clientes_base.csv")
    else:
        st.session_state.clientes = pd.DataFrame([
            {"Nome": "Consumidor Geral", "WhatsApp": "-", "Cidade": "Físico"}
        ])
        
    if os.path.exists("vendas_base.csv"):
        st.session_state.vendas = pd.read_csv("vendas_base.csv")
    else:
        st.session_state.vendas = pd.DataFrame(columns=[
            "Data", "Cliente", "Produto", "Quantidade", "Preço Unit.", "Total Venda", "Lucro Líquido"
        ])
    st.session_state.dados_inicializados = True

def salvar_estoque():
    st.session_state.estoque.to_csv("estoque_base.csv", index=False)

def salvar_clientes():
    st.session_state.clientes.to_csv("clientes_base.csv", index=False)

def salvar_vendas():
    st.session_state.vendas.to_csv("vendas_base.csv", index=False)

# ==============================================================================
# INTERFACE PRINCIPAL
# ==============================================================================
st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Painel de Gestão Direta — Cosméticos & Maquiagem</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "➕ Cadastrar Produto Manual", "🛍️ Ver Estoque Atual", "🏷️ Gerador de Etiquetas", "💸 Lançar Venda", "👥 Cadastro de Clientes"]
escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# --- DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro Real")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum() if not st.session_state.estoque.empty else 0.0
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Investimento em Estoque", f"R$ {total_investido:,.2f}")
    col2.metric("Faturamento Total", f"R$ {total_vendido:,.2f}")
    col3.metric("Lucro Líquido Real", f"R$ {lucro_real:,.2f}")

# --- NOVO MÓDULO: CADASTRO MANUAL SEGURO ---
elif escolha == "➕ Cadastrar Produto Manual":
    st.subheader("📝 Entrada Direta de Cosméticos")
    st.write("Insira os dados do produto exatamente como constam na sua nota fiscal:")
    
    with st.form("form_cadastro_manual", clear_on_submit=True):
        col_c, col_p = st.columns([1, 2])
        codigo = col_c.text_input("Código do Produto (Ex: EC0129)")
        produto = col_p.text_input("Descrição / Nome do Cosmético (Ex: KIT 4 ITENS UNICORNIO)")
        
        col_q, col_v, col_pv = st.columns(3)
        quantidade = col_q.number_input("Quantidade Comprada", min_value=1, value=1, step=1)
        custo_nota = col_v.number_input("Preço de Custo Unitário na Nota (R$)", min_value=0.0, value=0.0, format="%.2f")
        preco_venda = col_pv.number_input("Preço de Venda Sugerido (R$)", min_value=0.0, value=0.0, format="%.2f")
        
        st.write("---")
        fornecedor = st.text_input("Nome do Fornecedor", "Atacadão de Kits")
        
        botao_salvar = st.form_submit_button("Salvar Produto no Estoque 💾")
        
        if botao_salvar:
            if not codigo or not produto:
                st.error("Por favor, preencha o Código e a Descrição do produto.")
            elif custo_nota <= 0:
                st.error("O preço de custo precisa ser maior que zero.")
            else:
                # Se o preço de venda ficou em zero, sugere o dobro do custo automaticamente
                final_pv = preco_venda if preco_venda > 0 else (custo_nota * 2)
                
                novo_item = {
                    "Código": codigo.strip().upper(),
                    "Produto": produto.strip().upper(),
                    "Categoria": "Cosméticos e Maquiagem",
                    "Fornecedor": fornecedor.strip(),
                    "Custo Nota": round(custo_nota, 2),
                    "Custo Real": round(custo_nota, 2), # Sem frete, o custo real é o da nota
                    "Preço Venda": round(final_pv, 2),
                    "Taxa/Canal": 0.00,
                    "Embalagem": 0.50,
                    "Estoque Atual": int(quantidade)
                }
                
                # Adiciona e salva permanentemente
                st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame([novo_item])], ignore_index=True)
                salvar_estoque()
                st.success(f"✔️ {produto.upper()} cadastrado com sucesso!")
                st.rerun()

# --- VER ESTOQUE ---
elif escolha == "🛍️ Ver Estoque Atual":
    st.subheader("🛍️ Inventário Luhvees de Cosméticos e Maquiagem")
    
    if st.session_state.estoque.empty:
        st.info("O estoque está limpo e pronto para novos cadastros manuais.")
    else:
        st.write("Você pode alterar preços ou quantidades clicando direto nas células abaixo:")
        estoque_editado = st.data_editor(st.session_state.estoque, use_container_width=True, num_rows="dynamic")
        if st.button("Salvar Alterações do Estoque"):
            st.session_state.estoque = estoque_editado
            salvar_estoque()
            st.success("Alterações salvas no banco de dados!")
            st.rerun()

# --- ETIQUETAS ---
elif escolha == "🏷️ Gerador de Etiquetas":
    st.subheader("🏷️ Impressor de Etiquetas de Preço")
    if st.session_state.estoque.empty:
        st.warning("Estoque vazio.")
    else:
        lista_produtos = st.session_state.estoque["Produto"].tolist()
        with st.form("etq_form"):
            produtos_selecionados = []
            for idx, prod in enumerate(lista_produtos):
                row = st.session_state.estoque[st.session_state.estoque["Produto"] == prod].iloc[0]
                col_check, col_p, col_val, col_q = st.columns([1, 4, 2, 2])
                imprimir = col_check.checkbox("Sim", key=f"etq_ch_{idx}")
                col_p.markdown(f"📦 {prod}")
                preco_etq = col_val.number_input("Preço", min_value=0.0, value=float(row["Preço Venda"]), format="%.2f", key=f"etq_v_{idx}")
                copias = col_q.number_input("Cópias", min_value=1, value=int(row["Estoque Atual"]), key=f"etq_q_{idx}")
                if imprimir:
                    produtos_selecionados.append({"Produto": prod, "Preço": preco_etq, "Quantidade": copias})
            gerar = st.form_submit_button("Gerar Etiquetas")
        if gerar and produtos_selecionados:
            st.markdown("<div class='print-section'>", unsafe_allow_html=True)
            cols = st.columns(3)
            total = 0
            for item in produtos_selecionados:
                for _ in range(item["Quantidade"]):
                    html_layout = f"<div class='etiqueta-box'><div class='etiqueta-brand'>Luhvees</div><div class='etiqueta-prod'>{item['Produto']}</div><div class='etiqueta-price'>R$ {item['Preço']:.2f}</div></div>"
                    cols[total % 3].markdown(html_layout, unsafe_allow_html=True)
                    total += 1
            st.markdown("</div>", unsafe_allow_html=True)

# --- LANÇAR VENDA ---
elif escolha == "💸 Lançar Venda":
    st.subheader("💸 Registro de Transações")
    if st.session_state.estoque.empty:
        st.info("Adicione produtos ao estoque antes de realizar vendas.")
    else:
        with st.form("venda_form"):
            cliente = st.selectbox("Cliente", st.session_state.clientes["Nome"].tolist())
            produto_nome = st.selectbox("Produto", st.session_state.estoque["Produto"].tolist())
            qtd = st.number_input("Quantidade", min_value=1, value=1)
            
            prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
            preco_sugerido = float(prod_info["Preço Venda"])
            valor_total_venda = st.number_input("Total da Venda (R$)", min_value=0.0, value=preco_sugerido * qtd, format="%.2f")
            
            if st.form_submit_button("Concluir Venda 🎯"):
                if prod_info["Estoque Atual"] < qtd:
                    st.error("Quantidade em estoque insuficiente!")
                else:
                    st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
                    salvar_estoque()
                    
                    custo_total = qtd * prod_info["Custo Real"]
                    taxa = prod_info.get("Taxa/Canal", 0.0)
                    embalagem = prod_info.get("Embalagem", 0.50)
                    lucro_total = valor_total_venda - custo_total - (taxa * qtd) - (embalagem * qtd)
                    
                    nova_venda = {
                        "Data": pd.Timestamp.now().strftime("%d/%m/%Y"), "Cliente": cliente, "Produto": produto_nome, 
                        "Quantidade": qtd, "Preço Unit.": round(valor_total_venda / qtd, 2), "Total Venda": round(valor_total_venda, 2), 
                        "Lucro Líquido": round(lucro_total, 2)
                    }
                    st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
                    salvar_vendas()
                    st.success("Venda computada com sucesso!")
                    st.rerun()

# --- CADASTRO DE CLIENTES ---
elif escolha == "👥 Cadastro de Clientes":
    st.subheader("👥 Base de Dados de Clientes")
    nome = st.text_input("Nome do Cliente")
    whatsapp = st.text_input("WhatsApp")
    cidade = st.text_input("Cidade")
    
    if st.button("Gravar Registro do Cliente 💾"):
        if nome:
            novo_c = {"Nome": nome, "WhatsApp": whatsapp, "Cidade": cidade}
            st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([novo_c])], ignore_index=True)
            salvar_clientes()
            st.success("Cliente salvo permanentemente na base!")
            st.rerun()
            
    st.markdown("### Clientes Cadastrados")
    st.dataframe(st.session_state.clientes, use_container_width=True)
