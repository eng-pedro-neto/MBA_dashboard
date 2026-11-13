from pathlib import Path
from io import BytesIO
import hashlib
import os
import sys
import tempfile
import zipfile

os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")

import folium
import geopandas as gpd
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_folium import st_folium

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from zona_utm import calcular_utm

MUNICIPIOS_PATH = APP_DIR / "dados" / "municipios_pa" / "PA_Municipios_2022.shp"
DATA_ROOT_CONFIG = APP_DIR / ".local_data_path"
DATA_ROOT = (
    Path(DATA_ROOT_CONFIG.read_text(encoding="utf-8").strip()).expanduser()
    if DATA_ROOT_CONFIG.exists()
    else APP_DIR / "dados"
)
GEOMETRY_EXTENSIONS = (".geojson", ".gpkg", ".shp", ".json", ".kml", ".gml")
TABLE_EXTENSIONS = (".csv", ".xls", ".xlsx")
SHAPEFILE_EXTENSIONS = (".dbf", ".shx", ".prj", ".cpg", ".qix")
EMBARGO_PRIVATE_COLUMNS = (
    "nom_pessoa", "cpf_cnpj_i", "cpf_cnpj_s", "end_pessoa", "des_bairro",
    "num_cep", "num_fone", "data_tad", "dat_altera", "data_cadas",
    "data_geom", "dt_carga",
)
MAP_COLUMNS_TO_HIDE = {
    "Desmatamento": ("image_date", "fid", "year", "area_km"),
    "Terras Indígenas": ("terrai_cod", "superficie", "data_atual_left"),
}
ANALYSIS_LAYER_CANDIDATES = {
    "Embargo": (
        DATA_ROOT / "embargos" / "adm_embargo_a.shp",
        DATA_ROOT / "embargos" / "embargos_ibama.parquet",
    ),
    "Desmatamento": (
        DATA_ROOT / "prodes" / "prodes.parquet",
        DATA_ROOT / "mapbiomas" / "mapbiomas_alertas.parquet",
    ),
    "Terras Indígenas": (
        DATA_ROOT / "tis_poligonais" / "tis.parquet",
    ),
}
CAR_LOCAL_CANDIDATES = (
    DATA_ROOT / "car.geojson",
    DATA_ROOT / "car.gpkg",
    DATA_ROOT / "car.parquet",
    DATA_ROOT / "car.shp",
)

st.set_page_config(page_title="MBA | Inteligência Ambiental", layout="wide")
st.title("MBA Inteligência de dados ambientais")
st.sidebar.title("Menu")


def buscar_car_por_codigo(cod_imovel):
    codigo = (cod_imovel or "").strip()
    if not codigo:
        raise ValueError("Informe o código do imóvel CAR.")

    estado = codigo[:2].upper()
    tipo = f"sicar:imoveis_{estado.lower()}"
    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": tipo,
        "outputFormat": "application/json",
        "CQL_FILTER": f"cod_imovel='{codigo}'",
    }

    try:
        resposta = requests.get(
            "https://geoserver.car.gov.br/geoserver/sicar/ows",
            params=params,
            allow_redirects=True,
            timeout=30,
        )
        resposta.raise_for_status()
        tipo_resposta = resposta.headers.get("Content-Type", "").lower()
        if "application/json" not in tipo_resposta and "json" not in tipo_resposta:
            raise ValueError(f"Resposta inesperada do GeoServer: {tipo_resposta}")
        gdf = gpd.read_file(BytesIO(resposta.content))
        if gdf.empty:
            raise ValueError("Nenhum imóvel encontrado para esse código CAR.")
        return gdf
    except requests.exceptions.SSLError as erro:
        raise RuntimeError("O GeoServer da CAR rejeitou o handshake SSL do ambiente atual.") from erro
    except Exception as erro:
        raise RuntimeError(f"Não foi possível consultar o CAR: {erro}") from erro


