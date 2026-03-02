import torch
import numpy as np
from sentence_transformers import CrossEncoder
from huggingface_hub import login

class NLIVerifier:
    def __init__(self, model_name="cross-encoder/nli-distilroberta-base", hf_token=None):
        """
        Initialize the NLI model using CrossEncoder.
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading NLI Model ({self.device})...")
        
        if hf_token:
             try:
                 login(token=hf_token)
                 print("Logged in to Hugging Face.")
             except Exception as e:
                 print(f"HF Login Warning: {e}")

        try:
            self.model = CrossEncoder(model_name, device=self.device)
            print("NLI Model Loaded Successfully.")
        except Exception as e:
             print(f"Error loading model: {e}")
             self.model = None

        # Label mapping for cross-encoder/nli-distilroberta-base
        # 0: Contradiction
        # 1: Entailment
        # 2: Neutral
        self.labels = ["Contradiction", "Entailment", "Neutral"]

    def predict(self, text1, text2):
        """
        Verify if text1 and text2 contradict each other.
        Returns: (IsContradiction: bool, Confidence: float, Label: str)
        """
        if not self.model:
            return False, 0.0, "Model Error"

        # CrossEncoder returns logits
        scores = self.model.predict([(text1, text2)])[0]
        
        # Apply softmax to get probabilities
        exp_scores = np.exp(scores)
        probs = exp_scores / np.sum(exp_scores)
        
        pred_label_idx = probs.argmax()
        confidence = probs[pred_label_idx]
        label = self.labels[pred_label_idx]

        # Check if Contradiction (Index 0) is the winner with high confidence
        is_contradiction = (pred_label_idx == 0 and confidence > 0.5)

        return is_contradiction, float(confidence), label
