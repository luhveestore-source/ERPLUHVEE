import streamlit as st
import pandas as pd
import pdfplumber
import re

# Configuração da Página e Identidade Visual (Luhvees: Preto, Rosa e Lilás)
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

# Inicialização do Estoque e tabelas no sistema
if 'estoque' not in st.session_state:
    st.session_state.estoque = pd.DataFrame([
        {"Código": "LV038", "Produto": "Hidratante Corporal Babasoul Tutti-Frutti 240ml Soul", "Categoria": "Cosméticos", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 11.40, "Custo Real": 12.13, "Preço Venda": 21.90, "Taxa/Canal": 1.31, "Embalagem": 0.50, "Estoque Atual": 12},
        {"Código": "LV040", "Produto": "Sabonete Íntimo Chiclete Morango 200ml Eco Flora", "Categoria": "Cosméticos", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 5.08, "Custo Real": 5.50, "Preço Venda": 9.90, "Taxa/Canal": 0.59, "Embalagem": 0.50, "Estoque Atual": 15}
    ])

if 'vendas' not in st.session_state:
    st.session_state.vendas = pd.DataFrame(columns=[
        "Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total a Pagar", "Forma Pagamento", "Canal Venda", "Lucro Líquido"
    ])

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame([
        {"Nome": "Maria Silva", "WhatsApp": "11999998888", "Cidade": "São Paulo"},
        {"Nome": "Ana Costa", "WhatsApp": "11977776666", "Cidade": "Santos"}
    ])

def extrair_dados_pdf_danfe(pdf_file):
    produtos_extraidos = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            lines = text.split("\n")
            for line in lines:
                match = re.search(r'^([A-Z0-4]{4,8})\s+(.+?)\s+\d{8,9}\s+\d{2,3}\s+\d{4}\s+([A-Z]{2})\s+([\d,\.]+)\s+([\d,\.]+)', line)
                if match:
                    codigo = match.group(1)
                    descricao = match.group(2)
                    qtd = float(match.group(4).replace('.', '').replace(',', '.'))
                    custo_unit = float(match.group(5).replace('.', '').replace(',', '.'))
                    
                    produtos_extraidos.append({
                        "Código": codigo, "Produto": descricao, "Custo Nota": custo_unit, "Quantidade": int(qtd), "Fornecedor": "Distribuidor"
                    })
    return pd.DataFrame(produtos_extraidos)

st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão de Estoque, Clientes e Vendas Integradas</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Importar PDF de Nota Fiscal", "Visualizar Estoque", "Lançar Nova Venda", "Cadastro de Clientes"]
escolha = st.sidebar.selectbox("Navegação", menu)

# --- TELA 1: DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro do Negócio")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum()
    total_vendido = st.session_state.vendas["Total a Pagar"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento em Estoque", f"R$ {total_investido:,.2f}")
    c2.metric("Faturamento Total de Vendas", f"R$ {total_vendido:,.2f}")
    c3.metric("Margem de Lucro / Comissão Real", f"R$ {lucro_real:,.2f}")

    st.write("---")
    st.subheader("📋 Histórico Geral de Vendas Efetuadas")
    if st.session_state.vendas.empty:
        st.info("Nenhuma venda realizada ainda.")
    else:
        st.dataframe(st.session_state.vendas, use_container_width=True)

# --- TELA 2: IMPORTAR NOTA FISCAL ---
elif escolha == "Importar PDF de Nota Fiscal":
    st.subheader("📄 Entrada de Mercadorias via PDF")
    c_ub1, c_ub2 = st.columns(2)
    valor_uber = c_ub1.number_input("Valor do Uber/Frete pago para buscar (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c_ub2.text_input("Fornecedor", "Atacadão dos Kits Loja Brás")
    
    arquivo_pdf = st.file_uploader("Anexe o PDF da Nota Fiscal aqui", type=["pdf"])

    if arquivo_pdf is not None:
        df_nota = extrair_dados_pdf_danfe(arquivo_pdf)
        if not df_nota.empty:
            valor_total_nota_produtos = (df_nota["Custo Nota"] * df_nota["Quantidade"]).sum()
            st.success(f"Nota lida com sucesso! Total em produtos: R$ {valor_total_nota_produtos:.2f}")
            
            with st.form("salvar_estoque_form"):
                novos_produtos = []
                for idx, row in df_nota.iterrows():
                    peso_no_total = (row["Custo Nota"] * row["Quantidade"]) / valor_total_nota_produtos
                    uber_proporcional = (valor_uber * peso_no_total) / row["Quantidade"]
                    custo_real_com_uber = row["Custo Nota"] + uber_proporcional
                    
                    st.write(f"📦 **{row['Produto']}** (Qtd: {row['Quantidade']})")
                    c1, c2, c3 = st.columns(3)
                    preco_venda = c1.number_input(f"Preço de Venda (R$)", min_value=0.0, value=custo_real_com_uber*2, key=f"pv_{idx}")
                    taxa_canal = c2.number_input(f"Taxa Canal (R$)", min_value=0.0, value=preco_venda*0.06, key=f"tx_{idx}")
                    embalagem = c3.number_input(f"Custo Embalagem (R$)", min_value=0.0, value=0.50, key=f"emb_{idx}")
                    
                    novos_produtos.append({
                        "Código": row["Código"], "Produto": row["Produto"], "Categoria": "Cosméticos",
                        "Fornecedor": fornecedor_input, "Custo Nota": row["Custo Nota"], "Custo Real": custo_real_com_uber,
                        "Preço Venda": preco_venda, "Taxa/Canal": taxa_canal, "Embalagem": packaging_value := embalagem, "Estoque Atual": row["Quantidade"]
                    })
                if st.form_submit_button("Adicionar tudo ao Estoque 🚀"):
                    st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(novos_produtos)], ignore_index=True)
                    st.success("Estoque alimentado com sucesso!")

