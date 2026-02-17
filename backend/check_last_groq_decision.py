
import sys
import os
import json
from sqlalchemy import create_engine, text
from app.core.config import get_settings

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_last_groq():
    try:
        engine = create_engine(get_settings().DATABASE_URL)
        
        query = text("""
            SELECT 
                created_at,
                decision,
                confidence,
                groq_parsed_decision,
                groq_raw_response
            FROM groq_decisions_log 
            ORDER BY created_at DESC 
            LIMIT 1
        """)
        
        with engine.connect() as conn:
            result = conn.execute(query).fetchone()
            
            if not result:
                print("❌ No Groq logs found.")
                return

            timestamp, decision, confidence, raw_json, raw_text = result
            
            print(f"📅 Timestamp: {timestamp}")
            print(f"🤖 Decision: {decision} (Conf: {confidence:.2f})")
            print("-" * 50)
            print(f"📝 Raw Text Response (limit 500 chars):")
            print(str(raw_text)[:500])
            print("-" * 50)
            
            # Parse JSON safely
            try:
                if isinstance(raw_json, str):
                    data = json.loads(raw_json)
                else:
                    data = raw_json
                
                # Extract Reasoning Chain if available
                chain = data.get('reasoning_chain', {})
                if isinstance(chain, dict):
                    print("🧠 REASONING CHAIN:")
                    for step, content in chain.items():
                        print(f"\n🔹 {step}:")
                        print(f"   {content}")
                else:
                    print(f"🧠 Reasoning: {chain}")
                    
            except Exception as e:
                print(f"⚠️ Error parsing JSON: {e}")
                print(f"Raw: {raw_json}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    check_last_groq()
