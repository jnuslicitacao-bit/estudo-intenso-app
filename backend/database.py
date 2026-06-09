import os
import psycopg2

def get_db_connection():
    """Conecta ao banco PostgreSQL usando o psycopg2"""
    database_url = os.environ.get("postgresql://administrador:L1fnSYJTUY8fxCNuHrWA7IiFieD814Wr@dpg-d8iprv6q1p3s73f0qk5g-a.ohio-postgres.render.com/estudo_intenso_db")
    
    if database_url:
        print("🚀 [DATABASE] Conectando ao Postgres do Render...")
        return psycopg2.connect(database_url.strip())
    else:
        print("💻 [DATABASE] Sem URL de nuvem. Conectando ao Postgres Local...")
        return psycopg2.connect(
            user="administrador",
            password="nova_senha123",
            host="localhost",
            port=5432,
            database="estudo_intensivo_db"
        )