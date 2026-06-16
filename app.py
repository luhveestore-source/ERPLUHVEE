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
# LEITOR BLINDADO DE NOTA FISCAL
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
                            if "UN" in linha_seg or "PC" in inline_seg or "CX" in linha_seg or "," in linha_seg:
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
    
    # LINHA CORRIGIDA AQUI: Parêntese fechado corretamente!
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

# --- 2. IMPORTAR NOTA FISCAL ---
elif escolha == "Importar Nota Fiscal":
    st.subheader("📄 Entrada de Estoque Automatizada")
    c1, c2 = st.columns(2)
    valor_uber = c1.number_input("Quanto pagou de Uber/Frete para esta compra? (R$)", min_value=0.0, value=45.0)
    fornecedor_input = c2.text_input("Nome do Fornecedor", "Atacadão dos Kits Loja Brás")
    arquivo_pdf = st.file_uploader("Anexe aqui o PDF da sua Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        try:
            df_nota = extrair_produtos_da_nota_luhvees(arquivo_pdf)
            
            if not df_nota.empty:
                st.success("🎯 Sucesso! Isolamos os produtos reais encontrados na nota.")
                st.info("Confira os itens abaixo. Ajuste as quantidades e preços antes de salvar:")
                
                with st.form("salvar_estoque_limpo_form"):
                    novos_produtos = []
                    for idx, row in df_nota.iterrows():
                        chave_item = f"item_{idx}_{row['Código']}"
                        
                        st.markdown(f"📦 **Código: {row['Código']}** — **{row['Produto']}**")
                        col_qtd, col_custo, col_pv, col_tx, col_emb = st.columns(5)
                        
                        qtd_f = col_qtd.number_input("Qtd", min_value=1, value=int(row["Quantidade"]), key=f"q_{chave_item}")
                        custo_f = col_custo.number_input("Custo Nota (R$)", min_value=0.0, value=float(row['Custo Nota']), step=0.01, format="%.2f", key=f"c_{chave_item}")
                        pv_f = col_pv.number_input("Preço Venda (R$)", min_value=0.0, value=custo_f * 2, step=0.01, key=f"v_{chave_item}")
                        tx_f = col_tx.number_input("Taxa Canal (R$)", min_value=0.0, value=0.00, key=f"t_{chave_item}")
                        emb_f = col_emb.number_input("Embalagem (R$)", min_value=0.0, value=0.50, key=f"e_{chave_item}")
                        st.write("---")
                        
                        novos_produtos.append({
                            "Código": row["Código"], "Produto": row["Produto"], "Quantidade": qtd_f, 
                            "Custo Nota": custo_f, "Preço Venda": pv_f, "Taxa/Canal": tx_f, "Embalagem": emb_f
                        })
                        
                    if st.form_submit_button("Confirmar e Inserir no Estoque Geral 🚀"):
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
                        st.success("Estoque alimentado com sucesso! Vá para a aba 'Gerador de Etiquetas' para imprimir.")
            else:
                st.warning("Nenhum produto válido foi localizado na área de itens deste PDF. Verifique o arquivo.")
        except Exception as e:
            st.error(f"Erro no processamento do arquivo: {e}")

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

# --- 4. GERADOR DE ETIQUETAS ---
elif escolha == "Gerador de Etiquetas":
    st.subheader("🏷️ Gerador e Impressor de Etiquetas de Preço")
    
    if st.session_state.estoque.empty:
        st.warning("Seu estoque está vazio. Importe uma nota fiscal ou adicione produtos primeiro.")
    else:
        st.write("Escolha quais produtos do seu estoque deseja gerar etiquetas neste momento:")
        
        lista_produtos = st.session_state.estoque["Produto"].tolist()
        
        with st.form("seletor_etiquetas_form"):
            produtos_selecionados = []
            
            for idx, prod in enumerate(lista_produtos):
                row_estoque = st.session_state.estoque[st.session_state.estoque["Produto"] == prod].iloc[0]
                col_check, col_p, col_val, col_q = st.columns([1, 4, 2, 2])
                
                imprimir = col_check.checkbox("Imprimir", key=f"check_etq_{idx}")
                col_p.markdown(f"📦 **{prod}**")
                
                preco_etiqueta = col_val.number_input("Preço na Etiqueta (R$)", min_value=0.0, value=float(row_estoque["Preço Venda"]), step=0.01, key=f"val_etq_{idx}")
                qtd_copias = col_q.number_input("Nº de Cópias", min_value=1, value=int(row_estoque["Estoque Atual"]), key=f"qtd_etq_{idx}")
                
                if imprimir:
                    produtos_selecionados.append({
                        "Produto": prod,
                        "Preço": preco_etiqueta,
                        "Quantidade": qtd_copias
                    })
            
            gerar = st.form_submit_button("Visualizar Etiquetas Prontas 🏷️")
            
        if gerar and produtos_selecionados:
            st.success("✨ Etiquetas geradas com sucesso! Confira abaixo a pré-visualização física:")
            
            if st.button("🖨️ Enviar para Impressora / Salvar como PDF"):
                st.markdown("<script>window.print();</script>", unsafe_allow_html=True)
                
            st.write("---")
            
            st.markdown("<div class='print-section'>", unsafe_allow_html=True)
            col_et1, col_et2, col_et3 = st.columns(3)
            
            total_etiquetas = 0
            for item in produtos_selecionados:
                for _ in range(item["Quantidade"]):
                    html_layout = f"""
                    <div class='etiqueta-box'>
                        <div class='etiqueta-brand'>Luhvees Stores</div>
                        <div class='etiqueta-prod'>{item['Produto']}</div>
                        <div class='etiqueta-price'>R$ {item['Preço']:.2f}</div>
                    </div>
                    """
                    if total_etiquetas % 3 == 0:
                        col_et1.markdown(html_layout, unsafe_allow_html=True)
                    elif total_etiquetas % 3 == 1:
                        col_et2.markdown(html_layout, unsafe_allow_html=True)
                    else:
                        col_et3.markdown(html_layout, unsafe_allow_html=True)
                    total_etiquetas += 1
            st.markdown("</div>", unsafe_allow_html=True)
        elif gerar and not produtos_selecionados:
            st.warning("Por favor, marque a caixa 'Imprimir' em pelo menos um produto.")

# --- 5. LANÇAR NOVA VENDA ---
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
            
            