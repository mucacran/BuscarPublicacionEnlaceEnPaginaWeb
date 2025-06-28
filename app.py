from flask import Flask, render_template, request, jsonify
import httpx
from selectolax.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import asyncio
import threading

app = Flask(__name__)

progreso = {"total": 0, "actual": 0}
resultados = []
crawling_active = False

async def fetch(client, url):
    try:
        r = await client.get(url, follow_redirects=True, timeout=10)
        if r.status_code == 200:
            return r.text
    except:
        return None
    return None

def extract_links(html, base_url):
    tree = HTMLParser(html)
    links = set()
    for node in tree.css("a[href]"):
        href = node.attributes.get("href")
        if href and not href.startswith("javascript:") and not href.startswith("mailto:") and not href.startswith("#"):
            full_url = urljoin(base_url, href)
            # Limpiar fragmentos y parámetros innecesarios
            parsed = urlparse(full_url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                clean_url += f"?{parsed.query}"
            links.add(clean_url)
    return links

async def crawler(site_url, target_url):
    global progreso, resultados, crawling_active
    crawling_active = True
    visited = set()
    queue = [site_url]
    resultados.clear()
    progreso["total"] = 1
    progreso["actual"] = 0
    
    # Obtener el dominio base para filtrar enlaces
    base_domain = urlparse(site_url).netloc
    
    # Extraer el nombre del archivo del enlace objetivo para búsqueda más flexible
    target_filename = target_url.split('/')[-1].split('?')[0]
    print(f"Buscando archivo: {target_filename}")
    print(f"Enlace completo: {target_url}")

    try:
        async with httpx.AsyncClient(verify=False, timeout=30, follow_redirects=True) as client:
            while queue and crawling_active:
                current_url = queue.pop(0)
                
                # Evitar URLs ya visitadas
                if current_url in visited:
                    continue
                    
                visited.add(current_url)
                progreso["actual"] += 1
                
                print(f"Escaneando: {current_url}")

                html = await fetch(client, current_url)
                if not html:
                    continue

                # Búsqueda múltiple:
                # 1. Buscar el enlace exacto
                found_exact = target_url in html
                
                # 2. Buscar por nombre de archivo
                found_filename = target_filename in html
                
                # 3. Buscar enlaces que redirigen al archivo objetivo
                found_redirect = False
                if not found_exact and not found_filename:
                    # Extraer todos los enlaces de descarga y verificar redirecciones
                    links = extract_links(html, current_url)
                    for link in links:
                        if '/download/' in link or 'download' in link.lower():
                            try:
                                # Verificar si este enlace redirige al archivo objetivo
                                response = await client.head(link, follow_redirects=True)
                                final_url = str(response.url)
                                if target_url in final_url or target_filename in final_url:
                                    found_redirect = True
                                    print(f"¡Redirección encontrada! {link} -> {final_url}")
                                    break
                            except:
                                continue

                if found_exact or found_filename or found_redirect:
                    resultados.append(current_url)
                    reason = "enlace exacto" if found_exact else ("nombre de archivo" if found_filename else "redirección")
                    print(f"¡Enlace encontrado en: {current_url}! (Método: {reason})")

                # Extraer todos los enlaces de la página
                links = extract_links(html, current_url)
                
                # Agregar nuevos enlaces del mismo dominio a la cola
                for link in links:
                    parsed_link = urlparse(link)
                    
                    # Solo agregar enlaces del mismo dominio que no hayamos visitado
                    if (parsed_link.netloc == base_domain and 
                        link not in visited and 
                        link not in queue):
                        
                        queue.append(link)
                        progreso["total"] += 1
                
                # Actualizar progreso cada 10 páginas para no sobrecargar
                if progreso["actual"] % 10 == 0:
                    print(f"Progreso: {progreso['actual']} de {progreso['total']} páginas")
                    
    except Exception as e:
        print(f"Error en crawler: {e}")
    finally:
        crawling_active = False
        print(f"Crawler finalizado. Páginas visitadas: {len(visited)}")
        print(f"Enlaces encontrados: {len(resultados)}")

def run_crawler_thread(site_url, target_url):
    asyncio.run(crawler(site_url, target_url))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/iniciar", methods=["POST"])
def iniciar():
    global crawling_active
    if crawling_active:
        return jsonify({"error": "Ya hay un escaneo en progreso"}), 400
    
    site = request.form["site"]
    target_url = request.form["target"]
    
    # Ejecutar el crawler en un hilo separado
    thread = threading.Thread(target=run_crawler_thread, args=(site, target_url))
    thread.daemon = True
    thread.start()
    
    return "", 204

@app.route("/progreso")
def progreso_estado():
    global progreso, crawling_active
    print(f"Progreso solicitado: {progreso}, crawling_active: {crawling_active}")
    return jsonify(progreso)

@app.route("/resultados")
def resultados_finales():
    return jsonify(resultados)

@app.route("/resultados-parciales")
def resultados_parciales():
    global resultados, progreso
    return jsonify({
        "resultados": resultados,
        "total_encontrados": len(resultados),
        "progreso_actual": progreso["actual"],
        "progreso_total": progreso["total"]
    })

@app.route("/detener", methods=["POST"])
def detener():
    global crawling_active
    crawling_active = False
    return jsonify({"status": "Crawler detenido"})

@app.route("/estado")
def estado():
    global crawling_active
    print(f"Estado solicitado: crawling_active = {crawling_active}")
    return jsonify({"crawling_active": crawling_active})

if __name__ == "__main__":
    app.run(debug=True, port=5005)
