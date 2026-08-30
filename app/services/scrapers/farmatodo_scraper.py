import requests

def search_farmatodo(query: str):
    # Endpoint oficial de búsqueda según DevTools
    url = "https://api-search.farmatodo.com/1/indexes/*/queries"
    
    headers = {
        'x-algolia-application-id': 'VCOJEYD2PO',
        'x-algolia-api-key': 'eb9544fe7bfe7ec4c1aa5e5bf7740feb',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'origin': 'https://www.farmatodo.com.co',
        'referer': 'https://www.farmatodo.com.co/'
    }

    payload = {
        "requests": [
            {
                "indexName": "products-colombia",
                "params": f"query={query}&hitsPerPage=10&page=0"
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        results = response.json().get("results", [])[0]
        hits = results.get("hits", [])
        print(f"Total de productos extraídos: {len(hits)}\n")

        for item in hits:
            name = item.get('description') or item.get('name') or item.get('title')
            price = item.get('price') or item.get('offerPrice')
            brand = item.get('brand')
            print(f"- {name} | Marca: {brand} | Precio: ${price}")
    else:
        print("Error en la petición:", response.text)

if __name__ == "__main__":
    search_farmatodo("Nosotras")