import os
from openai import OpenAI
from services.supabase_client import supabase

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def search_legal_docs(query: str, limit: int = 3) -> list:
    # Gera o embedding da query
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=query
    )
    query_embedding = response.data[0].embedding

    # Busca os documentos mais similares no Supabase
    result = supabase.rpc("match_legal_documents", {
        "query_embedding": query_embedding,
        "match_count": limit
    }).execute()

    return result.data