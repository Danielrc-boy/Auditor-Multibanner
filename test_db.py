import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def test_database_schema():
    print("🔌 Conectando a PostgreSQL...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO retailers (code, name, base_url)
            VALUES ('exito', 'Exito Colombia', 'https://www.exito.com')
            RETURNING id;
        """)
        retailer_id = cursor.fetchone()[0]
        print(f"✅ Retailer OK - ID: {retailer_id}")
        
        cursor.execute("""
            INSERT INTO skus (ean_gtin, internal_code, brand, title)
            VALUES ('7701234567890', 'SKU-GAL-01', 'Noel', 'Galletas Ducales 300g')
            RETURNING id;
        """)
        sku_id = cursor.fetchone()[0]
        print(f"✅ SKU OK - ID: {sku_id}")
        
        cursor.execute("""
            INSERT INTO monitoring_configs (name, retailer_id, sku_id, frequency_hours)
            VALUES ('Monitoreo Ducales Exito 6h', %s, %s, 6)
            RETURNING id;
        """, (retailer_id, sku_id))
        config_id = cursor.fetchone()[0]
        print(f"✅ Config OK - ID: {config_id}")
        
        cursor.execute("""
            INSERT INTO scraping_runs (config_id, status)
            VALUES (%s, 'RUNNING')
            RETURNING id;
        """, (config_id,))
        run_id = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO daily_digital_shelf_metrics (
                run_id, retailer_id, sku_id, search_keyword, 
                search_position, base_price, discount_price, 
                is_sponsored, in_stock
            ) VALUES (
                %s, %s, %s, 'galletas dulces',
                1, 5200.00, 4500.00,
                TRUE, TRUE
            );
        """, (run_id, retailer_id, sku_id))
        
        cursor.execute("""
            UPDATE scraping_runs 
            SET status = 'COMPLETED', finished_at = CURRENT_TIMESTAMP 
            WHERE id = %s;
        """, (run_id,))
        
        conn.commit()
        print("✅ Métricas registradas con éxito.")
        
        cursor.execute("""
            SELECT s.title, r.name, m.base_price, m.discount_price, m.discount_percentage, m.in_stock
            FROM daily_digital_shelf_metrics m
            JOIN skus s ON m.sku_id = s.id
            JOIN retailers r ON m.retailer_id = r.id
            WHERE m.run_id = %s;
        """, (run_id,))
        row = cursor.fetchone()
        
        print("\n📊 RESULTADO EN BASE DE DATOS:")
        print(f"  - Producto: {row[0]}")
        print(f"  - Retailer: {row[1]}")
        print(f"  - Precio Base: ${row[2]}")
        print(f"  - Precio Descuento: ${row[3]}")
        print(f"  - % Descuento Calculado Auto: {row[4]}%")
        print(f"  - Disponible: {'Sí' if row[5] else 'No'}")
    
    except Exception as e:
        print(f"❌ Error durante la prueba: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

if __name__ == "__main__":
    test_database_schema()