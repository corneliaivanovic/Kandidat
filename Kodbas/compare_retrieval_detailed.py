"""
compare_retrieval_detailed.py
============================
Spara en detaljerad jämförelse till fil så du kan läsa genom alla chunks i full längd.

Kör:
    python compare_retrieval_detailed.py

Skapar: comparison_results_detailed.txt i samma mapp
"""

import os
import re
import sys

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150
TOP_K         = 8
DISCIPLINE = "medeldistans"
PHASE      = "uppbyggnad"
QUERIES = [
    f"{DISCIPLINE} {PHASE} träningsplanering veckoschema",
    f"{DISCIPLINE} tröskelpass uthållighet nyckelpass",
    "återhämtning vilodag hard easy polariserad löpning",
    f"{PHASE} intensitetszoner 80 20 tröskelträning",
]
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comparison_results_detailed.txt")


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
        results.append({"text": text, "score": float(sims[idx]), "source": sources[idx], "idx": idx})
        if len(results) >= top_k:
            break
    return results


def build_embeddings(chunks: list[str]):
    print(f"  Laddar embeddingsmodell '{EMBEDDING_MODEL}'...")
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
        results.append({"text": text, "score": float(sims[idx]), "source": sources[idx], "idx": idx})
        if len(results) >= top_k:
            break
    return results


def main():
    print("\n" + "="*80)
    print("  TF-IDF  vs  EMBEDDINGS  —  Detaljerad jämförelse")
    print(f"  Discipline: {DISCIPLINE}  |  Fas: {PHASE}")
    print("="*80 + "\n")

    # Ladda och indexera
    print("📚 Laddar kunskapsbas...")
    chunks, sources = load_knowledge_base()

    print("🔢 Bygger TF-IDF-index...")
    vectorizer, tfidf_matrix = build_tfidf(chunks)
    print(f"   {tfidf_matrix.shape[1]} features\n")

    print("🧠 Bygger embeddings-index...")
    emb_model, embeddings = build_embeddings(chunks)

    # Öppna output-fil
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out:
        out.write("="*80 + "\n")
        out.write("TF-IDF vs EMBEDDINGS — DETALJERAD JÄMFÖRELSE\n")
        out.write("="*80 + "\n\n")

        all_tfidf_results = []
        all_emb_results   = []

        # Kör alla frågor
        for query_num, query in enumerate(QUERIES, 1):
            t_res = search_tfidf(query, vectorizer, tfidf_matrix, chunks, sources)
            e_res = search_embeddings(query, emb_model, embeddings, chunks, sources)
            all_tfidf_results.append(t_res)
            all_emb_results.append(e_res)

            out.write("\n" + "="*80 + "\n")
            out.write(f"FRÅGA {query_num}: \"{query}\"\n")
            out.write("="*80 + "\n\n")

            # Jämför
            tfidf_texts = {r["text"] for r in t_res}
            emb_texts   = {r["text"] for r in e_res}
            shared      = tfidf_texts & emb_texts
            only_tfidf  = tfidf_texts - emb_texts
            only_emb    = emb_texts   - tfidf_texts

            # Statistik
            out.write(f"Gemensamma chunks: {len(shared)}\n")
            out.write(f"Unika TF-IDF:      {len(only_tfidf)}\n")
            out.write(f"Unika Embeddings:  {len(only_emb)}\n")
            out.write("-" * 80 + "\n\n")

            # Visa varje position side-by-side
            max_len = max(len(t_res), len(e_res))
            for i in range(max_len):
                out.write(f"\nPLATS #{i+1}\n")
                out.write("-" * 80 + "\n\n")

                # TF-IDF
                if i < len(t_res):
                    r = t_res[i]
                    tag = "✅ GEMENSAM" if r["text"] in shared else "🔵 UNIK FÖR TF-IDF"
                    out.write(f"TF-IDF [score: {r['score']:.4f}]  Källa: {r['source']}  {tag}\n")
                    out.write(f"{'─'*80}\n")
                    out.write(f"{r['text']}\n\n")
                else:
                    out.write(f"TF-IDF — (färre än {i+1} resultat)\n\n")

                # Embeddings
                if i < len(e_res):
                    r = e_res[i]
                    tag = "✅ GEMENSAM" if r["text"] in shared else "🟢 UNIK FÖR EMBEDDINGS"
                    out.write(f"EMBEDDINGS [score: {r['score']:.4f}]  Källa: {r['source']}  {tag}\n")
                    out.write(f"{'─'*80}\n")
                    out.write(f"{r['text']}\n\n")
                else:
                    out.write(f"EMBEDDINGS — (färre än {i+1} resultat)\n\n")

        # Sammanfattning
        out.write("\n" + "="*80 + "\n")
        out.write("SAMMANFATTNING ÖVER ALLA FRÅGOR\n")
        out.write("="*80 + "\n\n")

        total_shared = 0
        total_only_tfidf = 0
        total_only_emb = 0

        for t_res, e_res in zip(all_tfidf_results, all_emb_results):
            t_texts = {r["text"] for r in t_res}
            e_texts = {r["text"] for r in e_res}
            total_shared      += len(t_texts & e_texts)
            total_only_tfidf  += len(t_texts - e_texts)
            total_only_emb    += len(e_texts - t_texts)

        union_total = total_shared + total_only_tfidf + total_only_emb
        out.write(f"Totalt antal distinkta chunks TF-IDF valde:     {total_shared + total_only_tfidf}\n")
        out.write(f"Totalt antal distinkta chunks Embeddings valde: {total_shared + total_only_emb}\n")
        out.write(f"Chunks valda av båda metoderna:                 {total_shared}\n")
        out.write(f"Chunks valda enbart av TF-IDF:                  {total_only_tfidf}\n")
        out.write(f"Chunks valda enbart av Embeddings:              {total_only_emb}\n")
        out.write(f"Union av valda chunks (totalt antal segment):   {union_total}\n\n")

        if union_total > 0:
            overlap_pct = total_shared / union_total * 100
            out.write(f"Överlapp: {overlap_pct:.0f}% av unionen av valda chunks är gemensamma mellan metoderna.\n\n")
            if overlap_pct >= 70:
                out.write("→ Metoderna är mycket lika — liten praktisk skillnad.\n")
            elif overlap_pct >= 40:
                out.write("→ Metoderna skiljer sig märkbart — embeddings hittar annan text.\n")
            else:
                out.write("→ Stor skillnad — embeddings och TF-IDF prioriterar helt olika chunks.\n")

    print(f"\n✅ Detaljerade resultat sparade till: {OUTPUT_FILE}")
    print(f"   Öppna filen i en texteditor för att läsa genom alla chunks i full längd.\n")


if __name__ == "__main__":
    main()
