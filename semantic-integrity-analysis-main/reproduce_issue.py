import sys
import os
import numpy as np
from sentence_transformers import SentenceTransformer, util

sys.path.append(os.getcwd())
try:
    from analysis.common_analyzer import analyze_pair
    from preprocessing.clause_extraction import extract_clauses
except ImportError:
    # Handle case where run from root
    sys.path.append(os.path.join(os.getcwd(), 'analysis'))
    sys.path.append(os.path.join(os.getcwd(), 'preprocessing'))
    from analysis.common_analyzer import analyze_pair
    from preprocessing.clause_extraction import extract_clauses

def test_reproduction():
    print("--- Section 1: Core Logic Test ---")
    t1 = "Audit reports must be retained for a minimum of three (3) years."
    t2 = "Audit reports shall be deleted after one (1) year to reduce storage overhead."

    print(f"Text 1: {t1}")
    print(f"Text 2: {t2}")

    # 1. Calculate Similarity
    print("Loading embedding model...")
    model = SentenceTransformer('all-MiniLM-L6-v2') 
    e1 = model.encode(t1)
    e2 = model.encode(t2)
    
    sim = util.cos_sim(e1, e2).item()
    print(f"Similarity Score: {sim:.4f}")
    
    # 2. Test analyze_pair
    print("Running analyze_pair...")
    label, conf, reason = analyze_pair(t1, t2, sim)
    print(f"Result: Label={label}, Conf={conf}, Reason={reason}")
    
    if label == "CANDIDATE":
        print("!!! PASSED Phase 1: ACCEPTED as CANDIDATE")
        
        # 3. Test NLI
        from analysis.nli_verifier import NLIVerifier
        print("\nRunning NLI Verification (Phase 2)...")
        verifier = NLIVerifier()
        is_contra, nli_conf, nli_label = verifier.predict(t1, t2)
        print(f"NLI Result: IsContra={is_contra}, Conf={nli_conf}, Label={nli_label}")
        
    elif label:
        print(f"!!! PASSED Phase 1: ACCEPTED as {label} (No NLI needed usually, but logic might vary)")
    else:
        print("!!! PASSED Phase 1: REJECTED (None)")

    print("\n--- Section 2: Pipeline & Metadata Test ---")
    mock_text = [
        {"text": "Section 1. This is a test clause on page 1.", "page": 1},
        {"text": "Section 2. This is another clause on page 2.", "page": 2}
    ]
    print("Testing extract_clauses with structured input...")
    clauses = extract_clauses(mock_text)
    if len(clauses) > 0 and 'page' in clauses[0] and 'line' in clauses[0]:
        print(f"SUCCESS: Extracted {len(clauses)} clauses with metadata.")
        print(f"Sample: {clauses[0]}")
    else:
        print("FAIL: Metadata extraction failed.")


if __name__ == "__main__":
    test_reproduction()
