import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()  # Loads variables from .env if present

# Use standard environment variable names
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Optionally, you can also load the service role key if you need it for admin tasks
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Use the anon key for all client-side and registration/auth operations
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# --- Direct psycopg2 connection for standalone scripts only ---
def test_db_connection():
    import psycopg2
    USER = os.getenv("DB_USER")
    PASSWORD = os.getenv("DB_PASSWORD")
    HOST = os.getenv("DB_HOST")
    PORT = os.getenv("DB_PORT")
    DBNAME = os.getenv("DB_NAME")
    try:
        connection = psycopg2.connect(
            user=USER,
            password=PASSWORD,
            host=HOST,
            port=PORT,
            dbname=DBNAME
        )
        print("Connection successful!")
        cursor = connection.cursor()
        cursor.execute("SELECT NOW();")
        result = cursor.fetchone()
        print("Current Time:", result)
        cursor.close()
        connection.close()
        print("Connection closed.")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_db_connection()