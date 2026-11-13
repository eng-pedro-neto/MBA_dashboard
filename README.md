# MBA | Inteligência de dados ambientais

Aplicação Streamlit para carregar camadas vetoriais ou tabelas com coordenadas, explorar atributos, cruzar polígonos com bases ambientais, consultar imóveis CAR e gerar gráficos. Os limites municipais do Pará são pré-carregados e ficam disponíveis como uma camada opcional no mapa.

## Executar localmente

Requer Python 3.11 ou superior.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run Home.py
```

## Dados incluídos

A pasta `dados/municipios_pa/` contém o shapefile municipal pré-carregado. A tela inicial tem um único uploader. Ao abrir o mapa de um arquivo enviado, use o controle de camadas do próprio mapa para ligar ou desligar `Limites municipais do Pará`.

Os arquivos `.shp`, `.shx`, `.dbf` e `.prj` devem permanecer juntos. Os arquivos `.cpg` e `.qix` acompanham a base recebida.

Ao enviar um shapefile, envie também seus arquivos `.dbf`, `.shx` e `.prj` (ou um ZIP com todos eles). Se o `.shx` estiver ausente, o app tenta reconstruí-lo. Se não houver `.prj`, informe no app o código EPSG original da camada; sem essa informação, não é possível posicioná-la corretamente nem cruzá-la com as bases de análise.

## Análise por polígono

Quando o arquivo enviado contém polígonos, o app cruza automaticamente a área com estas bases locais opcionais:

- Embargos: `dados/embargos/adm_embargo_a.shp` (com os arquivos auxiliares) ou `dados/embargos/embargos_ibama.parquet`.
- Desmatamento: `dados/prodes/prodes.parquet` ou `dados/mapbiomas/mapbiomas_alertas.parquet`.
- Terras indígenas: `dados/tis_poligonais/tis.parquet`.

As bases opcionais não foram copiadas para este pacote: juntas ocupam mais de 350 MiB, e o Parquet de desmatamento sozinho ultrapassa o limite de 100 MB por arquivo do GitHub. Coloque-as localmente nos caminhos acima para habilitar o cruzamento. Elas estão excluídas do Git por `.gitignore`; se precisar versioná-las, use Git LFS ou mantenha-as em armazenamento de dados separado.

Para apontar o app para uma pasta de dados existente sem copiá-la, crie o arquivo local `.local_data_path` na raiz do projeto e coloque nele o caminho completo da pasta `dados`. Esse arquivo é ignorado pelo Git. Sem essa configuração, o app procura os dados em `dados/` dentro do projeto.

No modo compacto, os indicadores de área em hectares mostram também a quantidade de interseções encontradas em cada camada. Abaixo ficam os controles do gráfico (tema, tipo e colunas) e o mapa. Desative o modo compacto para selecionar uma visualização principal entre mapa, tabela, resumo e gráfico.

## Busca de imóvel CAR

A busca por código tenta consultar o GeoServer do CAR. Se o serviço remoto estiver indisponível, o app tenta localizar o código em uma base local chamada `car.geojson`, `car.gpkg`, `car.parquet` ou `car.shp` dentro da pasta de dados configurada. A camada precisa ter uma coluna `cod_imovel`. Para shapefile, mantenha juntos os arquivos auxiliares (`.dbf`, `.shx` e `.prj`). A base CAR não é incluída no repositório; se a busca online e a alternativa local falharem, o envio de arquivos continua disponível.

Também é possível baixar um imóvel pela linha de comando: `python car_download.py CODIGO_CAR --saida imovel.geojson`. A consulta requer acesso ao GeoServer; nenhuma requisição é executada ao importar o módulo.

## Publicação no GitHub

Antes de tornar o repositório público, confirme a origem, os termos de uso e a permissão de redistribuição do shapefile municipal. Inclua a atribuição/licença da fonte dos dados quando aplicável. Não adicione credenciais, dados pessoais ou arquivos privados ao repositório.
