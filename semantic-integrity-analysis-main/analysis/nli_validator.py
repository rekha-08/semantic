from transformers import pipeline

# Load once (slow only first time)
nli_pipeline = pipeline(
    "text-classification",
    model="roberta-large-mnli",
    device=-1  # CPU
)

def nli_contradiction(text1, text2, threshold=0.8):
    """
    Returns True if NLI model strongly predicts contradiction
    """
    input_text = f"{text1} </s></s> {text2}"
    result = nli_pipeline(input_text)[0]

    return (
        result["label"] == "CONTRADICTION" and
        result["score"] >= threshold
    )
