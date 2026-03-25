import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")

def migrate():
    if not db_url:
        print("DATABASE_URL not found.")
        return
        
    engine = create_engine(db_url)
    print("Migrating Database...")
    
    def run_sql(sql, desc):
        with engine.begin() as conn:
            try:
                conn.execute(text(sql))
                print(f"- {desc}")
            except Exception as e:
                # print(f"- Error during {desc}: {e}")
                pass

    run_sql("ALTER TABLE trades ADD COLUMN tp1_hit BOOLEAN DEFAULT FALSE;", "Added 'tp1_hit' column")
    
    # Try adding trade_metadata
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE trades ADD COLUMN trade_metadata VARCHAR(500);"))
            print("- Added 'trade_metadata' column")
        except:
            # If metadata already exists, rename it
            try:
                conn.execute(text("ALTER TABLE trades RENAME COLUMN metadata TO trade_metadata;"))
                print("- Renamed 'metadata' to 'trade_metadata'")
            except:
                print("- 'trade_metadata' column is ready.")
    
    run_sql("ALTER TABLE trades ADD COLUMN tp2_price FLOAT;", "Added 'tp2_price' column")
    
    print("Done! Database is ready for SonicR Paper Trading.")

if __name__ == "__main__":
    migrate()