# --- TELA 3: VISUALIZAR ESTOQUE ---
elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Estoque Atual da Luhvees")
    df_vis = st.session_state.estoque.copy()
    df_vis["Lucro Unit."] = df_vis["Preço Venda"] - df_vis["Custo Real"] - df_vis["Taxa/Canal"] - df_vis["Embalagem"]
    df_vis["Margem Líquida (%)"] = (df_vis["Lucro Unit."] / df_vis["Preço Venda"]) * 100
    st.dataframe(df_vis, use_container_width=True)

# --- TELA 4: LANÇAR NOVA VENDA (ATUALIZADA) ---
elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Lançamento de Vendas Efetuadas")
    
    with st.form("venda_form"):
        # 1. Escolha do Cliente e do Produto
        cliente = st.selectbox("Selecione o Cliente que comprou", st.session_state.clientes["Nome"].tolist())
        produto_nome = st.selectbox("Selecione o Produto vendido", st.session_state.estoque["Produto"].tolist())
        qtd = st.number_input("Quantidade vendida", min_value=1, value=1)
        
        # 2. Configurações pedidas: Canais de venda (incluindo Físico) e Forma de Pagamento
        canal = st.selectbox("Canal de Venda", ["Yampi", "WhatsApp", "Instagram", "Shopee", "Loja Física (Pessoalmente)"])
        forma_pagamento = st.selectbox("Forma de Pagamento", ["PIX", "Dinheiro", "Cartão de Crédito", "Cartão de Débito", "Link de Pagamento"])
        
        if st.form_submit_button("Gravar Venda e Atualizar Estoque 🎯"):
            prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
            
            if prod_info["Estoque Atual"] < qtd:
                st.error(f"Quantidade insuficiente no estoque! Você só tem {prod_info['Estoque Atual']} unidades.")
            else:
                # Cálculos automáticos de valores totais e comissão
                total_pagar = qtd * prod_info["Preço Venda"]
                custo_total = qtd * prod_info["Custo Real"]
                lucro_total = total_pagar - custo_total - (prod_info["Taxa/Canal"] * qtd) - (prod_info["Embalagem"] * qtd)
                
                # Registra na tabela de vendas
                nova_venda = {
                    "Data": pd.Timestamp.now().strftime("%d/%m/%Y"),
                    "Cliente": cliente, "Produto": produto_nome, "Qtde": qtd,
                    "Preço Unit.": prod_info["Preço Venda"], "Total a Pagar": total_pagar,
                    "Forma Pagamento": forma_pagamento, "Canal Venda": canal, "Lucro Líquido": lucro_total
                }
                st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
                
                # Dá baixa automática no estoque
                st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
                
                st.success(f"Venda gravada! Cliente: {cliente} | Total a Pagar: R$ {total_pagar:.2f} | Pago via: {forma_pagamento}")

# --- TELA 5: CADASTRO DE CLIENTES ---
elif escolha == "Cadastro de Clientes":
    st.subheader("👥 Cadastro de Clientes")
    with st.form("form_cliente"):
        nome = st.text_input("Nome do Cliente")
        whatsapp = st.text_input("WhatsApp")
        cidade = st.text_input("Cidade")
        if st.form_submit_button("Salvar Cliente"):
            if nome:
                st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([{"Nome": nome, "WhatsApp": whatsapp, "Cidade": city := cidade}])], ignore_index=True)
                st.success(f"Cliente {nome} adicionado!")
    st.dataframe(st.session_state.clientes, use_container_width=True)
