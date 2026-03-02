import re

def extract_number(text):
    match = re.search(r'INR\s*([\d,]+)', text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None

def numeric_contradiction(text1, text2):
    n1 = extract_number(text1)
    n2 = extract_number(text2)
    return n1 is not None and n2 is not None and n1 != n2

def ownership_contradiction(text1, text2):
    t1 = text1.lower()
    t2 = text2.lower()
    return (
        ("must not own" in t1 and "may be eligible" in t2) or
        ("must not own" in t2 and "may be eligible" in t1)
    )

def check_contradiction(text1, text2):
    return numeric_contradiction(text1, text2) or ownership_contradiction(text1, text2)
