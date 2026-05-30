# rag.py

import os
from openai import OpenAI
from services.supabase_client import supabase

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def search_legal_docs(query: str, limit: int = 3) -> list:
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    query_embedding = response.data[0].embedding

    result = supabase.rpc("match_legal_documents", {
        "query_embedding": query_embedding,
        "match_count": limit
    }).execute()

    return result.data


def index_document(title: str, source: str, content: str) -> bool:
    """
    Indexes a document (CCT or any legal text) into the pgvector table.
    Splits content into chunks to avoid embedding token limits.
    """
    chunks = _split_into_chunks(content, max_chars=1500)

    for i, chunk in enumerate(chunks):
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=chunk
        )
        embedding = response.data[0].embedding

        supabase.table("legal_documents").insert({
            "title": f"{title} (parte {i+1})" if len(chunks) > 1 else title,
            "source": source,
            "content": chunk,
            "embedding": embedding
        }).execute()

    return True


def _split_into_chunks(text: str, max_chars: int = 1500) -> list:
    """
    Splits text into chunks of max_chars, breaking at paragraph boundaries.
    """
    paragraphs = text.split("\n\n")
    chunks = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current += ("" if not current else "\n\n") + para
        else:
            if current:
                chunks.append(current.strip())
            current = para

    if current:
        chunks.append(current.strip())

    return chunks if chunks else [text]