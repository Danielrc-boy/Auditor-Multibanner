import psycopg2, sys  
URL = "postgresql://postgres:bzGSEimIxnWoqEInOACKCDPbNYvfsfOH@junction.proxy.rlwy.net:5432/railway"  
f = sys.argv[1] if len(sys.argv)  else "schema.sql"  
print(f"Conectando a Railway y ejecutando {f}...")  
try:  
    conn = psycopg2.connect(URL)  
    conn.autocommit = True  
    cur = conn.cursor()  
    with open(f, 'r', encoding='utf-8') as file:  
        cur.execute(file.read())  
    print("SUCCESS")  
except Exception as e: print(f"Error: {e}") 
