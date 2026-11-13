import argparse
from io import BytesIO
from pathlib import Path
import re

import geopandas as gpd
import requests


URL = "https://geoserver.car.gov.br/geoserver/sicar/ows"


def baixar_car(cod_imovel):
    codigo = (cod_imovel or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}-[A-Z0-9-]+", codigo):
        raise ValueError("Informe um código CAR válido, incluindo a sigla do estado.")

    params = {
        "service": "WFS",
        "version": "1.0.0",
        "request": "GetFeature",
        "typeName": f"sicar:imoveis_{codigo[:2].lower()}",
        "outputFormat": "application/json",
        "CQL_FILTER": f"cod_imovel='{codigo}'",
    }
    resposta = requests.get(URL, params=params, timeout=30)
    resposta.raise_for_status()
    if "json" not in resposta.headers.get("Content-Type", "").lower():
        raise ValueError("O GeoServer retornou uma resposta que não é GeoJSON.")

    gdf = gpd.read_file(BytesIO(resposta.content))
    if gdf.empty:
        raise ValueError(f"Nenhum imóvel encontrado para o código {codigo}.")
    return gdf


def main():
    parser = argparse.ArgumentParser(description="Baixa um imóvel CAR pelo código.")
    parser.add_argument("cod_imovel", help="Código completo do imóvel CAR")
    parser.add_argument("--saida", type=Path, help="Arquivo GeoJSON de destino")
    argumentos = parser.parse_args()

    gdf = baixar_car(argumentos.cod_imovel)
    destino = argumentos.saida or Path(f"{argumentos.cod_imovel}.geojson")
    gdf.to_file(destino, driver="GeoJSON")
    print(f"Imóvel salvo em: {destino.resolve()}")


if __name__ == "__main__":
    main()
