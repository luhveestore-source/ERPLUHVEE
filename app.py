import streamlit as st
import pandas as pd
import os
from datetime import datetime

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
        padding: 22px;
        border-radius: 8px;
        border: 2px solid #ff007f;
        font-family: Arial, sans-serif;
    }
    .recibo-box h2, .recibo-box h3, .recibo-box p, .recibo-box li {
        color: #000000 !important;
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
    try:
        if pd.isna(valor):
            return padrao
        if isinstance(valor, str):
            valor = valor.replace("R$", "").replace(".", "").replace(",", ".").strip()
        return float(valor)
    except Exception:
        return padrao


def numero_para_int(valor, padrao=0):
    try:
        if pd.isna(valor):
            return padrao
        return int(float(valor))
    except Exception:
        return padrao


def formatar_moeda(valor):
    return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
        for col in ["Custo Nota", "Custo Real", "Preço Venda", "Taxa/Canal", "Embalagem", "Estoque Atual"]:
            if col in st.session_state.estoque.columns:
                st.session_state.estoque[col] = pd.to_numeric(st.session_state.estoque[col], errors="coerce").fillna(0)


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
    "📈 Histórico por Cliente"
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
                erro_estoque = False
                mensagens_erro = []

                for item in itens_temp:
                    linha = st.session_state.estoque[st.session_state.estoque["Produto"] == item["Produto"]].iloc[0]
                    estoque_atual = numero_para_int(linha["Estoque Atual"])
                    if estoque_atual < item["Quantidade"]:
                        erro_estoque = True
                        mensagens_erro.append(f"{item['Produto']} tem apenas {estoque_atual} unidade(s) em estoque.")

                if erro_estoque:
                    for msg in mensagens_erro:
                        st.error(msg)
                else:
                    dados_cliente = st.session_state.clientes[st.session_state.clientes["Nome"] == cliente].iloc[0]
                    whatsapp = dados_cliente.get("WhatsApp", "")

                    total_pedido = 0.0
                    lucro_total = 0.0
                    novos_itens = []

                    for item in itens_temp:
                        produto = item["Produto"]
                        qtd = item["Quantidade"]
                        preco_unit = item["Preço Unitário"]

                        linha = st.session_state.estoque[st.session_state.estoque["Produto"] == produto].iloc[0]
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

                        st.session_state.estoque.loc[
                            st.session_state.estoque["Produto"] == produto, "Estoque Atual"
                        ] = st.session_state.estoque.loc[
                            st.session_state.estoque["Produto"] == produto, "Estoque Atual"
                        ].astype(float) - qtd

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
            itens_html += f"<li>{int(item['Quantidade'])}x {item['Produto']} — {formatar_moeda(item['Total Item'])}</li>"

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
            <h2>Total: {formatar_moeda(numero_para_float(pedido_info['Total Pedido']))}</h2>
            <p><i>Obrigada por comprar na LuhVee Stores ❤️</i></p>
        </div>
        """

        st.markdown(recibo_html, unsafe_allow_html=True)
        st.info("Para imprimir ou salvar em PDF: use CTRL + P e escolha 'Salvar como PDF'.")

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
                novo_c = {
                    "Nome": nome.strip(),
                    "WhatsApp": whatsapp.strip(),
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
