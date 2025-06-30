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
        r = await client.get(url, follow_redirects=True, timeout=12)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"Error fetching {url}: {str(e)[:50]}")
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

def search_content_thoroughly(html, target_url, target_filename):
    """Búsqueda exhaustiva del contenido en diferentes formatos"""
    # Convertir a minúsculas para búsqueda case-insensitive
    html_lower = html.lower()
    target_url_lower = target_url.lower()
    target_filename_lower = target_filename.lower()
    target_filename_base = target_filename.split('.')[0].lower()
    
    # 1. Búsqueda del enlace exacto
    if target_url in html or target_url_lower in html_lower:
        return True, "enlace exacto"
    
    # 2. Búsqueda del nombre del archivo
    if target_filename in html or target_filename_lower in html_lower:
        return True, "nombre de archivo"
        
    # 3. Búsqueda de partes del nombre del archivo (sin extensión)
    if len(target_filename_base) > 5 and target_filename_base in html_lower:
        return True, "parte del nombre de archivo"
        
    # 4. Búsqueda de variaciones del enlace (sin protocolo, sin www, etc.)
    url_variations = [
        target_url.replace('https://', '').replace('http://', ''),
        target_url.replace('www.', ''),
        target_url.split('/')[-1],  # Solo el archivo
    ]
    
    for variation in url_variations:
        if variation in html or variation.lower() in html_lower:
            return True, f"variación del enlace ({variation})"
    
    # 5. Búsqueda específica para WordPress - paths comunes
    wp_patterns = [
        f"wp-content/uploads/{target_filename_lower}",
        f"/uploads/{target_filename_lower}",
        f"/files/{target_filename_lower}",
        target_filename_base  # Solo el nombre base sin extensión
    ]
    
    for pattern in wp_patterns:
        if pattern in html_lower:
            return True, f"patrón WordPress ({pattern})"
    
    return False, None

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
    target_filename_base = target_filename.split('.')[0]  # Sin extensión
    
    print(f"\n🔍 INICIANDO BÚSQUEDA")
    print(f"   🌐 Sitio web: {site_url}")
    print(f"   📁 Archivo objetivo: {target_filename}")
    print(f"   🔗 URL completa: {target_url}")
    print(f"   📝 Nombre base: {target_filename_base}")
    print(f"   🏗️  Buscando en WordPress (wp-content/uploads/) y otras ubicaciones")
    print("─" * 50)

    try:
        async with httpx.AsyncClient(
            verify=False, 
            timeout=20,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        ) as client:
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

                # Búsqueda optimizada:
                found_content, content_reason = search_content_thoroughly(html, target_url, target_filename)
                
                # 3. Búsqueda de enlaces que puedan apuntar al archivo (directos o redirecciones)
                found_redirect = False
                redirect_info = None
                
                if not found_content:
                    # Extraer todos los enlaces de la página
                    links = extract_links(html, current_url)
                    
                    # Buscar enlaces que puedan contener el archivo
                    potential_links = [link for link in links if (
                        # WordPress uploads
                        '/wp-content/uploads/' in link or
                        '/uploads/' in link or
                        # Otras ubicaciones comunes
                        '/files/' in link or 
                        '/documentos/' in link or
                        '/media/' in link or
                        '/download/' in link or
                        # Archivos PDF
                        '.pdf' in link.lower() or
                        # Nombre del archivo en la URL
                        target_filename.lower() in link.lower() or
                        # Parte del nombre del archivo
                        target_filename.split('.')[0].lower() in link.lower()
                    )]
                    
                    print(f"Encontrados {len(potential_links)} enlaces potenciales en {current_url}")
                    
                    # Verificar cada enlace potencial
                    for i, link in enumerate(potential_links[:8]):  # Aumentamos a 8 enlaces
                        try:
                            print(f"  Verificando {i+1}/{min(8, len(potential_links))}: {link}")
                            
                            # Verificar si es el enlace directo
                            if target_url.lower() == link.lower() or target_filename.lower() in link.lower():
                                found_redirect = True
                                redirect_info = {
                                    'original_link': link,
                                    'final_url': link,
                                    'type': 'enlace directo'
                                }
                                print(f"¡Enlace directo encontrado!: {link}")
                                break
                            
                            # Verificar redirecciones
                            response = await client.head(link, follow_redirects=True, timeout=10)
                            final_url = str(response.url)
                            
                            if (target_url.lower() in final_url.lower() or 
                                target_filename.lower() in final_url.lower()):
                                found_redirect = True
                                redirect_info = {
                                    'original_link': link,
                                    'final_url': final_url,
                                    'type': 'redirección'
                                }
                                print(f"¡Redirección encontrada!: {link} -> {final_url}")
                                break
                                
                        except Exception as e:
                            print(f"    Error verificando {link}: {str(e)[:50]}")
                            continue

                if found_content or found_redirect:
                    # Crear objeto detallado del resultado
                    resultado_detalle = {
                        'pagina_donde_se_encontro': current_url,
                        'metodo_encontrado': content_reason if found_content else redirect_info['type'],
                        'enlace_publicado': redirect_info['original_link'] if found_redirect else 'En el contenido de la página',
                        'enlace_final': redirect_info['final_url'] if found_redirect else target_url,
                        'timestamp': progreso["actual"]
                    }
                    
                    resultados.append(resultado_detalle)
                    
                    # Log detallado
                    print(f"\n🎯 ¡ENLACE ENCONTRADO!")
                    print(f"   📄 Página: {current_url}")
                    print(f"   🔍 Método: {resultado_detalle['metodo_encontrado']}")
                    if found_redirect:
                        print(f"   🔗 Enlace publicado: {redirect_info['original_link']}")
                        print(f"   📍 Enlace final: {redirect_info['final_url']}")
                    print(f"   ⏱️  En página #{progreso['actual']}")
                    print("─" * 50)

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
                
                # Actualizar progreso cada 5 páginas para mejor feedback
                if progreso["actual"] % 10 == 0:
                    print(f"Progreso: {progreso['actual']} de {progreso['total']} páginas")
                    print(f"Resultados encontrados hasta ahora: {len(resultados)}")
                    
                # Mostrar estadísticas cada 50 páginas
                if progreso["actual"] % 50 == 0:
                    print(f"=== ESTADÍSTICAS ===")
                    print(f"Páginas escaneadas: {progreso['actual']}")
                    print(f"Total en cola: {progreso['total']}")
                    print(f"Páginas visitadas únicas: {len(visited)}")
                    print(f"Resultados encontrados: {len(resultados)}")
                    print(f"====================")
                    
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
        "progreso_total": progreso["total"],
        "detalles_busqueda": {
            "paginas_escaneadas": progreso["actual"],
            "en_progreso": crawling_active
        }
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
    app.run(debug=True, port=5007)
