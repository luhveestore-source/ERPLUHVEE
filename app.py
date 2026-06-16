import streamlit as st
import pandas as pd
import os
from datetime import datetime
from io import BytesIO

# ==============================================================================
# CONFIGURAÇÃO DE AMBIENTE E IDENTIDADE VISUAL - LUHVEE STORES
# ==============================================================================
st.set_page_config(page_title="ERP LuhVee Stores", page_icon="🛍️", layout="wide")

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
        .print-section { position: absolute; left: 0; top: 0; width: 100%; background: white !important; color: black !important; padding: 20px; }
    }

    .etiqueta-box {
        background-color: #ffffff !important; color: #000000 !important;
        border: 2px dashed #000000 !important; padding: 15px; border-radius: 4px;
        text-align: center; margin-bottom: 15px; font-family: 'Arial', sans-serif;
    }
    .etiqueta-brand { font-size: 16px; font-weight: bold; text-transform: uppercase; margin-bottom: 5px; color: #000000 !important; }
    .etiqueta-prod { font-size: 11px; max-height: 35px; overflow: hidden; margin-bottom: 8px; line-height: 1.2; color: #333333 !important; }
    .etiqueta-price { font-size: 22px; font-weight: bold; color: #000000 !important; }

    .recibo-box {
        background: #ffffff !important;
        color: #000000 !important;
        padding: 14px 16px;
        border-radius: 8px;
        border: 1.5px solid #ff007f;
        font-family: Arial, sans-serif;
        max-width: 520px;
        font-size: 12px;
        line-height: 1.25;
    }
    .recibo-box h2 {
        font-size: 18px !important;
        margin: 0 0 4px 0 !important;
        color: #000000 !important;
    }
    .recibo-box h3 {
        font-size: 14px !important;
        margin: 6px 0 4px 0 !important;
        color: #000000 !important;
    }
    .recibo-box p, .recibo-box li {
        font-size: 12px !important;
        margin: 2px 0 !important;
        color: #000000 !important;
    }
    .recibo-box ul {
        margin-top: 4px;
        margin-bottom: 4px;
        padding-left: 18px;
    }
    .recibo-total {
        font-size: 16px !important;
        font-weight: bold;
        margin-top: 6px !important;
    }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# FUNÇÕES DE ARQUIVO
# ==============================================================================

def carregar_csv(caminho, colunas, dados_padrao=None):
    if os.path.exists(caminho):
        try:
            df = pd.read_csv(caminho)
            for col in colunas:
                if col not in df.columns:
                    df[col] = ""
            return df[colunas]
        except Exception:
            return pd.DataFrame(dados_padrao if dados_padrao else [], columns=colunas)
    return pd.DataFrame(dados_padrao if dados_padrao else [], columns=colunas)


def salvar_csv(df, caminho):
    df.to_csv(caminho, index=False)


def numero_para_float(valor, padrao=0.0):
    """
    Converte valores vindos do CSV para número.
    Aceita formatos como:
    10
    10.5
    10,50
    R$ 10,50
    """
    try:
        if pd.isna(valor):
            return padrao

        if isinstance(valor, str):
            valor = valor.replace("R$", "").replace(" ", "").strip()

            # Se tiver vírgula, considera padrão brasileiro: 1.234,56
            if "," in valor:
                valor = valor.replace(".", "").replace(",", ".")

        return float(valor)
    except Exception:
        return padrao


def numero_para_int(valor, padrao=0):
    try:
        return int(round(numero_para_float(valor, padrao)))
    except Exception:
        return padrao


def limpar_nome_produto(nome):
    """
    Padroniza o nome do produto para evitar erro por espaços, letras maiúsculas/minúsculas
    ou caracteres invisíveis no CSV.
    """
    return str(nome).strip().upper()


def formatar_moeda(valor):
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_pdf_recibo(pedido_info, itens):
    """
    Gera recibo em PDF no formato A6, compacto e pronto para WhatsApp.
    Para funcionar no Streamlit Cloud, coloque no requirements.txt:
    reportlab
    """
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
    except Exception:
        return None

    buffer = BytesIO()

    largura = 105 * mm
    altura = 148 * mm
    pdf = canvas.Canvas(buffer, pagesize=(largura, altura))

    rosa = colors.HexColor("#ff007f")
    preto = colors.black
    cinza = colors.HexColor("#444444")

    margem = 7 * mm
    y = altura - 9 * mm

    def linha():
        nonlocal y
        pdf.setStrokeColor(rosa)
        pdf.setLineWidth(0.6)
        pdf.line(margem, y, largura - margem, y)
        y -= 5 * mm

    def texto_central(txt, fonte="Helvetica-Bold", tamanho=10, cor=preto):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawCentredString(largura / 2, y, str(txt))
        y -= (tamanho * 0.45) * mm

    def texto_esq(txt, fonte="Helvetica", tamanho=7.5, cor=preto):
        nonlocal y
        pdf.setFont(fonte, tamanho)
        pdf.setFillColor(cor)
        pdf.drawString(margem, y, str(txt)[:62])
        y -= 4 * mm

    def nova_pagina_se_precisar(espaco_minimo=25):
        nonlocal y
        if y < espaco_minimo * mm:
            pdf.showPage()
            y = altura - 9 * mm
            texto_central("LUHVEE STORES", "Helvetica-Bold", 11, rosa)
            texto_central("Continuação do recibo", "Helvetica", 6.5, cinza)
            y -= 2 * mm
            linha()

    # Cabeçalho
    texto_central("LUHVEE STORES", "Helvetica-Bold", 13, rosa)
    texto_central("Curadoria Inteligente & Achadinhos Exclusivos", "Helvetica", 6.5, cinza)
    y -= 2 * mm
    linha()

    texto_central("RECIBO DE VENDA", "Helvetica-Bold", 10, preto)
    y -= 1 * mm

    texto_esq(f"Pedido: {pedido_info['Pedido']}", "Helvetica-Bold", 8)
    texto_esq(f"Data: {pedido_info['Data']}", "Helvetica", 7)
    linha()

    # Cliente
    texto_esq("CLIENTE", "Helvetica-Bold", 8, rosa)
    texto_esq(f"Nome: {pedido_info['Cliente']}", "Helvetica", 7.5)
    texto_esq(f"WhatsApp: {pedido_info['WhatsApp']}", "Helvetica", 7.5)
    linha()

    # Detalhes
    texto_esq("DETALHES DA VENDA", "Helvetica-Bold", 8, rosa)
    texto_esq(f"Plataforma: {pedido_info['Plataforma']}", "Helvetica", 7.5)
    texto_esq(f"Pagamento: {pedido_info['Forma Pagamento']} - {pedido_info['Parcelas']}", "Helvetica", 7.5)
    texto_esq(f"Status: {pedido_info['Status']}", "Helvetica", 7.5)
    linha()

    # Produtos
    texto_esq("PRODUTOS", "Helvetica-Bold", 8, rosa)

    for _, item in itens.iterrows():
        nova_pagina_se_precisar(30)
        qtd = int(item["Quantidade"])
        produto = str(item["Produto"])[:34]
        valor = formatar_moeda(numero_para_float(item["Total Item"]))

        pdf.setFont("Helvetica", 7)
        pdf.setFillColor(preto)
        pdf.drawString(margem, y, f"{qtd}x {produto}")
        pdf.drawRightString(largura - margem, y, valor)
        y -= 4 * mm

    y -= 1 * mm
    linha()

    # Total
    texto_central("TOTAL DO PEDIDO", "Helvetica-Bold", 8, preto)
    texto_central(formatar_moeda(numero_para_float(pedido_info["Total Pedido"])), "Helvetica-Bold", 16, rosa)

    y -= 2 * mm
    linha()

    texto_central("Obrigada pela preferência", "Helvetica-Oblique", 7, preto)
    texto_central("LuhVee Stores", "Helvetica-Bold", 8, rosa)

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()

def proximo_numero_pedido():
    if st.session_state.pedidos.empty:
        return "PED-0001"
    numeros = []
    for ped in st.session_state.pedidos["Pedido"].astype(str).tolist():
        try:
            numeros.append(int(ped.replace("PED-", "")))
        except Exception:
            pass
    proximo = max(numeros) + 1 if numeros else 1
    return f"PED-{proximo:04d}"


def gerar_numero_pedido_migracao(indice):
    return f"ANT-{int(indice) + 1:04d}"


def migrar_vendas_antigas_para_pedidos():
    """
    Converte as vendas antigas do arquivo vendas_base.csv para o novo formato:
    pedidos_base.csv + itens_pedido_base.csv.

    IMPORTANTE:
    - Não baixa estoque novamente.
    - Serve apenas para permitir histórico e recibo das vendas já feitas.
    """
    if st.session_state.vendas.empty:
        return 0, "Não existem vendas antigas para migrar."

    migradas = 0

    pedidos_existentes = set(st.session_state.pedidos["Pedido"].astype(str).tolist()) if not st.session_state.pedidos.empty else set()

    for idx, venda in st.session_state.vendas.iterrows():
        pedido_id = gerar_numero_pedido_migracao(idx)

        if pedido_id in pedidos_existentes:
            continue

        cliente = str(venda.get("Cliente", "Consumidor Geral"))
        produto = str(venda.get("Produto", "Produto não informado"))
        quantidade = numero_para_int(venda.get("Quantidade", 1), 1)
        total_venda = numero_para_float(venda.get("Total Venda", 0.0), 0.0)
        preco_unit = numero_para_float(venda.get("Preço Unit.", 0.0), 0.0)
        lucro = numero_para_float(venda.get("Lucro Líquido", 0.0), 0.0)

        if preco_unit <= 0 and quantidade > 0:
            preco_unit = total_venda / quantidade

        whatsapp = ""
        if not st.session_state.clientes.empty and cliente in st.session_state.clientes["Nome"].astype(str).tolist():
            dados_cliente = st.session_state.clientes[st.session_state.clientes["Nome"].astype(str) == cliente].iloc[0]
            whatsapp = dados_cliente.get("WhatsApp", "")

        data_venda = str(venda.get("Data", datetime.now().strftime("%d/%m/%Y")))

        novo_pedido = {
            "Pedido": pedido_id,
            "Data": data_venda,
            "Cliente": cliente,
            "WhatsApp": whatsapp,
            "Plataforma": "Venda antiga",
            "Forma Pagamento": "Não informado",
            "Parcelas": "Não informado",
            "Tipo Entrega": "Não informado",
            "Local Retirada/Entrega": "",
            "Status": "Pago",
            "Total Pedido": round(total_venda, 2),
            "Lucro Total": round(lucro, 2),
            "Observações": "Pedido migrado automaticamente do vendas_base.csv. O estoque NÃO foi baixado novamente."
        }

        novo_item = {
            "Pedido": pedido_id,
            "Produto": produto,
            "Quantidade": quantidade,
            "Preço Unitário": round(preco_unit, 2),
            "Total Item": round(total_venda, 2),
            "Custo Total": round(total_venda - lucro, 2),
            "Lucro Item": round(lucro, 2)
        }

        st.session_state.pedidos = pd.concat([st.session_state.pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
        st.session_state.itens_pedido = pd.concat([st.session_state.itens_pedido, pd.DataFrame([novo_item])], ignore_index=True)

        migradas += 1

    salvar_pedidos()
    salvar_itens_pedido()

    return migradas, f"{migradas} venda(s) antiga(s) migrada(s) para pedidos."


def atualizar_tipos_estoque():
    if not st.session_state.estoque.empty:
        if "Produto" in st.session_state.estoque.columns:
            st.session_state.estoque["Produto"] = st.session_state.estoque["Produto"].astype(str).str.strip()

        for col in ["Custo Nota", "Custo Real", "Preço Venda", "Taxa/Canal", "Embalagem", "Estoque Atual"]:
            if col in st.session_state.estoque.columns:
                st.session_state.estoque[col] = st.session_state.estoque[col].apply(numero_para_float).fillna(0)

        # Estoque deve ficar número inteiro
        if "Estoque Atual" in st.session_state.estoque.columns:
            st.session_state.estoque["Estoque Atual"] = st.session_state.estoque["Estoque Atual"].apply(numero_para_int)


# ==============================================================================
# BASES DE DADOS CSV
# ==============================================================================

COL_ESTOQUE = [
    "Código", "Produto", "Categoria", "Fornecedor", "Custo Nota", "Custo Real",
    "Preço Venda", "Taxa/Canal", "Embalagem", "Estoque Atual"
]

COL_CLIENTES = [
    "Nome", "WhatsApp", "Cidade", "Endereço", "Bairro", "CPF", "Observações", "Data Cadastro"
]

COL_VENDAS_ANTIGAS = [
    "Data", "Cliente", "Produto", "Quantidade", "Preço Unit.", "Total Venda", "Lucro Líquido"
]

COL_PEDIDOS = [
    "Pedido", "Data", "Cliente", "WhatsApp", "Plataforma", "Forma Pagamento",
    "Parcelas", "Tipo Entrega", "Local Retirada/Entrega", "Status",
    "Total Pedido", "Lucro Total", "Observações"
]

COL_ITENS = [
    "Pedido", "Produto", "Quantidade", "Preço Unitário", "Total Item",
    "Custo Total", "Lucro Item"
]

if "dados_inicializados" not in st.session_state:
    st.session_state.estoque = carregar_csv("estoque_base.csv", COL_ESTOQUE)

    clientes_padrao = [{
        "Nome": "Consumidor Geral",
        "WhatsApp": "-",
        "Cidade": "Físico",
        "Endereço": "",
        "Bairro": "",
        "CPF": "",
        "Observações": "",
        "Data Cadastro": datetime.now().strftime("%d/%m/%Y")
    }]
    st.session_state.clientes = carregar_csv("clientes_base.csv", COL_CLIENTES, clientes_padrao)

    st.session_state.vendas = carregar_csv("vendas_base.csv", COL_VENDAS_ANTIGAS)
    st.session_state.pedidos = carregar_csv("pedidos_base.csv", COL_PEDIDOS)
    st.session_state.itens_pedido = carregar_csv("itens_pedido_base.csv", COL_ITENS)

    atualizar_tipos_estoque()
    st.session_state.dados_inicializados = True


def salvar_estoque():
    salvar_csv(st.session_state.estoque, "estoque_base.csv")


def salvar_clientes():
    salvar_csv(st.session_state.clientes, "clientes_base.csv")


def salvar_vendas():
    salvar_csv(st.session_state.vendas, "vendas_base.csv")


def salvar_pedidos():
    salvar_csv(st.session_state.pedidos, "pedidos_base.csv")


def salvar_itens_pedido():
    salvar_csv(st.session_state.itens_pedido, "itens_pedido_base.csv")


# ==============================================================================
# CABEÇALHO
# ==============================================================================
st.markdown("<h1 class='brand-title'>LuhVee Stores ❤️</h1>", unsafe_allow_html=True)
st.markdown("<div class='brand-subtitle'>ERP de Gestão — Estoque, Clientes, Pedidos & Vendas</div>", unsafe_allow_html=True)

menu = [
    "Dashboard Geral",
    "➕ Cadastrar Produto Manual",
    "🛍️ Ver Estoque Atual",
    "🏷️ Gerador de Etiquetas",
    "🧾 Criar Pedido",
    "📋 Histórico de Pedidos",
    "🔄 Migrar Vendas Antigas",
    "👥 Cadastro de Clientes",
    "📈 Histórico por Cliente",
    "🧹 Limpeza de Dados"
]

escolha = st.sidebar.selectbox("Menu de Navegação", menu)

# ==============================================================================
# DASHBOARD
# ==============================================================================
if escolha == "Dashboard Geral":
    st.subheader("📊 Resumo Financeiro Real")

    atualizar_tipos_estoque()

    total_investido = (
        st.session_state.estoque["Custo Real"] * st.session_state.estoque["Estoque Atual"]
    ).sum() if not st.session_state.estoque.empty else 0.0

    total_vendido_pedidos = pd.to_numeric(
        st.session_state.pedidos["Total Pedido"], errors="coerce"
    ).fillna(0).sum() if not st.session_state.pedidos.empty else 0.0

    lucro_pedidos = pd.to_numeric(
        st.session_state.pedidos["Lucro Total"], errors="coerce"
    ).fillna(0).sum() if not st.session_state.pedidos.empty else 0.0

    total_vendido_antigo = pd.to_numeric(
        st.session_state.vendas["Total Venda"], errors="coerce"
    ).fillna(0).sum() if not st.session_state.vendas.empty else 0.0

    lucro_antigo = pd.to_numeric(
        st.session_state.vendas["Lucro Líquido"], errors="coerce"
    ).fillna(0).sum() if not st.session_state.vendas.empty else 0.0

    faturamento_total = total_vendido_pedidos + total_vendido_antigo
    lucro_total = lucro_pedidos + lucro_antigo

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Investimento em Estoque", formatar_moeda(total_investido))
    col2.metric("Faturamento Total", formatar_moeda(faturamento_total))
    col3.metric("Lucro Líquido Real", formatar_moeda(lucro_total))
    col4.metric("Pedidos Cadastrados", len(st.session_state.pedidos))

    st.markdown("---")
    st.subheader("📦 Produtos com Estoque Baixo")
    if st.session_state.estoque.empty:
        st.info("Nenhum produto cadastrado ainda.")
    else:
        estoque_baixo = st.session_state.estoque[st.session_state.estoque["Estoque Atual"] <= 2]
        if estoque_baixo.empty:
            st.success("Nenhum produto crítico no estoque.")
        else:
            st.dataframe(estoque_baixo[["Código", "Produto", "Preço Venda", "Estoque Atual"]], use_container_width=True)

# ==============================================================================
# CADASTRO PRODUTO
# ==============================================================================
elif escolha == "➕ Cadastrar Produto Manual":
    st.subheader("📝 Entrada Direta de Cosméticos")

    with st.form("form_cadastro_manual", clear_on_submit=True):
        col_c, col_p = st.columns([1, 2])
        codigo = col_c.text_input("Código do Produto")
        produto = col_p.text_input("Descrição / Nome do Produto")

        col_q, col_v, col_pv = st.columns(3)
        quantidade = col_q.number_input("Quantidade Comprada", min_value=1, value=1, step=1)
        custo_nota = col_v.number_input("Preço de Custo Unitário na Nota (R$)", min_value=0.0, value=0.0, format="%.2f")
        preco_venda = col_pv.number_input("Preço de Venda Sugerido (R$)", min_value=0.0, value=0.0, format="%.2f")

        fornecedor = st.text_input("Nome do Fornecedor", "Atacadão de Kits")
        categoria = st.text_input("Categoria", "Cosméticos e Maquiagem")

        botao_salvar = st.form_submit_button("Salvar Produto no Estoque 💾")

        if botao_salvar:
            if not codigo or not produto:
                st.error("Preencha o código e o nome do produto.")
            elif custo_nota <= 0:
                st.error("O preço de custo precisa ser maior que zero.")
            else:
                final_pv = preco_venda if preco_venda > 0 else (custo_nota * 2)

                novo_item = {
                    "Código": codigo.strip().upper(),
                    "Produto": produto.strip().upper(),
                    "Categoria": categoria.strip(),
                    "Fornecedor": fornecedor.strip(),
                    "Custo Nota": round(custo_nota, 2),
                    "Custo Real": round(custo_nota, 2),
                    "Preço Venda": round(final_pv, 2),
                    "Taxa/Canal": 0.00,
                    "Embalagem": 0.50,
                    "Estoque Atual": int(quantidade)
                }

                st.session_state.estoque = pd.concat([st.session_state.estoque, pd.DataFrame([novo_item])], ignore_index=True)
                salvar_estoque()
                st.success(f"✔️ {produto.upper()} cadastrado com sucesso!")
                st.rerun()

# ==============================================================================
# ESTOQUE
# ==============================================================================
elif escolha == "🛍️ Ver Estoque Atual":
    st.subheader("🛍️ Inventário LuhVee")

    if st.session_state.estoque.empty:
        st.info("O estoque está pronto para novos cadastros.")
    else:
        st.write("Você pode alterar preços ou quantidades clicando nas células abaixo:")
        estoque_editado = st.data_editor(st.session_state.estoque, use_container_width=True, num_rows="dynamic")
        if st.button("Salvar Alterações do Estoque"):
            st.session_state.estoque = estoque_editado
            atualizar_tipos_estoque()
            salvar_estoque()
            st.success("Alterações salvas no banco de dados!")
            st.rerun()

# ==============================================================================
# ETIQUETAS
# ==============================================================================
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
                copias = col_q.number_input("Cópias", min_value=1, value=max(1, int(row["Estoque Atual"])), key=f"etq_q_{idx}")
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
                        <div class='etiqueta-brand'>LuhVee Stores</div>
                        <div class='etiqueta-prod'>{item['Produto']}</div>
                        <div class='etiqueta-price'>R$ {item['Preço']:.2f}</div>
                    </div>
                    """
                    cols[total % 3].markdown(html_layout, unsafe_allow_html=True)
                    total += 1
            st.markdown("</div>", unsafe_allow_html=True)
            st.info("Para imprimir: use CTRL + P no computador ou opção imprimir no navegador.")

# ==============================================================================
# CRIAR PEDIDO
# ==============================================================================
elif escolha == "🧾 Criar Pedido":
    st.subheader("🧾 Criar Pedido Completo")

    if st.session_state.estoque.empty:
        st.warning("Cadastre produtos antes de criar pedidos.")
    elif st.session_state.clientes.empty:
        st.warning("Cadastre clientes antes de criar pedidos.")
    else:
        st.info("Selecione o cliente, escolha os produtos e finalize o pedido. O estoque será baixado automaticamente.")

        pedido_num = proximo_numero_pedido()
        st.markdown(f"### Pedido: **{pedido_num}**")

        with st.form("form_pedido"):
            col1, col2, col3 = st.columns(3)
            cliente = col1.selectbox("Cliente", st.session_state.clientes["Nome"].tolist())
            plataforma = col2.selectbox("Plataforma da Venda", [
                "WhatsApp", "Instagram", "Facebook", "Loja Física", "Yampi", "Shopee",
                "Mercado Livre", "iFood", "Outros"
            ])
            status = col3.selectbox("Status do Pedido", [
                "Pago", "Pendente", "Aguardando Retirada", "Entregue", "Cancelado"
            ])

            col4, col5, col6 = st.columns(3)
            forma_pagamento = col4.selectbox("Forma de Pagamento", [
                "PIX", "Dinheiro", "Débito", "Crédito", "Mercado Pago", "PagBank", "PicPay", "Outro"
            ])
            parcelas = col5.selectbox("Parcelas", [
                "À vista", "1x", "2x", "3x", "4x", "5x", "6x", "7x", "8x", "9x", "10x", "11x", "12x"
            ])
            tipo_entrega = col6.selectbox("Retirada / Entrega", [
                "Retirada", "Entrega Local", "Correios", "Transportadora", "Marketplaces"
            ])

            local_entrega = st.text_input("Local de retirada ou endereço de entrega")
            observacoes = st.text_area("Observações do pedido")

            st.markdown("### Produtos do Pedido")
            st.caption("Escolha até 10 produtos no mesmo pedido. Deixe quantidade 0 nos produtos que não usar.")

            itens_temp = []
            produtos_disponiveis = st.session_state.estoque["Produto"].tolist()

            for i in range(1, 11):
                col_prod, col_qtd, col_preco = st.columns([4, 1, 2])
                produto_escolhido = col_prod.selectbox(
                    f"Produto {i}",
                    [""] + produtos_disponiveis,
                    key=f"pedido_produto_{i}"
                )
                qtd = col_qtd.number_input(
                    "Qtd",
                    min_value=0,
                    value=0,
                    step=1,
                    key=f"pedido_qtd_{i}"
                )

                preco_padrao = 0.0
                if produto_escolhido:
                    linha_prod = st.session_state.estoque[st.session_state.estoque["Produto"] == produto_escolhido].iloc[0]
                    preco_padrao = float(linha_prod["Preço Venda"])

                preco_unit = col_preco.number_input(
                    "Preço Unitário",
                    min_value=0.0,
                    value=preco_padrao,
                    format="%.2f",
                    key=f"pedido_preco_{i}"
                )

                if produto_escolhido and qtd > 0:
                    itens_temp.append({
                        "Produto": produto_escolhido,
                        "Quantidade": int(qtd),
                        "Preço Unitário": float(preco_unit)
                    })

            finalizar = st.form_submit_button("Finalizar Pedido e Baixar Estoque 🎯")

        if finalizar:
            if not itens_temp:
                st.error("Adicione pelo menos 1 produto ao pedido.")
            else:
                atualizar_tipos_estoque()

                # Junta produtos repetidos dentro do mesmo pedido.
                # Exemplo: se escolher Batom em duas linhas, o sistema soma as quantidades.
                itens_agrupados = {}
                for item in itens_temp:
                    chave = limpar_nome_produto(item["Produto"])
                    if chave not in itens_agrupados:
                        itens_agrupados[chave] = {
                            "Produto": item["Produto"],
                            "Quantidade": 0,
                            "Preço Unitário": item["Preço Unitário"]
                        }
                    itens_agrupados[chave]["Quantidade"] += int(item["Quantidade"])
                    itens_agrupados[chave]["Preço Unitário"] = float(item["Preço Unitário"])

                itens_temp = list(itens_agrupados.values())

                erro_estoque = False
                mensagens_erro = []

                for item in itens_temp:
                    produto_limpo = limpar_nome_produto(item["Produto"])
                    estoque_match = st.session_state.estoque[
                        st.session_state.estoque["Produto"].astype(str).str.strip().str.upper() == produto_limpo
                    ]

                    if estoque_match.empty:
                        erro_estoque = True
                        mensagens_erro.append(f"Produto não encontrado no estoque: {item['Produto']}")
                        continue

                    # Se existir produto duplicado com o mesmo nome, soma o estoque total disponível
                    estoque_atual = estoque_match["Estoque Atual"].apply(numero_para_int).sum()

                    if estoque_atual < item["Quantidade"]:
                        erro_estoque = True
                        mensagens_erro.append(
                            f"{item['Produto']} tem apenas {estoque_atual} unidade(s) em estoque, mas você colocou {item['Quantidade']}."
                        )

                if erro_estoque:
                    st.error("Não consegui finalizar o pedido por causa do estoque abaixo:")
                    for msg in mensagens_erro:
                        st.error(msg)

                    st.info(
                        "Dica: vá em 🛍️ Ver Estoque Atual e confirme se o produto não está duplicado com o mesmo nome "
                        "ou se o estoque está salvo como número. Esta versão já aceita vírgula e espaços no CSV."
                    )
                else:
                    dados_cliente = st.session_state.clientes[st.session_state.clientes["Nome"] == cliente].iloc[0]
                    whatsapp = dados_cliente.get("WhatsApp", "")

                    total_pedido = 0.0
                    lucro_total = 0.0
                    novos_itens = []

                    for item in itens_temp:
                        produto = item["Produto"]
                        produto_limpo = limpar_nome_produto(produto)
                        qtd = int(item["Quantidade"])
                        preco_unit = float(item["Preço Unitário"])

                        estoque_match = st.session_state.estoque[
                            st.session_state.estoque["Produto"].astype(str).str.strip().str.upper() == produto_limpo
                        ]

                        linha = estoque_match.iloc[0]
                        custo_real = numero_para_float(linha["Custo Real"])
                        taxa = numero_para_float(linha.get("Taxa/Canal", 0.0))
                        embalagem = numero_para_float(linha.get("Embalagem", 0.50))

                        total_item = qtd * preco_unit
                        custo_total = qtd * custo_real
                        lucro_item = total_item - custo_total - (taxa * qtd) - (embalagem * qtd)

                        total_pedido += total_item
                        lucro_total += lucro_item

                        novos_itens.append({
                            "Pedido": pedido_num,
                            "Produto": produto,
                            "Quantidade": qtd,
                            "Preço Unitário": round(preco_unit, 2),
                            "Total Item": round(total_item, 2),
                            "Custo Total": round(custo_total, 2),
                            "Lucro Item": round(lucro_item, 2)
                        })

                        # Baixa o estoque sem depender de nome 100% igual; usa o índice da primeira linha encontrada.
                        # Se houver duplicado, baixa primeiro da primeira linha.
                        qtd_restante = qtd
                        for idx_estoque in estoque_match.index:
                            estoque_linha = numero_para_int(st.session_state.estoque.loc[idx_estoque, "Estoque Atual"])
                            if estoque_linha <= 0:
                                continue

                            baixar = min(qtd_restante, estoque_linha)
                            st.session_state.estoque.loc[idx_estoque, "Estoque Atual"] = estoque_linha - baixar
                            qtd_restante -= baixar

                            if qtd_restante <= 0:
                                break

                    novo_pedido = {
                        "Pedido": pedido_num,
                        "Data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "Cliente": cliente,
                        "WhatsApp": whatsapp,
                        "Plataforma": plataforma,
                        "Forma Pagamento": forma_pagamento,
                        "Parcelas": parcelas,
                        "Tipo Entrega": tipo_entrega,
                        "Local Retirada/Entrega": local_entrega,
                        "Status": status,
                        "Total Pedido": round(total_pedido, 2),
                        "Lucro Total": round(lucro_total, 2),
                        "Observações": observacoes
                    }

                    st.session_state.pedidos = pd.concat([st.session_state.pedidos, pd.DataFrame([novo_pedido])], ignore_index=True)
                    st.session_state.itens_pedido = pd.concat([st.session_state.itens_pedido, pd.DataFrame(novos_itens)], ignore_index=True)

                    salvar_estoque()
                    salvar_pedidos()
                    salvar_itens_pedido()

                    st.success(f"Pedido {pedido_num} criado com sucesso! Total: {formatar_moeda(total_pedido)}")
                    st.rerun()

# ==============================================================================
# HISTÓRICO DE PEDIDOS
# ==============================================================================
elif escolha == "📋 Histórico de Pedidos":
    st.subheader("📋 Histórico de Pedidos")

    if st.session_state.pedidos.empty:
        st.info("Nenhum pedido cadastrado ainda.")
    else:
        st.dataframe(st.session_state.pedidos, use_container_width=True)

        st.markdown("---")
        pedido_sel = st.selectbox("Ver detalhes do pedido", st.session_state.pedidos["Pedido"].tolist())

        pedido_info = st.session_state.pedidos[st.session_state.pedidos["Pedido"] == pedido_sel].iloc[0]
        itens = st.session_state.itens_pedido[st.session_state.itens_pedido["Pedido"] == pedido_sel]

        col1, col2, col3 = st.columns(3)
        col1.metric("Cliente", pedido_info["Cliente"])
        col2.metric("Total", formatar_moeda(numero_para_float(pedido_info["Total Pedido"])))
        col3.metric("Status", pedido_info["Status"])

        st.markdown("### Itens do Pedido")
        st.dataframe(itens, use_container_width=True)

        st.markdown("### Recibo / Pedido de Compra")
        itens_html = ""
        for _, item in itens.iterrows():
            itens_html += f"<li>{int(item['Quantidade'])}x {item['Produto']} — {formatar_moeda(numero_para_float(item['Total Item']))}</li>"

        recibo_html = f"""
        <div class="recibo-box print-section">
            <h2>LuhVee Stores ❤️</h2>
            <h3>Pedido {pedido_sel}</h3>
            <p><b>Data:</b> {pedido_info['Data']}</p>
            <p><b>Cliente:</b> {pedido_info['Cliente']}</p>
            <p><b>WhatsApp:</b> {pedido_info['WhatsApp']}</p>
            <p><b>Plataforma:</b> {pedido_info['Plataforma']}</p>
            <p><b>Pagamento:</b> {pedido_info['Forma Pagamento']} — {pedido_info['Parcelas']}</p>
            <p><b>Retirada/Entrega:</b> {pedido_info['Tipo Entrega']}</p>
            <p><b>Local:</b> {pedido_info['Local Retirada/Entrega']}</p>
            <p><b>Status:</b> {pedido_info['Status']}</p>
            <hr>
            <h3>Produtos</h3>
            <ul>{itens_html}</ul>
            <hr>
            <p class="recibo-total">Total: {formatar_moeda(numero_para_float(pedido_info['Total Pedido']))}</p>
            <p><i>Obrigada por comprar na LuhVee Stores ❤️</i></p>
        </div>
        """

        st.markdown(recibo_html, unsafe_allow_html=True)

        pdf_bytes = gerar_pdf_recibo(pedido_info, itens)

        col_pdf, col_info = st.columns([1, 2])
        if pdf_bytes:
            col_pdf.download_button(
                label="📄 Baixar recibo em PDF",
                data=pdf_bytes,
                file_name=f"recibo_{pedido_sel}.pdf",
                mime="application/pdf"
            )
        else:
            col_pdf.warning("Para ativar PDF, adicione reportlab no requirements.txt")

        col_info.info("Também dá para imprimir pelo navegador: CTRL + P e escolha 'Salvar como PDF'.")

# ==============================================================================
# MIGRAR VENDAS ANTIGAS
# ==============================================================================
elif escolha == "🔄 Migrar Vendas Antigas":
    st.subheader("🔄 Migrar Vendas Antigas para Pedidos")

    st.warning(
        "Use este botão para transformar vendas antigas do vendas_base.csv em pedidos com recibo. "
        "Essa migração NÃO baixa o estoque novamente."
    )

    if st.session_state.vendas.empty:
        st.info("Não encontrei vendas antigas no vendas_base.csv.")
    else:
        st.markdown("### Vendas antigas encontradas")
        st.dataframe(st.session_state.vendas, use_container_width=True)

        if st.button("Converter vendas antigas em pedidos com recibo"):
            total, mensagem = migrar_vendas_antigas_para_pedidos()
            if total > 0:
                st.success(mensagem)
                st.info("Agora vá em 📋 Histórico de Pedidos para abrir o pedido e imprimir o recibo.")
                st.rerun()
            else:
                st.info("Nenhuma venda nova para migrar. Talvez elas já tenham sido convertidas.")

    if not st.session_state.pedidos.empty:
        st.markdown("### Pedidos já cadastrados")
        st.dataframe(st.session_state.pedidos, use_container_width=True)


# ==============================================================================
# CLIENTES
# ==============================================================================
elif escolha == "👥 Cadastro de Clientes":
    st.subheader("👥 Base de Dados de Clientes")

    with st.form("form_cliente", clear_on_submit=True):
        col1, col2 = st.columns(2)
        nome = col1.text_input("Nome do Cliente")
        whatsapp = col2.text_input("WhatsApp")

        col3, col4 = st.columns(2)
        cidade = col3.text_input("Cidade")
        bairro = col4.text_input("Bairro")

        endereco = st.text_input("Endereço")
        cpf = st.text_input("CPF opcional")
        observacoes = st.text_area("Observações")

        salvar_cliente = st.form_submit_button("Gravar Registro do Cliente 💾")

        if salvar_cliente:
            if nome:
                nome_limpo = nome.strip()
                whatsapp_limpo = whatsapp.strip()

                cliente_duplicado = False
                if not st.session_state.clientes.empty:
                    nomes_existentes = st.session_state.clientes["Nome"].astype(str).str.strip().str.upper()
                    whats_existentes = st.session_state.clientes["WhatsApp"].astype(str).str.strip()

                    if nome_limpo.upper() in nomes_existentes.tolist():
                        cliente_duplicado = True

                    if whatsapp_limpo and whatsapp_limpo != "-" and whatsapp_limpo in whats_existentes.tolist():
                        cliente_duplicado = True

                if cliente_duplicado:
                    st.warning("Esse cliente parece já estar cadastrado. Confira em 👥 Cadastro de Clientes antes de salvar duplicado.")
                else:
                    novo_c = {
                        "Nome": nome_limpo,
                        "WhatsApp": whatsapp_limpo,
                        "Cidade": cidade.strip(),
                        "Endereço": endereco.strip(),
                        "Bairro": bairro.strip(),
                        "CPF": cpf.strip(),
                        "Observações": observacoes.strip(),
                        "Data Cadastro": datetime.now().strftime("%d/%m/%Y")
                    }
                    st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([novo_c])], ignore_index=True)
                    salvar_clientes()
                    st.success("Cliente salvo permanentemente na base!")
                    st.rerun()
            else:
                st.error("Digite pelo menos o nome do cliente.")

    st.markdown("### Clientes Cadastrados")
    clientes_editados = st.data_editor(st.session_state.clientes, use_container_width=True, num_rows="dynamic")
    if st.button("Salvar Alterações dos Clientes"):
        st.session_state.clientes = clientes_editados
        salvar_clientes()
        st.success("Clientes atualizados com sucesso!")
        st.rerun()

# ==============================================================================
# HISTÓRICO POR CLIENTE
# ==============================================================================
elif escolha == "📈 Histórico por Cliente":
    st.subheader("📈 Histórico por Cliente")

    if st.session_state.clientes.empty:
        st.info("Nenhum cliente cadastrado.")
    else:
        cliente_sel = st.selectbox("Selecione o cliente", st.session_state.clientes["Nome"].tolist())

        pedidos_cliente = st.session_state.pedidos[st.session_state.pedidos["Cliente"] == cliente_sel] if not st.session_state.pedidos.empty else pd.DataFrame()

        if pedidos_cliente.empty:
            st.info("Esse cliente ainda não possui pedidos cadastrados.")
        else:
            total_gasto = pd.to_numeric(pedidos_cliente["Total Pedido"], errors="coerce").fillna(0).sum()
            total_pedidos = len(pedidos_cliente)
            ultima_compra = pedidos_cliente.iloc[-1]["Data"]

            col1, col2, col3 = st.columns(3)
            col1.metric("Total de Pedidos", total_pedidos)
            col2.metric("Total Gasto", formatar_moeda(total_gasto))
            col3.metric("Última Compra", ultima_compra)

            st.markdown("### Pedidos desse Cliente")
            st.dataframe(pedidos_cliente, use_container_width=True)

            pedidos_ids = pedidos_cliente["Pedido"].tolist()
            itens_cliente = st.session_state.itens_pedido[st.session_state.itens_pedido["Pedido"].isin(pedidos_ids)]

            st.markdown("### Produtos Comprados")
            st.dataframe(itens_cliente, use_container_width=True)

            if not itens_cliente.empty:
                ranking = itens_cliente.groupby("Produto")["Quantidade"].sum().reset_index().sort_values("Quantidade", ascending=False)
                st.markdown("### Produtos que esse cliente mais comprou")
                st.dataframe(ranking, use_container_width=True)


# ==============================================================================
# LIMPEZA DE DADOS
# ==============================================================================
elif escolha == "🧹 Limpeza de Dados":
    st.subheader("🧹 Limpeza de Dados")
    st.warning("Use com cuidado. Essa área serve para remover clientes ou pedidos duplicados. Ela NÃO mexe no estoque.")

    aba1, aba2 = st.tabs(["👥 Excluir Cliente", "📋 Excluir Pedido"])

    with aba1:
        st.markdown("### Excluir cliente duplicado")
        st.info("Excluir cliente aqui remove apenas o cadastro do cliente. Os pedidos antigos continuam salvos, para não perder histórico.")

        if st.session_state.clientes.empty:
            st.info("Nenhum cliente cadastrado.")
        else:
            st.dataframe(st.session_state.clientes, use_container_width=True)

            clientes_lista = st.session_state.clientes["Nome"].astype(str).tolist()
            cliente_excluir = st.selectbox("Escolha o cliente para excluir", clientes_lista, key="cliente_excluir_select")
            confirmar_cliente = st.checkbox(f"Confirmo que quero excluir o cliente: {cliente_excluir}", key="confirmar_excluir_cliente")

            if st.button("🗑️ Excluir cliente selecionado"):
                if confirmar_cliente:
                    st.session_state.clientes = st.session_state.clientes[
                        st.session_state.clientes["Nome"].astype(str) != str(cliente_excluir)
                    ].reset_index(drop=True)
                    salvar_clientes()
                    st.success("Cliente excluído do cadastro.")
                    st.rerun()
                else:
                    st.error("Marque a confirmação antes de excluir.")

    with aba2:
        st.markdown("### Excluir pedido duplicado ou lançado errado")
        st.info("Isso apaga o pedido e todos os produtos ligados a ele. Não baixa e não devolve estoque automaticamente.")

        if st.session_state.pedidos.empty:
            st.info("Nenhum pedido cadastrado.")
        else:
            st.dataframe(st.session_state.pedidos, use_container_width=True)

            pedidos_lista = st.session_state.pedidos["Pedido"].astype(str).tolist()
            pedido_excluir = st.selectbox("Escolha o pedido para excluir", pedidos_lista, key="pedido_excluir_select")

            pedido_info = st.session_state.pedidos[
                st.session_state.pedidos["Pedido"].astype(str) == str(pedido_excluir)
            ]

            itens_info = st.session_state.itens_pedido[
                st.session_state.itens_pedido["Pedido"].astype(str) == str(pedido_excluir)
            ] if not st.session_state.itens_pedido.empty else pd.DataFrame()

            if not pedido_info.empty:
                st.markdown("#### Pedido selecionado")
                st.dataframe(pedido_info, use_container_width=True)

            if not itens_info.empty:
                st.markdown("#### Produtos desse pedido")
                st.dataframe(itens_info, use_container_width=True)

            confirmar_pedido = st.checkbox(f"Confirmo que quero excluir o pedido: {pedido_excluir}", key="confirmar_excluir_pedido")

            if st.button("🗑️ Excluir pedido selecionado"):
                if confirmar_pedido:
                    st.session_state.pedidos = st.session_state.pedidos[
                        st.session_state.pedidos["Pedido"].astype(str) != str(pedido_excluir)
                    ].reset_index(drop=True)

                    if not st.session_state.itens_pedido.empty:
                        st.session_state.itens_pedido = st.session_state.itens_pedido[
                            st.session_state.itens_pedido["Pedido"].astype(str) != str(pedido_excluir)
                        ].reset_index(drop=True)

                    salvar_pedidos()
                    salvar_itens_pedido()
                    st.success("Pedido e itens do pedido foram excluídos.")
                    st.rerun()
                else:
                    st.error("Marque a confirmação antes de excluir.")