def buscar_car_local(cod_imovel):
    codigo = (cod_imovel or "").strip().upper()
    caminho = next((path for path in CAR_LOCAL_CANDIDATES if path.exists()), None)
    if caminho is None:
        raise FileNotFoundError(
            "Nenhuma base CAR local foi encontrada. Adicione car.geojson, car.gpkg, "
            "car.parquet ou car.shp à pasta de dados configurada."
        )

    if caminho.suffix.lower() == ".parquet":
        base = gpd.read_parquet(caminho)
    else:
        base = gpd.read_file(caminho)

    coluna_codigo = next(
        (coluna for coluna in base.columns if coluna.lower() == "cod_imovel"),
        None,
    )
    if coluna_codigo is None:
        raise ValueError(f"A base local {caminho.name} não contém a coluna cod_imovel.")

    resultado = base.loc[
        base[coluna_codigo].astype("string").str.strip().str.upper() == codigo
    ].copy()
    if resultado.empty:
        raise ValueError(f"O código {codigo} não foi encontrado na base local {caminho.name}.")
    return resultado


@st.cache_data(show_spinner="Carregando os municípios do Pará...")
def carregar_municipios():
    if not MUNICIPIOS_PATH.exists():
        raise FileNotFoundError(f"Shapefile municipal não encontrado: {MUNICIPIOS_PATH}")
    return gpd.read_file(MUNICIPIOS_PATH)


carregar_municipios()


def adicionar_camada_municipios(mapa):
    municipios = carregar_municipios()[["NM_MUN", "geometry"]].to_crs("EPSG:3857")
    municipios["geometry"] = municipios.geometry.simplify(250, preserve_topology=True)
    municipios = municipios.to_crs("EPSG:4326")
    camada = folium.FeatureGroup(name="Limites municipais do Pará", show=False)
    folium.GeoJson(
        municipios,
        style_function=lambda _: {"color": "#667085", "weight": 1, "fillOpacity": 0},
        tooltip=folium.GeoJsonTooltip(fields=["NM_MUN"], aliases=["Município"]),
    ).add_to(camada)
    camada.add_to(mapa)


def carregar_geodados(arquivos):
    if not arquivos:
        return None

    zip_files = [arquivo for arquivo in arquivos if arquivo.name.lower().endswith(".zip")]
    if zip_files:
        if len(zip_files) > 1:
            raise ValueError("Envie apenas um arquivo ZIP por vez.")
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "upload.zip"
            zip_path.write_bytes(zip_files[0].getvalue())
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(tmpdir)

            candidatos = []
            for path in Path(tmpdir).rglob("*"):
                if path.is_file() and path.suffix.lower() in GEOMETRY_EXTENSIONS:
                    candidatos.append(path)
            shapefiles = [path for path in candidatos if path.suffix.lower() == ".shp"]
            candidatos = shapefiles or candidatos
            for path in candidatos:
                try:
                    gdf = gpd.read_file(path)
                    if not gdf.empty:
                        return gdf
                except Exception:
                    continue
        raise ValueError("O ZIP não contém uma camada geoespacial válida.")

    shp_files = [arquivo for arquivo in arquivos if arquivo.name.lower().endswith(".shp")]
    if shp_files:
        if len(shp_files) != 1:
            raise ValueError("Envie um único arquivo .shp junto com seus arquivos .dbf, .shx e .prj.")
        with tempfile.TemporaryDirectory() as tmpdir:
            for arquivo in arquivos:
                nome_seguro = Path(arquivo.name).name
                (Path(tmpdir) / nome_seguro).write_bytes(arquivo.getvalue())
            return gpd.read_file(Path(tmpdir) / Path(shp_files[0].name).name)

    if len(arquivos) != 1:
        raise ValueError("Envie um arquivo geoespacial por vez.")

    arquivo = arquivos[0]
    if Path(arquivo.name).suffix.lower() not in GEOMETRY_EXTENSIONS:
        raise ValueError("Formato geoespacial não suportado.")
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(arquivo.name).suffix) as tmp:
        tmp.write(arquivo.getvalue())
        caminho = tmp.name
    try:
        return gpd.read_file(caminho)
    finally:
        os.remove(caminho)


