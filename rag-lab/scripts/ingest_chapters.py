import os
import sys
from pathlib import Path

# Add the project root to sys.path so we can import 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import SessionLocal
from app.services.rag_service import RAGService
from app.schemas.chat import DomainType

def main():
    rag_service = RAGService()
    db = SessionLocal()
    
    data_dir = Path("c:/Users/kik32/workspace/EST-Camp-AI-Quant/projects/investment-rag-lab/data")
    md_files = list(data_dir.glob("*.md"))
    
    if not md_files:
        print("No markdown files found in data/")
        return
        
    for md_file in md_files:
        if md_file.name in ('voca.md', 'voca-exam.md'):
            continue
            
        print(f"Ingesting {md_file.name}...")
        try:
            content = md_file.read_text(encoding='utf-8')
            title = md_file.stem
            for line in content.split('\n'):
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
                    
            count = rag_service.ingest_text(
                db=db,
                document_id=f"chapter-{md_file.stem}",
                title=title,
                content=content,
                domain=DomainType.finance.value,
            )
            print(f"Successfully ingested {md_file.name} -> {count} chunks.")
        except Exception as e:
            print(f"Error ingesting {md_file.name}: {e}")
            
    db.close()
    print("Ingestion complete.")

if __name__ == '__main__':
    main()
