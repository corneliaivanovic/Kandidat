"""
compare_retrieval.py
====================
Fristående jämförelseverktyg: TF-IDF vs Embeddings

Kör i terminalen från projektmappen:
    python compare_retrieval.py

Kräver att sentence-transformers är installerat:
    pip install sentence-transformers

Läser knowledge_base/-mappen i samma katalog som skriptet.
Inga ändringar behövs i plattformens kod.
"""

import os
import re
import sys

# ── Sökväg till knowledge_base ─────────────────────────────────────────────
# Om skriptet ligger i projektmappen behöver du inte ändra detta.
# Annars: ange absolut sökväg, t.ex. "/Users/oliver/projekt/knowledge_base"
KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")

# ── Inställningar ──────────────────────────────────────────────────────────
CHUNK_SIZE    = 800   # Samma som plattformen
CHUNK_OVERLAP = 150
TOP_K         = 8     # Antal chunks per metod

# ── Sökfrågor (samma format som plattformens RAG-sökning) ───────
# Discipline och phase är hårdkodade här för testet — ändra om du vill testa
# en annan atlet.
DISCIPLINE = "sprint"
PHASE      = "uppbyggnad"

QUERIES = [
    f"{DISCIPLINE} {PHASE} träningsplanering veckoschema",
    f"{DISCIPLINE} intervallträning uthållighet nyckelpass",
    "återhämtning vilodag hard easy polariserad löpning",
    f"{PHASE} intensitetszoner 80 20 tröskelträning",
]

# ── Embeddingsmodell ────────────────────────────────────────────────────────
# Tränad på svenska, körs helt lokalt, gratis.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


