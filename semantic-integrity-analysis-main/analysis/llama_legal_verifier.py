import os
import re
from typing import Tuple

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline


class LlamaLegalVerifier:
    """
    Verifies whether two legal clauses are contradictory, entailing, or neutral
    using a local fine-tuned causal language model.
    """

    def __init__(self, model_path: str):
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"Model path not found: {model_path}")

        self.model_path = model_path
        self.device = 0 if torch.cuda.is_available() else -1
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32

        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            torch_dtype=dtype,
        )
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token_id = tokenizer.eos_token_id

        self.generator = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            device=self.device,
        )

    @staticmethod
    def _parse_label(text: str) -> str:
        lowered = text.lower()
        if "contradiction" in lowered:
            return "Contradiction"
        if "entailment" in lowered or "duplicate" in lowered or "same meaning" in lowered:
            return "Entailment"
        if "neutral" in lowered:
            return "Neutral"
        return "Neutral"

    @staticmethod
    def _parse_confidence(text: str) -> float:
        matches = re.findall(r"(?<!\d)(0(?:\.\d+)?|1(?:\.0+)?)(?!\d)", text)
        if matches:
            try:
                value = float(matches[0])
                return max(0.0, min(1.0, value))
            except ValueError:
                return 0.60
        return 0.60

    @staticmethod
    def _parse_reason(text: str) -> str:
        m = re.search(r"reason\s*:\s*(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()[:300]
        return text.strip()[:300]

    def predict(self, text1: str, text2: str) -> Tuple[bool, float, str, str]:
        prompt = f"""You are a legal NLI verifier.
Classify relationship between Clause A and Clause B.
Allowed labels: Contradiction, Entailment, Neutral.
Return exactly in this format:
Label: <Contradiction|Entailment|Neutral>
Confidence: <0.00-1.00>
Reason: <one short legal reason>

Clause A: {text1}
Clause B: {text2}
"""

        output = self.generator(
            prompt,
            max_new_tokens=96,
            do_sample=False,
            return_full_text=False,
            pad_token_id=self.generator.tokenizer.eos_token_id,
        )[0]["generated_text"]

        label = self._parse_label(output)
        confidence = self._parse_confidence(output)
        reason = self._parse_reason(output)
        is_contradiction = label == "Contradiction" and confidence >= 0.50
        return is_contradiction, confidence, label, reason
