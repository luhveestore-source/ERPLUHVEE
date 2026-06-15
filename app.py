

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

# Inicialização do Banco de Dados em Memória (Puxando a estrutura das suas abas)
if 'estoque' not in st.session_state:
    st.session_state.estoque = pd.DataFrame([
        {"Código": "LV038", "Produto": "Hidratante Corporal Babasoul Tutti-Frutti 240ml Soul", "Categoria": "Cosméticos - Nova Compra", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 11.40, "Custo Real": 12.13, "Preço Venda": 21.90, "Taxa/Canal": 1.31, "Embalagem": 0.50, "Estoque Atual": 12},
        {"Código": "LV039", "Produto": "Kit Capilar 3 Itens 312 VIP Charmelle", "Categoria": "Cosméticos - Nova Compra", "Fornecedor": "Atacadão dos Kits Loja Brás", "Custo Nota": 25.70, "Custo Real": 27.35, "Preço Venda": 39.90, "Taxa/Canal": 2.39, "Embalagem": 0.50, "Estoque Atual": 6}
    ])

if 'vendas' not in st.session_state:
    st.session_state.vendas = pd.DataFrame(columns=["Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total Venda", "Custo Real Unit.", "Lucro Venda", "Canal Venda"])

if 'clientes' not in st.session_state:
    st.session_state.clientes = pd.DataFrame([{"Nome": "Maria Silva", "WhatsApp": "11999998888", "Cidade": "São Paulo"}])

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
                        "Código": codigo,
                        "Produto": descricao,
                        "Custo Nota": custo_unit,
                        "Quantidade": int(qtd),
                        "Fornecedor": "Distribuidor"
                    })
    return pd.DataFrame(produtos_extraidos)

st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão Automatizada de Estoque com Rateio de Frete/Uber</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Importar PDF de Nota Fiscal", "Visualizar Estoque", "Lançar Nova Venda"]
escolha = st.sidebar.selectbox("Navegação", menu)

# --- 1. DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro Luhvees")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum()
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Venda"].sum() if not st.session_state.vendas.empty else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento Atual em Estoque (c/ Uber)", f"R$ {total_investido:,.2f}")
    c2.metric("Faturamento de Vendas", f"R$ {total_vendido:,.2f}")
    c3.metric("Lucro Líquido Real", f"R$ {lucro_real:,.2f}")

# --- 2. IMPORTAR NOTA FISCAL (COM CÁLCULO DE UBER) ---
elif escolha == "Importar PDF de Nota Fiscal":
    st.subheader("📄 Entrada Inteligente de Mercadoria")
    
    # Inputs do Uber/Frete antes de processar a nota
    c_uber1, c_uber2 = st.columns(2)
    valor_uber = c_uber1.number_input("Quanto você pagou de Uber/Frete para buscar essa mercadoria? (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c_uber2.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    
    arquivo_pdf = st.file_uploader("Anexe aqui o PDF da Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        df_nota = extrair_dados_pdf_danfe(arquivo_pdf)
        
        if not df_nota.empty:
            # Lógica Financeira de Rateio: Descobre o valor bruto total da nota
            valor_total_nota_produtos = (df_nota["Custo Nota"] * df_nota["Quantidade"]).sum()
            
            st.success(f"Nota lida! Total em produtos: R$ {valor_total_nota_produtos:.2f}")
            st.info(f"O custo do Uber (R$ {valor_uber:.2f}) será distribuído proporcionalmente ao preço de cada produto automaticamente.")
            
            with st.form("salvar_estoque_form"):
                novos_produtos = []
                for idx, row in df_nota.iterrows():
                    # Cálculo do percentual que esse produto representa na nota para aplicar o Uber proporcional
                    peso_no_total = (row["Custo Nota"] * row["Quantidade"]) / valor_total_nota_produtos
                    uber_proporcional_unitario = (valor_uber * peso_no_total) / row["Quantidade"]
                    
                    custo_real_com_uber = row["Custo Nota"] + uber_proporcional_unitario
                    
                    st.write(f"📦 **{row['Produto']}**")
                    st.write(f"Qtd: {row['Quantidade']} | Na Nota: R$ {row['Custo Nota']:.2f} | **Com Uber: R$ {custo_real_com_uber:.2f}**")
                    
                    c1, c2, c3 = st.columns(3)
                    preco_venda = c1.number_input(f"Preço de Venda (R$)", min_value=0.0, value=custo_real_com_uber*2, key=f"pv_{idx}")
                    taxa_canal = c2.number_input(f"Taxa Canal/Yampi (R$)", min_value=0.0, value=preco_venda*0.06, key=f"tx_{idx}")
                    embalagem = c3.number_input(f"Custo Embalagem/Laço (R$)", min_value=0.0, value=0.50, key=f"emb_{idx}")
                    
                    lucro_unit = preco_venda - custo_real_com_uber - taxa_canal - embalagem
                    st.markdown(f"<span style='color:#da70d6;'>Sua comissão líquida por unidade: R$ {lucro_unit:.2f}</span>", unsafe_allow_html=True)
                    st.write("---")
                    
                    novos_produtos.append({
                        "Código": row["Código"], "Produto": row["Produto"], "Categoria": "Cosméticos",
                        "Fornecedor": fornecedor_input, "Custo Nota": row["Custo Nota"], "Custo Real": custo_real_com_uber,
                        "Preço Venda": preco_venda, "Taxa/Canal": taxa_canal, "Embalagem": embalagem, "Estoque Atual": row["Quantidade"]
                    })
                
                if st.form_submit_button("Confirmar e Adicionar ao Estoque 🚀"):
                    st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame(novos_produtos)], ignore_index=True)
                    st.success("Estoque atualizado considerando os gastos com o Uber!")

# --- 3. VISUALIZAR ESTOQUE ---
elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Seu Estoque Atualizado")
    df_vis = st.session_state.estoque.copy()
    df_vis["Lucro Unit."] = df_vis["Preço Venda"] - df_vis["Custo Real"] - df_vis["Taxa/Canal"] - df_vis["Embalagem"]
    df_vis["Margem Líquida"] = (df_vis["Lucro Unit."] / df_vis["Preço Venda"]) * 100
    st.dataframe(df_vis, use_container_width=True)

# --- 4. LANÇAR VENDA ---
elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Lançar Pedidos")
    with st.form("venda_form"):
        cliente = st.selectbox("Cliente", st.session_state.clientes["Nome"].tolist())
        produto_nome = st.selectbox("Produto", st.session_state.estoque["Produto"].tolist())
        qtd = st.number_input("Quantidade", min_value=1, value=1)
        canal = st.selectbox("Canal", ["Yampi", "WhatsApp", "Instagram", "Shopee"])
        
        if st.form_submit_button("Concluir Venda"):
            prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
            total_v = qtd * prod_info["Preço Venda"]
            lucro_v = total_v - (qtd * prod_info["Custo Real"]) - (prod_info["Taxa/Canal"] * qtd) - (prod_info["Embalagem"] * qtd)
            
            nova_venda = {"Data": "Hoje", "Cliente": cliente, "Produto": produto_nome, "Qtde": qtd, "Preço Unit.": prod_info["Preço Venda"], "Total Venda": total_v, "Custo Real Unit.": prod_info["Custo Real"], "Lucro Venda": lucro_v, "Canal Venda": canal}
            st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
            st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
            st.success(f"Venda registrada! Lucro real contabilizado: R$ {lucro_v:.2f}")