# ===========================================================================
# CHUNKING (identisk med rag_knowledge.py)
# ===========================================================================

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r'--- Sida \d+ ---', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            bp = text.rfind('.', start + chunk_size // 2, end)
            if bp == -1:
                bp = text.rfind('\n', start + chunk_size // 2, end)
            if bp > start:
                end = bp + 1
        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def load_knowledge_base() -> tuple[list[str], list[str]]:
    """Returnerar (chunks, källnamn per chunk)."""
    all_chunks, all_sources = [], []
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print(f"❌ Hittade inte knowledge_base-mappen: {KNOWLEDGE_BASE_DIR}")
        sys.exit(1)

    files_found = [f for f in os.listdir(KNOWLEDGE_BASE_DIR) if f.endswith('.txt')]
    if not files_found:
        print(f"❌ Inga .txt-filer i {KNOWLEDGE_BASE_DIR}")
        sys.exit(1)

    for filename in sorted(files_found):
        filepath = os.path.join(KNOWLEDGE_BASE_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()
        chunks = chunk_text(text)
        all_chunks.extend(chunks)
        all_sources.extend([filename] * len(chunks))
        print(f"  📄 {filename}: {len(chunks)} chunks")

    print(f"  Totalt: {len(all_chunks)} chunks från {len(files_found)} filer\n")
    return all_chunks, all_sources


# ===========================================================================
# TF-IDF RETRIEVAL
# ===========================================================================

def build_tfidf(chunks: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    vectorizer = TfidfVectorizer(
        max_features=5000,
        ngram_range=(1, 2),
        stop_words=None,
        min_df=2,
        max_df=0.8,
    )
    matrix = vectorizer.fit_transform(chunks)
    return vectorizer, matrix


def search_tfidf(query: str, vectorizer, matrix, chunks, sources, top_k=TOP_K) -> list[dict]:
    from sklearn.metrics.pairwise import cosine_similarity
    q_vec = vectorizer.transform([query])
    sims  = cosine_similarity(q_vec, matrix).flatten()
    idxs  = sims.argsort()[-(top_k * 3):][::-1]
    results = []
    seen = set()
    for idx in idxs:
        if sims[idx] <= 0.05:
            continue
        text = chunks[idx]
        if text in seen:
            continue
        seen.add(text)
        results.append({"text": text, "score": float(sims[idx]), "source": sources[idx]})
        if len(results) >= top_k:
            break
    return results


# ===========================================================================
# EMBEDDINGS RETRIEVAL
# ===========================================================================

def build_embeddings(chunks: list[str]):
    print(f"  Laddar embeddingsmodell '{EMBEDDING_MODEL}' (kan ta 30–60 sek första gången)...")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("\n❌ sentence-transformers saknas.")
        print("   Installera med:  pip install sentence-transformers\n")
        sys.exit(1)

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"  Genererar embeddings för {len(chunks)} chunks...")
    embeddings = model.encode(chunks, show_progress_bar=True, batch_size=64)
    print()
    return model, embeddings


def search_embeddings(query: str, model, embeddings, chunks, sources, top_k=TOP_K) -> list[dict]:
    import numpy as np
    q_emb = model.encode([query])
    # Cosine similarity manuellt (undviker ytterligare beroende)
    q_norm   = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-10)
    c_norms  = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10
    c_normed = embeddings / c_norms
    sims     = (c_normed @ q_norm.T).flatten()
    idxs     = sims.argsort()[::-1]
    results  = []
    seen     = set()
    for idx in idxs:
        text = chunks[idx]
        if text in seen:
            continue
        seen.add(text)
        results.append({"text": text, "score": float(sims[idx]), "source": sources[idx]})
        if len(results) >= top_k:
            break
    return results


# ===========================================================================
# UTSKRIFT
# ===========================================================================

SEPARATOR = "═" * 80
DIVIDER   = "─" * 80

def short(text: str, max_chars: int = 220) -> str:
    """Visa ett kort utdrag av chunken."""
    t = text.replace('\n', ' ').strip()
    return t[:max_chars] + "…" if len(t) > max_chars else t


def print_results_side_by_side(query: str, tfidf_res: list[dict], emb_res: list[dict]):
    print(f"\n{SEPARATOR}")
    print(f"  FRÅGA: \"{query}\"")
    print(SEPARATOR)

    tfidf_texts = {r["text"] for r in tfidf_res}
    emb_texts   = {r["text"] for r in emb_res}
    shared      = tfidf_texts & emb_texts
    only_tfidf  = tfidf_texts - emb_texts
    only_emb    = emb_texts   - tfidf_texts

    max_len = max(len(tfidf_res), len(emb_res))
    for i in range(max_len):
        print(f"\n  Plats #{i+1}")
        print(f"  {DIVIDER}")

        # TF-IDF
        if i < len(tfidf_res):
            r = tfidf_res[i]
            tag = "✅ GEMENSAM" if r["text"] in shared else "🔵 UNIK FÖR TF-IDF"
            print(f"  TF-IDF  [{r['score']:.3f}]  {r['source']}  {tag}")
            print(f"  \"{short(r['text'])}\"")
        else:
            print(f"  TF-IDF  — (färre än {i+1} resultat)")

        print()

        # Embeddings
        if i < len(emb_res):
            r = emb_res[i]
            tag = "✅ GEMENSAM" if r["text"] in shared else "🟢 UNIK FÖR EMBEDDINGS"
            print(f"  EMBED   [{r['score']:.3f}]  {r['source']}  {tag}")
            print(f"  \"{short(r['text'])}\"")
        else:
            print(f"  EMBED   — (färre än {i+1} resultat)")

    print(f"\n  {DIVIDER}")
    print(f"  Gemensamma chunks: {len(shared)}/{TOP_K}  |  "
          f"Unika TF-IDF: {len(only_tfidf)}  |  "
          f"Unika Embeddings: {len(only_emb)}")


def print_summary(all_tfidf: list[list[dict]], all_emb: list[list[dict]]):
    print(f"\n{SEPARATOR}")
    print("  SAMMANFATTNING ÖVER ALLA FRÅGOR")
    print(SEPARATOR)

    total_shared = 0
    total_only_tfidf = 0
    total_only_emb = 0

    for t_res, e_res in zip(all_tfidf, all_emb):
        t_texts = {r["text"] for r in t_res}
        e_texts = {r["text"] for r in e_res}
        total_shared      += len(t_texts & e_texts)
        total_only_tfidf  += len(t_texts - e_texts)
        total_only_emb    += len(e_texts - t_texts)

    print(f"\n  Totalt unika chunks TF-IDF valde:   "
          f"{total_shared + total_only_tfidf}")
    print(f"  Totalt unika chunks Embeddings valde:"
          f" {total_shared + total_only_emb}")
    print(f"  Gemensamt valda chunks:               {total_shared}")
    print(f"  Chunks enbart TF-IDF hittade:         {total_only_tfidf}")
    print(f"  Chunks enbart Embeddings hittade:     {total_only_emb}")
    print()

    overlap_pct = total_shared / (total_shared + total_only_tfidf + total_only_emb) * 100
    print(f"  Överlapp: {overlap_pct:.0f}% av alla valda chunks är identiska mellan metoderna.")
    if overlap_pct >= 70:
        print("  → Metoderna är mycket lika — liten praktisk skillnad att vänta.")
    elif overlap_pct >= 40:
        print("  → Metoderna skiljer sig märkbart — embeddings hittar annan text.")
    else:
        print("  → Stor skillnad — embeddings och TF-IDF prioriterar helt olika chunks.")
    print()


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("\n" + SEPARATOR)
    print("  TF-IDF  vs  EMBEDDINGS  —  Chunk-jämförelse")
    print(f"  Discipline: {DISCIPLINE}  |  Fas: {PHASE}  |  Top-K: {TOP_K}")
    print(SEPARATOR + "\n")

    # Ladda kunskapsbas
    print("📚 Laddar kunskapsbas...")
    chunks, sources = load_knowledge_base()

    # Bygg TF-IDF
    print("🔢 Bygger TF-IDF-index...")
    vectorizer, tfidf_matrix = build_tfidf(chunks)
    print(f"   {tfidf_matrix.shape[1]} features\n")

    # Bygg Embeddings
    print("🧠 Bygger embeddings-index...")
    emb_model, embeddings = build_embeddings(chunks)

    # Kör jämförelse per fråga
    all_tfidf_results = []
    all_emb_results   = []

    for query in QUERIES:
        t_res = search_tfidf(query, vectorizer, tfidf_matrix, chunks, sources)
        e_res = search_embeddings(query, emb_model, embeddings, chunks, sources)
        all_tfidf_results.append(t_res)
        all_emb_results.append(e_res)
        print_results_side_by_side(query, t_res, e_res)

    # Sammanfattning
    print_summary(all_tfidf_results, all_emb_results)

    # Interaktivt läge: testa egna frågor
    print(SEPARATOR)
    print("  TESTA EGNA FRÅGOR  (skriv 'avsluta' för att stänga)")
    print(SEPARATOR)
    while True:
        try:
            q = input("\n  Skriv fråga: ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not q or q.lower() in ("avsluta", "exit", "quit"):
            break
        t_res = search_tfidf(q, vectorizer, tfidf_matrix, chunks, sources)
        e_res = search_embeddings(q, emb_model, embeddings, chunks, sources)
        print_results_side_by_side(q, t_res, e_res)

    print("\n  Klar. Ha det bra! 👋\n")


if __name__ == "__main__":
    main()