def carregar_tabela(arquivo):
    suffix = Path(arquivo.name).suffix.lower()
    dados = arquivo.getvalue()
    if suffix == ".csv":
        try:
            return pd.read_csv(BytesIO(dados), sep=None, engine="python", encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(BytesIO(dados), sep=None, engine="python", encoding="latin-1")
    if suffix in (".xls", ".xlsx"):
        return pd.read_excel(BytesIO(dados))
    raise ValueError("Formato de tabela não suportado.")


def criar_gdf_por_coordenadas(df, coluna_latitude, coluna_longitude):
    resultado = df.copy()
    for coluna in (coluna_latitude, coluna_longitude):
        resultado[coluna] = pd.to_numeric(
            resultado[coluna].astype("string").str.strip().str.replace(",", ".", regex=False),
            errors="coerce",
        )

    valido = (
        resultado[coluna_latitude].between(-90, 90)
        & resultado[coluna_longitude].between(-180, 180)
    )
    resultado = resultado.loc[valido].copy()
    if resultado.empty:
        raise ValueError("Não há pares válidos de latitude e longitude. Confira os valores e a ordem das colunas.")

    return gpd.GeoDataFrame(
        resultado,
        geometry=gpd.points_from_xy(resultado[coluna_longitude], resultado[coluna_latitude]),
        crs="EPSG:4326",
    )


@st.cache_data(show_spinner="Carregando camada de análise...")
def carregar_camada_analise(caminho, modificado_em):
    path = Path(caminho)
    if path.suffix.lower() == ".parquet":
        return gpd.read_parquet(path)
    return gpd.read_file(path)


def analisar_poligono(poligono):
    resultados = {}
    avisos = {}
    if poligono.crs is None:
        raise ValueError("O arquivo enviado não informa o CRS. Defina o sistema de coordenadas antes da análise.")

    for tema, candidatos in ANALYSIS_LAYER_CANDIDATES.items():
        caminho = next((path for path in candidatos if path.exists()), None)
        if caminho is None:
            avisos[tema] = "Base não encontrada. Consulte a seção de dados locais no README."
            continue

        try:
            camada = carregar_camada_analise(str(caminho), caminho.stat().st_mtime_ns)
            if camada.crs is None:
                avisos[tema] = f"A base {caminho.name} não informa o CRS."
                continue
            if tema == "Embargo":
                camada = camada.drop(columns=list(EMBARGO_PRIVATE_COLUMNS), errors="ignore")
            poligono_reprojetado = (
                poligono[[poligono.geometry.name]]
                .to_crs(camada.crs)
                .dissolve()
            )
            resultados[tema] = gpd.overlay(
                camada,
                poligono_reprojetado,
                how="intersection",
                keep_geom_type=False,
            )
        except Exception as erro:
            avisos[tema] = f"Não foi possível cruzar {caminho.name}: {erro}"

    return resultados, avisos


def calcular_area_unificada_ha(camada, crs_area):
    if camada is None or camada.empty:
        return 0.0

    geometrias = camada.geometry.dropna()
    if geometrias.empty:
        return 0.0

    area_m2 = geometrias.to_crs(crs_area).union_all().area
    return float(area_m2 / 10000)


def exibir_analise_poligono(poligono, resultados, modo_compacto=False):
    poligono_geografico = poligono.to_crs("EPSG:4326")
    try:
        crs_area = f"EPSG:{calcular_utm(poligono_geografico)}"
    except Exception as erro:
        st.warning(f"Não foi possível determinar uma projeção UTM para calcular as áreas: {erro}")
        crs_area = None

    st.subheader("Áreas intersectadas")
    colunas_area = st.columns(3)
    indicadores_area = (
        ("Desmatamento", "Área Total desmatada (ha)"),
        ("Embargo", "Área Total de embargos (ha)"),
        ("Terras Indígenas", "Área Total de Terras Indígenas (ha)"),
    )
    for coluna, (tema, rotulo) in zip(colunas_area, indicadores_area):
        camada = resultados.get(tema)
        quantidade_intersecoes = len(camada) if camada is not None else 0
        try:
            area_ha = (
                calcular_area_unificada_ha(camada, crs_area)
                if crs_area is not None
                else 0.0
            )
            valor_formatado = f"{area_ha:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            coluna.metric(rotulo, valor_formatado)
            substantivo_intersecao = "interseção" if quantidade_intersecoes == 1 else "interseções"
            coluna.caption(f"{quantidade_intersecoes} {substantivo_intersecao}")
        except Exception as erro:
            coluna.metric(rotulo, "0,00")
            st.warning(f"Não foi possível calcular a área de {tema}: {erro}")

    tabelas = {
        tema: pd.DataFrame(camada.drop(columns=[camada.geometry.name], errors="ignore"))
        for tema, camada in resultados.items()
    }

    def exibir_grafico():
        temas = list(tabelas)
        if not temas:
            st.info("Nenhuma camada de análise está disponível para gerar gráficos.")
            return
        c_tema, c_tipo, c_eixo_x, c_eixo_y = st.columns(4)
        tema = c_tema.selectbox("Selecione o tema do gráfico", temas)
        df_analisado = tabelas[tema]
        colunas = df_analisado.columns.tolist()
        if len(colunas) < 2:
            st.warning("A camada selecionada precisa ter pelo menos duas colunas para configurar o gráfico.")
            return

        tipo = c_tipo.selectbox("Selecione o tipo de gráfico", ["histogram", "bar", "line", "scatter", "box", "violin"])
        eixo_x = c_eixo_x.selectbox("Selecione o eixo x", colunas)
        colunas_y = [coluna for coluna in colunas if coluna != eixo_x]
        eixo_y = c_eixo_y.selectbox("Selecione o eixo y", colunas_y)
        if tipo == "histogram":
            figura = px.histogram(df_analisado, x=eixo_x, y=eixo_y)
        else:
            figura = getattr(px, tipo)(df_analisado, x=eixo_x, y=eixo_y)
        st.plotly_chart(figura, width="stretch")

    def exibir_mapa():
        poligono_mapa = poligono.to_crs("EPSG:4326")
        limites = poligono_mapa.total_bounds
        centro = poligono_mapa.geometry.union_all().centroid
        mapa = folium.Map(location=[centro.y, centro.x], zoom_start=7, control_scale=True, tiles=None)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Tiles © Esri",
            name="Imagem de satélite",
            overlay=False,
            control=True,
        ).add_to(mapa)
        folium.TileLayer(
            tiles="OpenStreetMap",
            name="Ruas",
            overlay=False,
            control=True,
            show=False,
        ).add_to(mapa)
        folium.GeoJson(poligono_mapa, name="Área enviada", style_function=lambda _: {"color": "blue", "fillOpacity": 0.1}).add_to(mapa)
        cores = {"Embargo": "orange", "Desmatamento": "red", "Terras Indígenas": "green"}
        for tema, camada in resultados.items():
            camada_mapa = camada.drop(
                columns=list(MAP_COLUMNS_TO_HIDE.get(tema, ())),
                errors="ignore",
            ).to_crs("EPSG:4326")
            folium.GeoJson(
                camada_mapa,
                name=tema,
                style_function=lambda _, cor=cores[tema]: {"color": cor, "fillColor": cor, "fillOpacity": 0.35},
            ).add_to(mapa)
        adicionar_camada_municipios(mapa)
        mapa.fit_bounds([[limites[1], limites[0]], [limites[3], limites[2]]])
        folium.LayerControl().add_to(mapa)
        st_folium(mapa, use_container_width=True, height=560)

    if modo_compacto:
        st.subheader("Gráfico")
        exibir_grafico()
        st.subheader("Mapa")
        exibir_mapa()
        return

    visualizacao = st.sidebar.radio("Visualização da análise", ["Mapa", "Tabela", "Resumo", "Gráfico"])
    if visualizacao == "Tabela":
        for tema, tabela in tabelas.items():
            st.subheader(tema)
            st.dataframe(tabela, width="stretch")
    elif visualizacao == "Resumo":
        for tema, tabela in tabelas.items():
            st.subheader(tema)
            st.dataframe(tabela.describe(include="all").transpose(), width="stretch")
    elif visualizacao == "Gráfico":
        exibir_grafico()
    else:
        exibir_mapa()


