import streamlit as st
import pandas as pd
import pdfplumber
import re
import os

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
    
    /* Layout profissional de impressão de etiquetas */
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
# PERSISTÊNCIA REAL DE DADOS (ARQUIVOS CSV LOCAIS)
# ==============================================================================
if 'dados_carregados' not in st.session_state:
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
            "Data", "Cliente", "Produto", "Qtde", "Preço Unit.", "Total Venda", "Parcelas", "Forma Pagamento", "Canal Venda", "Lucro Líquido"
        ])
    st.session_state.dados_carregados = True

def salvar_estado_estoque():
    st.session_state.estoque.to_csv("estoque_base.csv", index=False)

def salvar_estado_clientes():
    st.session_state.clientes.to_csv("clientes_base.csv", index=False)

def salvar_estado_vendas():
    st.session_state.vendas.to_csv("vendas_base.csv", index=False)

# ==============================================================================
# LEITOR DE PDF AVANÇADO E COMPLETO
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
                
                if "RECEBEMOS" in linha or "CONSTATES NA NOTA" in linha or "IDENTIFICAÇÃO DO EMITENTE" in linha:
                    i += 1
                    continue
                
                if "DADOS DO PRODUTO" in linha or "DADOS DOS PRODUTOS" in linha or "PROD./SERV." in linha or "CÓD. PROD." in linha:
                    area_de_produtos = True
                    i += 1
                    continue
                
                if "DADOS ADICIONAIS" in linha or "INFORMAÇÕES COMPLEMENTARES" in linha or "CÁLCULO DO ISSQN" in linha:
                    area_de_produtos = False
                
                if area_de_produtos:
                    match_prod = re.search(r'^([A-Z0-9\-]{3,15})\s+(.+)$', texto_linhas_limpas[i])
                    if match_prod:
                        codigo = match_prod.group(1)
                        resto = match_prod.group(2)
                        
                        if codigo in ["NCM", "CFOP", "VALOR", "QUANT", "UN", "ST", "TOTAL", "CÓDIGO", "ITEM", "CNPJ"]:
                            i += 1
                            continue
                        
                        # DESCRIÇÃO COMPLETA: Junta textos fragmentados nas linhas seguintes
                        descricao_completa = resto
                        while i + 1 < len(texto_linhas_limpas):
                            linha_seg = texto_linhas_limpas[i+1].upper()
                            if re.search(r'^([A-Z0-9\-]{3,15})\s+', linha_seg):
                                break
                            if "DADOS ADICIONAIS" in linha_seg or "CÁLCULO" in linha_seg:
                                break
                            if any(x in linha_seg for x in [" UN ", " PC ", " CX ", " UND ", " PAR ", " UNID "]) or "," in linha_seg:
                                break
                            
                            if len(linha_seg.strip()) > 1:
                                descricao_completa += " " + texto_linhas_limpas[i+1]
                            i += 1
                        
                        qtd_encontrada = 1
                        preco_sugerido = 10.00
                        
                        for k in range(max(0, i-1), min(i + 3, len(texto_linhas_limpas))):
                            linha_val = texto_linhas_limpas[k]
                            match_valores = re.search(r'\b(UN|PC|CX|KG|UND|UNID|PAR)\s+([\d,\.]+)\s+([\d,\.]+)', linha_val.upper())
                            if match_valores:
                                try:
                                    qtd_encontrada = int(float(match_valores.group(2).replace('.', '').replace(',', '.')))
                                    preco_sugerido = float(match_valores.group(3).replace('.', '').replace(',', '.'))
                                    break
                                except:
                                    pass
                        
                        descricao_completa = re.sub(r'\b(UN|PC|CX|KG|UND|UNID|PAR)\b.*', '', descricao_completa, flags=re.IGNORECASE)
                        descricao_completa = re.sub(r'\b\d{8}\b.*', '', descricao_completa).strip()
                        
                        if len(descricao_completa) > 4:
                            produtos.append({
                                "Código": codigo,
                                "Produto": descricao_completa.upper(),
                                "Custo Nota": round(preco_sugerido, 2),
                                "Quantidade": qtd_encontrada
                            })
                i += 1
                
    return pd.DataFrame(produtos)

# ==============================================================================
# ESTRUTURA VISUAL E NAVEGAÇÃO
# ==============================================================================
st.markdown("<h1 class='brand-title'>Luhvees Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>Gestão Automatizada de Estoque e Vendas</div>", unsafe_allow_html=True)

