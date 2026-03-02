from ingestion.pdf_reader import extract_text_from_pdf
from preprocessing.clause_extraction import extract_clauses
from embeddings.sbert_encoder import generate_embeddings
from storage.faiss_index import create_faiss_index
from analysis.similarity_search import get_similar
from analysis.common_analyzer import analyze_pair
from output.report_generator import generate_report
import numpy as np

# Load document
text = extract_text_from_pdf("data/sample_docs/policy.pdf")

# Clause extraction
clauses = extract_clauses(text)

# Embeddings
embeddings = generate_embeddings(clauses)
index = create_faiss_index(embeddings)

results = []

for i, emb in enumerate(embeddings):
    idxs, dists = get_similar(index, emb)
    for j, dist in zip(idxs, dists):
        if i == j:
            continue


        similarity = 1 / (1 + dist)

        # Use new Common Analyzer (Centralized Logic)
        issue_type, score = analyze_pair(clauses[i]["text"], clauses[j]["text"], similarity)

        if issue_type:
            results.append({
                "type": issue_type,
                "confidence": score,
                "clause_1": clauses[i]["text"],
                "clause_2": clauses[j]["text"]
            })

generate_report(results)
print("✅ Analysis completed. Report generated.")