st.sidebar.subheader("Buscar CAR")
car_codigo = st.sidebar.text_input(
    "Código do imóvel",
    value="",
    placeholder="Ex.: GO-5207080-883FE126185456889AD7A3C87719EC",
    key="car_codigo_input",
)
modo_compacto = st.sidebar.checkbox("Ativar modo compacto", key="modo_compacto")
if st.sidebar.button("Buscar CAR no GeoServer", key="btn_buscar_car"):
    try:
        st.session_state["_gdf_car"] = buscar_car_por_codigo(car_codigo)
        st.session_state["_car_busca_ativa"] = True
        st.session_state.pop("_gdf_upload", None)
        st.session_state.pop("_tabela_upload", None)
        st.session_state.pop("_gdf_coordenadas", None)
        st.success("CAR localizado e carregado com sucesso.")
    except Exception as erro_remoto:
        try:
            st.session_state["_gdf_car"] = buscar_car_local(car_codigo)
            st.session_state["_car_busca_ativa"] = True
            st.session_state.pop("_gdf_upload", None)
            st.session_state.pop("_tabela_upload", None)
            st.session_state.pop("_gdf_coordenadas", None)
            st.sidebar.success("GeoServer indisponível; imóvel carregado da base CAR local.")
        except Exception as erro_local:
            st.session_state.pop("_gdf_car", None)
            st.session_state.pop("_car_busca_ativa", None)
            st.sidebar.warning(
                "Não foi possível consultar o CAR online e não há resultado local. "
                "Você ainda pode usar o envio de arquivo geoespacial abaixo."
            )
            st.sidebar.caption(f"Consulta online: {erro_remoto} | Alternativa local: {erro_local}")