menu = ["Dashboard Geral", "Anexar Nota Fiscal (PDF)", "Visualizar Estoque", "Gerador de Etiquetas", "Lançar Nova Venda", "Cadastro de Clientes"]
escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# --- 1. DASHBOARD ---
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro Real")
    total_investido = (st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]).sum() if not st.session_state.estoque.empty else 0.0
    total_vendido = st.session_state.vendas["Total Venda"].sum() if not st.session_state.vendas.empty else 0.0
    lucro_real = st.session_state.vendas["Lucro Líquido"].sum() if not st.session_state.vendas.empty else 0.0
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Investimento em Estoque", f"R$ {total_investido:,.2f}")
    col2.metric("Faturamento Total", f"R$ {total_vendido:,.2f}")
    col3.metric("Lucro Líquido Real", f"R$ {lucro_real:,.2f}")

# --- 2. ANEXAR NOTA FISCAL (MÉTODO PDF AUTOMÁTICO) ---
elif escolha == "Anexar Nota Fiscal (PDF)":
    st.subheader("📄 Entrada Automatizada por Nota Fiscal")
    
    c1, c2 = st.columns(2)
    valor_uber = c1.number_input("Valor de Frete / Uber Proporcional (R$)", min_value=0.0, value=0.00, format="%.2f")
    fornecedor_input = c2.text_input("Nome do Fornecedor", "Fornecedor de Calçados")
    
    arquivo_pdf = st.file_uploader("Anexe aqui o arquivo PDF original da Nota Fiscal", type=["pdf"])

    if arquivo_pdf is not None:
        df_nota = extrair_produtos_da_nota_luhvees(arquivo_pdf)
        
        if not df_nota.empty:
            st.success(f"🎯 Sucesso! Identificamos {len(df_nota)} produtos com a descrição completa.")
            
            with st.form("form_inserir_estoque"):
                novos_produtos = []
                for idx, row in df_nota.iterrows():
                    chave_item = f"pdf_{idx}_{row['Código']}"
                    st.markdown(f"📦 **Código: {row['Código']}** — **{row['Produto']}**")
                    
                    col_qtd, col_custo, col_pv, col_tx, col_emb = st.columns(5)
                    qtd_f = col_qtd.number_input("Qtd", min_value=1, value=int(row["Quantidade"]), key=f"q_{chave_item}")
                    custo_f = col_custo.number_input("Custo Nota", min_value=0.0, value=float(row['Custo Nota']), format="%.2f", key=f"c_{chave_item}")
                    pv_f = col_pv.number_input("Preço Venda", min_value=0.0, value=float(round(custo_f * 2, 2)), format="%.2f", key=f"v_{chave_item}")
                    tx_f = col_tx.number_input("Taxa Canal", min_value=0.0, value=0.00, format="%.2f", key=f"t_{chave_item}")
                    emb_f = col_emb.number_input("Embalagem", min_value=0.0, value=0.50, format="%.2f", key=f"e_{chave_item}")
                    st.write("---")
                    
                    novos_produtos.append({
                        "Código": row["Código"], "Produto": row["Produto"], "Quantidade": qtd_f, 
                        "Custo Nota": custo_f, "Preço Venda": pv_f, "Taxa/Canal": tx_f, "Embalagem": emb_f
                    })
                    
                bot_confirmar = st.form_submit_button("Confirmar e Registrar tudo no Estoque 🚀")
                
            if bot_confirmar:
                total_nota_produtos = sum([p["Custo Nota"] * p["Quantidade"] for p in novos_produtos])
                lista_final = []
                
                for p in novos_produtos:
                    peso = (p["Custo Nota"] * p["Quantidade"]) / total_nota_produtos if total_nota_produtos > 0 else 0
                    uber_proporcional = (valor_uber * peso) / p["Quantidade"] if p["Quantidade"] > 0 else 0
                    custo_real = round(p["Custo Nota"] + uber_proporcional, 2)
                    
                    lista_final.append({
                        "Código": p["Código"], "Produto": p["Produto"], "Categoria": "Calçados Femininos",
                        "Fornecedor": fornecedor_input, "Custo Nota": round(p["Custo Nota"], 2), "Custo Real": custo_real,
                        "Preço Venda": round(p["Preço Venda"], 2), "Taxa/Canal": round(p["Taxa/Canal"], 2), "Embalagem": round(p["Embalagem"], 2), "Estoque Atual": p["Quantidade"]
                    })
                
                df_novos = pd.DataFrame(lista_final)
                st.session_state.estoque = pd.concat([st.session_state.estoque, df_novos], ignore_index=True)
                salvar_estado_estoque() # Grava no arquivo físico do servidor
                st.success("Estoque atualizado e salvo permanentemente!")
                st.rerun()
        else:
            st.warning("Não conseguimos ler os produtos desse PDF. Certifique-se de que é uma Nota Fiscal eletrônica válida (DANFE).")

