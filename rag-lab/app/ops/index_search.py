"""Optional Meilisearch indexing for bundled UTF-8 lecture documents."""
import os
from pathlib import Path
import meilisearch


def main():
    client = meilisearch.Client(os.environ["MEILI_URL"], os.getenv("MEILI_MASTER_KEY"))
    docs = []
    for path in sorted(Path("/app/data").glob("*.md")):
        content = path.read_text(encoding="utf-8")
        title = next((line[2:] for line in content.splitlines() if line.startswith("# ")), path.stem)
        docs.append({"doc_id": path.stem, "title": title, "content": content})
    task = client.index("learning_documents").add_documents(docs, primary_key="doc_id")
    result = client.wait_for_task(task.task_uid, timeout_in_ms=60000)
    if result.status != "succeeded":
        raise RuntimeError("Search index task did not succeed")
    print(f"Indexed {len(docs)} learning documents")


if __name__ == "__main__":
    main()