if st.session_state.get("_car_busca_ativa") and st.sidebar.button(
    "Voltar ao envio de arquivos",
    key="btn_voltar_upload",
):
    st.session_state.pop("_gdf_car", None)
    st.session_state.pop("_car_busca_ativa", None)

arquivos = st.sidebar.file_uploader(
    "Selecione os arquivos para visualizar",
    type=["geojson", "gpkg", "shp", "zip", "json", "kml", "gml", "csv", "xlsx", "xls", "dbf", "shx", "prj", "cpg", "qix"],
    accept_multiple_files=True,
    help="Para shapefile, envie juntos os arquivos .shp, .dbf, .shx e .prj, ou envie um ZIP.",
    key="dados_upload",
)

car_busca_ativa = st.session_state.get("_car_busca_ativa", False)
gdf = st.session_state.get("_gdf_car") if car_busca_ativa else None
df_base = None
if arquivos and not car_busca_ativa:
    chave_arquivos = tuple(
        (arquivo.name, hashlib.sha256(arquivo.getvalue()).hexdigest())
        for arquivo in arquivos
    )
    if st.session_state.get("_chave_arquivos") != chave_arquivos:
        for chave in ("_gdf_upload", "_tabela_upload", "_gdf_coordenadas", "_resultados_analise", "_avisos_analise"):
            st.session_state.pop(chave, None)
        st.session_state["_chave_arquivos"] = chave_arquivos

    tabelas = [arquivo for arquivo in arquivos if Path(arquivo.name).suffix.lower() in TABLE_EXTENSIONS]
    geodados = [
        arquivo
        for arquivo in arquivos
        if Path(arquivo.name).suffix.lower() in GEOMETRY_EXTENSIONS + SHAPEFILE_EXTENSIONS
        or arquivo.name.lower().endswith(".zip")
    ]

    if tabelas and geodados:
        st.warning("Envie uma tabela ou uma camada geoespacial por vez.")
    elif tabelas:
        if len(tabelas) != 1:
            st.warning("Envie apenas uma tabela por vez.")
        else:
            try:
                if "_tabela_upload" not in st.session_state:
                    st.session_state["_tabela_upload"] = carregar_tabela(tabelas[0])
                df_base = st.session_state["_tabela_upload"]
                colunas = df_base.columns.tolist()
                st.subheader("Dados enviados")
                st.dataframe(df_base.head(10 if modo_compacto else 100), width="stretch")

                if colunas:
                    chave_widget = hashlib.sha1(repr(chave_arquivos).encode()).hexdigest()[:10]
                    col_lat, col_lon = st.sidebar.columns(2)
                    indice_lat = next((i for i, c in enumerate(colunas) if c.lower() in ("lat", "latitude", "y")), 0)
                    indice_lon = next((i for i, c in enumerate(colunas) if c.lower() in ("lon", "long", "longitude", "x")), min(1, len(colunas) - 1))
                    coluna_latitude = col_lat.selectbox("Latitude", colunas, index=indice_lat, key=f"lat_{chave_widget}")
                    coluna_longitude = col_lon.selectbox("Longitude", colunas, index=indice_lon, key=f"lon_{chave_widget}")
                    if coluna_latitude == coluna_longitude:
                        st.sidebar.warning("Selecione colunas diferentes para latitude e longitude.")
                    elif st.sidebar.button("Usar coordenadas no mapa", type="primary", key=f"coords_{chave_widget}"):
                        try:
                            st.session_state["_gdf_coordenadas"] = criar_gdf_por_coordenadas(
                                df_base,
                                coluna_latitude,
                                coluna_longitude,
                            )
                        except Exception as erro:
                            st.error(f"Não foi possível criar os pontos: {erro}")
                gdf = st.session_state.get("_gdf_coordenadas")
            except Exception as erro:
                st.error(f"Erro ao ler a tabela: {erro}")
    elif geodados:
        try:
            if "_gdf_upload" not in st.session_state:
                st.session_state["_gdf_upload"] = carregar_geodados(geodados)
            gdf = st.session_state["_gdf_upload"]
        except Exception as erro:
            st.error(f"Erro ao ler a camada: {erro}")
    else:
        st.warning("Os arquivos selecionados não contêm uma camada geográfica ou tabela suportada.")