# --- 3. VISUALIZAR ESTOQUE ---
elif escolha == "Visualizar Estoque":
    st.subheader("🛍️ Inventário de Produtos Disponíveis")
    if st.session_state.estoque.empty:
        st.info("O estoque está vazio no momento.")
    else:
        st.dataframe(st.session_state.estoque, use_container_width=True)

# --- 4. GERADOR DE ETIQUETAS ---
elif escolha == "Gerador de Etiquetas":
    st.subheader("🏷️ Impressor de Etiquetas de Preço")
    if st.session_state.estoque.empty:
        st.warning("Estoque vazio.")
    else:
        lista_produtos = st.session_state.estoque["Produto"].tolist()
        with st.form("etq_form_pdf"):
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
                    html_layout = f"""
                    <div class='etiqueta-box'>
                        <div class='etiqueta-brand'>Luhvees Stores</div>
                        <div class='etiqueta-prod'>{item['Produto']}</div>
                        <div class='etiqueta-price'>R$ {item['Preço']:.2f}</div>
                    </div>
                    """
                    cols[total % 3].markdown(html_layout, unsafe_allow_html=True)
                    total += 1
            st.markdown("</div>", unsafe_allow_html=True)

# --- 5. LANÇAR NOVA VENDA ---
elif escolha == "Lançar Nova Venda":
    st.subheader("💸 Registro de Transações")
    if st.session_state.estoque.empty:
        st.info("Adicione produtos ao estoque antes de realizar vendas.")
    else:
        with st.form("venda_form_pdf"):
            cliente = st.selectbox("Cliente", st.session_state.clientes["Nome"].tolist())
            produto_nome = st.selectbox("Produto", st.session_state.estoque["Produto"].tolist())
            qtd = st.number_input("Quantidade", min_value=1, value=1)
            
            preco_sugerido = float(st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]["Preço Venda"])
            valor_total_venda = st.number_input("Total da Venda (R$)", min_value=0.0, value=preco_sugerido * qtd, format="%.2f")
            
            if st.form_submit_button("Concluir Venda 🎯"):
                prod_info = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_nome].iloc[0]
                if prod_info["Estoque Atual"] < qtd:
                    st.error("Quantidade em estoque insuficiente!")
                else:
                    st.session_state.estoque.loc[st.session_state.estoque["Produto"] == produto_nome, "Estoque Atual"] -= qtd
                    salvar_estado_estoque()
                    
                    custo_total = qtd * prod_info["Custo Real"]
                    lucro_total = valor_total_venda - custo_total - (prod_info["Taxa/Canal"] * qtd) - (prod_info["Embalagem"] * qtd)
                    
                    nova_venda = {
                        "Data": pd.Timestamp.now().strftime("%d/%m/%Y"), "Cliente": cliente, "Produto": produto_nome, "Qtde": qtd,
                        "Preço Unit.": round(valor_total_venda / qtd, 2), "Total Venda": round(valor_total_venda, 2), "Parcelas": "1x",
                        "Forma Pagamento": "PIX", "Canal Venda": "WhatsApp", "Lucro Líquido": round(lucro_total, 2)
                    }
                    st.session_state.vendas = pd.concat([st.session_state.vendas, pd.DataFrame([nova_venda])], ignore_index=True)
                    salvar_estado_vendas()
                    
                    st.success("Venda computada!")
                    st.rerun()

# --- 6. CADASTRO DE CLIENTES ---
elif escolha == "Cadastro de Clientes":
    st.subheader("👥 Cadastro de Clientes da Marca")
    nome = st.text_input("Nome")
    whatsapp = st.text_input("WhatsApp")
    cidade = st.text_input("Cidade")
    
    if st.button("Gravar Registro do Cliente 💾"):
        if nome:
            novo_c = {"Nome": nome, "WhatsApp": whatsapp, "Cidade": cidade}
            st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([novo_c])], ignore_index=True)
            salvar_estado_clientes()
            st.success("Cliente salvo permanentemente!")
            st.rerun()
            
    st.dataframe(st.session_state.clientes, use_container_width=True)
