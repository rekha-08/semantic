import os
from sentence_transformers import SentenceTransformer

_model = None

def get_model():
    global _model
    if _model is None:
        model_name = "all-MiniLM-L6-v2"
        try:
            print(f"Loading {model_name}...")
            _model = SentenceTransformer(model_name)
        except Exception as e:
            print(f"Failed to load {model_name} online: {e}")
            print("Attempting to load from local cache...")
            try:
                _model = SentenceTransformer(model_name, local_files_only=True)
            except Exception as e2:
                raise RuntimeError(f"Could not load model {model_name} (Online or Offline). Check connection.") from e2
    return _model

def generate_embeddings(clauses):
    model = get_model()
    texts = [c["text"] for c in clauses]
    return model.encode(texts, convert_to_numpy=True)