elif not car_busca_ativa:
    for chave in ("_chave_arquivos", "_gdf_upload", "_tabela_upload", "_gdf_coordenadas", "_resultados_analise", "_avisos_analise"):
        st.session_state.pop(chave, None)
    st.info("Selecione os arquivos que deseja visualizar na barra lateral ou busque um CAR pelo código.")

if gdf is not None and not gdf.empty and gdf.crs is None:
    st.warning(
        "Este arquivo não informa o sistema de coordenadas (CRS). "
        "Envie também o arquivo .prj do shapefile ou informe o código EPSG abaixo."
    )
    chave_gdf = "_gdf_car" if car_busca_ativa else "_gdf_upload"
    with st.sidebar.form("crs_upload_form"):
        codigo_epsg = st.text_input(
            "Código EPSG do arquivo",
            placeholder="Ex.: 4674",
            help="Informe o EPSG original da camada. Isso define o CRS, sem reprojetar as coordenadas.",
        )
        definir_crs = st.form_submit_button("Definir CRS")

    if definir_crs:
        try:
            codigo_epsg = codigo_epsg.strip().upper().removeprefix("EPSG:")
            if not codigo_epsg.isdigit():
                raise ValueError("Informe somente o código numérico EPSG, por exemplo 4674.")
            st.session_state[chave_gdf] = gdf.set_crs(f"EPSG:{codigo_epsg}")
            st.session_state.pop("_resultados_analise", None)
            st.session_state.pop("_avisos_analise", None)
            st.rerun()
        except Exception as erro:
            st.sidebar.error(f"Não foi possível definir o CRS: {erro}")

    st.info("Enquanto o CRS não for informado, os dados não podem ser posicionados nem cruzados no mapa.")
    st.dataframe(
        gdf.drop(columns=[gdf.geometry.name], errors="ignore").head(10 if modo_compacto else 100),
        width="stretch",
    )

if gdf is not None and not gdf.empty and gdf.crs is not None:
    tipos_geometria = set(gdf.geometry.geom_type.dropna())
    poligonal = bool(tipos_geometria.intersection({"Polygon", "MultiPolygon"}))

    if poligonal:
        if "_resultados_analise" not in st.session_state:
            resultados, avisos = analisar_poligono(gdf)
            st.session_state["_resultados_analise"] = resultados
            st.session_state["_avisos_analise"] = avisos
        resultados = st.session_state["_resultados_analise"]
        avisos = st.session_state["_avisos_analise"]
        for tema, mensagem in avisos.items():
            st.warning(f"{tema}: {mensagem}")
        exibir_analise_poligono(gdf, resultados, modo_compacto=modo_compacto)
    else:
        df = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
        st.sidebar.subheader("Colunas")
        colunas_visiveis = st.sidebar.multiselect(
            "Colunas para visualizar",
            options=df.columns.tolist(),
            default=df.columns.tolist(),
        )
        df_exibicao = df[colunas_visiveis]
        if modo_compacto:
            col1, col2, col3 = st.columns(3)
            col1.metric("Feições", f"{len(gdf):,}")
            col2.metric("Colunas exibidas", str(len(colunas_visiveis)))
            col3.metric("Geometrias", ", ".join(sorted(tipos_geometria)))
            st.dataframe(df_exibicao.head(10), width="stretch")
        else:
            elemento = st.sidebar.radio("Visualização dos dados", ["Mapa", "Tabela", "Resumo", "Gráfico"])

            if elemento == "Tabela":
                st.dataframe(df_exibicao, width="stretch")
            elif elemento == "Resumo":
                st.subheader("Resumo dos dados")
                st.dataframe(df_exibicao.describe(include="all").transpose(), width="stretch")
            elif elemento == "Gráfico":
                if len(df_exibicao.columns) < 2:
                    st.warning("Selecione pelo menos duas colunas para montar um gráfico.")
                else:
                    c1, c2, c3 = st.columns(3)
                    tipo = c1.selectbox("Tipo de gráfico", ["bar", "line", "scatter", "box", "violin", "histogram"])
                    eixo_x = c2.selectbox("Eixo X", df_exibicao.columns)
                    opcoes_y = [coluna for coluna in df_exibicao.columns if coluna != eixo_x]
                    eixo_y = c3.selectbox("Eixo Y", opcoes_y)
                    figura = getattr(px, tipo)(df_exibicao, x=eixo_x, y=eixo_y)
                    st.plotly_chart(figura, width="stretch")
            elif gdf.crs is None:
                st.warning("A camada não informa seu CRS; não é possível posicioná-la corretamente no mapa.")
            else:
                mapa_gdf = gdf.to_crs("EPSG:4326")
                centro = mapa_gdf.geometry.union_all().centroid
                mapa = folium.Map(location=[centro.y, centro.x], zoom_start=6, control_scale=True, tiles="OpenStreetMap")
                propriedades = [coluna for coluna in colunas_visiveis if coluna in mapa_gdf.columns][:8]
                folium.GeoJson(
                    mapa_gdf,
                    name="Dados enviados",
                    tooltip=folium.GeoJsonTooltip(fields=propriedades) if propriedades else None,
                ).add_to(mapa)
                adicionar_camada_municipios(mapa)
                limites = mapa_gdf.total_bounds
                mapa.fit_bounds([[limites[1], limites[0]], [limites[3], limites[2]]])
                folium.LayerControl().add_to(mapa)
                st_folium(mapa, use_container_width=True, height=560)
elif gdf is not None and gdf.empty:
    st.warning("A camada não contém feições para mostrar.")
