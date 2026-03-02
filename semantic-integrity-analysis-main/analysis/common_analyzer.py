"""
Strict Domain Analyzer for Legal Documents.
Implements specific checks for:
- Entity Roles (Vendor vs Vendee)
- Domain Categories (Financial, Possession, Ownership, etc.)
- Timeline Logic (Agreement vs Registration)
- Numeric Consistency within context
"""

import re

# =========================
# 1. STRICT CLASSIFICATION
# =========================

def is_legal_boilerplate(text):
    """Detects standard legal headers, footers, and witness blocks."""
    t = text.lower()
    patterns = [
        "in witness whereof", "signed and delivered", "witnesses:", 
        "schedule", "jurisdiction", "arbitration", "notice",
        "all that piece and parcel", "north by", "south by"
    ]
    # If it's very short (< 5 words) and contains a keyword
    words = t.split()
    if len(words) < 5 and any(p in t for p in patterns):
        return True
    
    # If it's just a signature block
    if "signed by" in t or "witness" in t:
        return True
        
    return False

def get_clause_domain(text):
    """
    Classify clause into strict legal domains.
    Returns: 'FINANCIAL', 'POSSESSION', 'OWNERSHIP', 'ENCUMBRANCE', 'ADMINISTRATIVE', 'RECITAL', 'DEFINITION', 'OPERATIVE' or 'GENERAL'
    """
    t = text.lower()
    
    # 1. RECITAL (Background)
    if t.startswith("whereas") or "and whereas" in t:
        return "RECITAL"
        
    # 2. DEFINITION
    if "shall mean" in t or "expression vendor" in t or "expression vendee" in t:
        return "DEFINITION"

    # 3. FINANCIAL (Money, Consideration)
    if any(w in t for w in ["rs.", "rupees", "paid", "consideration", "sum of", "amount", "price", "cheque", "bank"]):
        return "FINANCIAL"

    # 4. POSSESSION (Handover, Vacant)
    if any(w in t for w in ["possession", "handed over", "delivered", "vacant"]):
        return "POSSESSION"

    # 5. OWNERSHIP / TITLE
    if any(w in t for w in ["owner", "title", "interest", "rights", "absolute", "fee simple"]):
        return "OWNERSHIP"
        
    # 6. ENCUMBRANCE (Loans, Mortgages)
    if any(w in t for w in ["encumbrance", "mortgage", "loan", "charge", "lien", "litigation"]):
        return "ENCUMBRANCE"
        
    # 7. ADMINISTRATIVE (Boilerplate)
    if any(w in t for w in ["witness", "signed", "schedule", "jurisdiction", "arbitration", "notice"]):
        return "ADMINISTRATIVE"

    # 8. OPERATIVE (Action)
    if t.startswith("that") or "hereby" in t or "now this deed" in t:
        return "OPERATIVE"

    return "GENERAL"

def get_entities(text):
    """
    Strictly detect if clause belongs to a specific entity.
    """
    t = text.lower()
    entities = set()
    if "vendor" in t: entities.add("Vendor")
    if "vendee" in t: entities.add("Vendee")
    return entities

# =========================
# 2. EXTRACTION HELPERS
# =========================

def extract_numbers(text):
    """Extract numeric values for comparison."""
    # Matches Rs. 100, 1,00,000, 500 sq ft (just the numbers)
    return [int(n.replace(",", "")) for n in re.findall(r'\b\d{1,3}(?:,\d{3})*\b', text)]

def has_negation(text):
    neg_words = ["not", "never", "no", "cannot", "must not", "shall not"]
    return any(w in text.lower() for w in neg_words)

def has_exception_language(text):
    """Detects legal exception/qualification identifiers."""
    qualifiers = [
        "subject to", "notwithstanding", "except as provided", 
        "unless otherwise", "provided however", "without prejudice"
    ]
    return any(q in text.lower() for q in qualifiers)

def is_definition(text):
    """Strictly checks if a clause is a definition."""
    t = text.lower()
    if "shall mean" in t or "means" in t or "defined as" in t:
        return True
    return False

def is_party_intro(text):
    """Detects if a clause is just listing a party description."""
    t = text.lower()
    
    # Strong Indicators: Address patterns, Relations, IDs
    # Regex for "Door No", "D.No", "residing at"
    address_pattern = r"(door\s*no|d\.no|residing\s*at|post\s*,\s*village)"
    
    # Regex for relations: "son of", "wife of", "daughter of", "w/o", "s/o", or just "son", "wife" in context
    relation_pattern = r"\b(son|wife|daughter|husband|father|mother|s/o|w/o|d/o)\b"
    
    # Regex for IDs: "aadhaar", "pan no", "id card"
    id_pattern = r"(aadhaar|pan\s*no|id\s*card|mobile\s*no)"
    
    # Check for presence of these patterns
    has_address = re.search(address_pattern, t)
    has_relation = re.search(relation_pattern, t)
    has_id = re.search(id_pattern, t)
    
    # If it has at least 2 strong components (e.g. Relation + ID, or Address + Relation), it's a bio
    score = 0
    if has_address: score += 1
    if has_relation: score += 1
    if has_id: score += 1
    
    return score >= 2

# =========================
# 3. CORE LOGIC GATES
# =========================

def analyze_pair(text1, text2, similarity, threshold=0.75):
    """
    Strict Analyzer returning (Label, Score, Reason).
    Args:
        threshold: Minimum similarity score to consider as CANDIDATE (default 0.75)
    """
    # Force Reload Trigger
    
    # --- GATE 0: BOILERPLATE CHECK ---
    if is_legal_boilerplate(text1) or is_legal_boilerplate(text2):
        return None, 0.0, "Boilerplate (Skipped)"

    # --- GATE 1: DOMAIN MISMATCH ---
    d1 = get_clause_domain(text1)
    d2 = get_clause_domain(text2)
    
    # If domains are totally different, SKIP.
    # Exception: OPERATIVE and GENERAL might overlap, but strictly FINANCIAL vs POSSESSION should skip.
    if d1 != "GENERAL" and d2 != "GENERAL" and d1 != d2:
        # RELAXATION: Only bypass if similarity is VERY high (suggesting misclassification).
        # Otherwise, DO NOT compare apples (Financial) to oranges (Possession), 
        # even in Deep Search mode.
        if similarity < 0.85:
            return None, 0.0, "Domain Mismatch"

    # --- HARDENED CHECK: GENERAL vs SPECIFIC ---
    # Common source of noise: "Any other details" matching "The price is Rs 100"
    # Block GENERAL vs Specific unless similarity is high
    if (d1 == "GENERAL" and d2 != "GENERAL") or (d2 == "GENERAL" and d1 != "GENERAL"):
        if similarity < 0.80:
             return None, 0.0, "General vs Specific Domain (Skipped)"

    # --- SPECIFIC FILTER: MONEY vs TIMELINE ---
    # Prevents "Price is X" vs "Payment due on Date Y" (confusing numbers/dates)
    # Check if one clause is purely FINANCIAL and other is purely TIMELINE/DATE based
    is_financial = d1 == "FINANCIAL" or d2 == "FINANCIAL"
    has_date = re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text1) or \
               re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text2)
    
    if is_financial and has_date:
        # If one talks about Price/Amount and other has a Date, 
        # unless they are explicitly about "Payment Schedule", they are likely different.
        if "schedule" not in text1.lower() and "schedule" not in text2.lower():
             if similarity < 0.85:
                 return None, 0.0, "Financial vs Timeline Mismatch"

    # --- SPECIFIC FILTER: ELIGIBILITY vs ASSISTANCE ---
    # Prevents "Eligibility criteria" vs "Assistance details" (Common in schemes)
    # Check for keywords like "eligible", "qualify" vs "grant", "support", "help"
    t1_lower, t2_lower = text1.lower(), text2.lower()
    is_eligibility = any(w in t1_lower for w in ["eligible", "qualify", "criteria", "requirement"]) or \
                     any(w in t2_lower for w in ["eligible", "qualify", "criteria", "requirement"])
    is_assistance = any(w in t1_lower for w in ["provide", "grant", "subsidy", "support", "assistance"]) or \
                    any(w in t2_lower for w in ["provide", "grant", "subsidy", "support", "assistance"])

    if is_eligibility and is_assistance:
         # Unless precise overlap, these are distinct sections
         if similarity < 0.85:
              return None, 0.0, "Eligibility vs Assistance Mismatch"

    # --- GATE 1.5: PARTY DESCRIPTION CHECK ---
    # If both clauses are just descriptions of people (addresses, relations), skip.
    if is_party_intro(text1) and is_party_intro(text2):
        return None, 0.0, "Party Description (Skipped)"

    # --- GATE 2: ENTITY MISMATCH ---
    e1 = get_entities(text1)
    e2 = get_entities(text2)
    # If one is Vendor ONLY and other is Vendee ONLY -> SKIP
    if e1 and e2 and e1 != e2 and not (e1 & e2):
        # RELAXATION: Only bypass if similarity is VERY high.
        if similarity < 0.85:
            return None, 0.0, "Entity Role Mismatch"
    
    # --- GATE 2.5: DEFINITION GUARD ---
    # Don't compare definitions with operative clauses generally
    if is_definition(text1) or is_definition(text2):
        # Only compare if both are definitions (conflicting definitions)
        if not (is_definition(text1) and is_definition(text2)):
             return None, 0.0, "Definition vs Operative"

    # --- GATE 3: POSSESSION TIMELINE ---
    # "Possession at agreement" vs "Possession at registration" is NOT a contradiction.
    if d1 == "POSSESSION" and d2 == "POSSESSION":
        keywords_a = ["agreement", "earnest"]
        keywords_b = ["registration", "sale deed", "final"]
        
        has_a = any(k in text1.lower() for k in keywords_a)
        has_b = any(k in text2.lower() for k in keywords_b)
        
        # If one talks about start and other about end, it's a sequence.
        if (has_a and any(k in text2.lower() for k in keywords_b)) or \
           (has_b and any(k in text1.lower() for k in keywords_a)):
             return None, 0.0, "Possession Timeline Sequence"

    # --- GATE 4: NUMERIC REASONING ---
    # Only compare numbers if context allows
    nums1 = extract_numbers(text1)
    nums2 = extract_numbers(text2)
    
    if nums1 and nums2 and nums1 != nums2:
        # MAGNITUDE CHECK: If numbers differ by > 100x, likely different units (e.g. Price vs Area)
        # e.g. 5,50,000 vs 1.25 -> Ratio is huge.
        max1, max2 = max(nums1), max(nums2)
        if max1 > 0 and max2 > 0:
            ratio = max1 / max2 if max1 > max2 else max2 / max1
            if ratio > 100:
                 return None, 0.0, "Numeric Magnitude Mismatch (Likely Unit Diff)"

        # Check if they are in the same domain (likely valid comparison)
        if d1 == d2 and d1 != "GENERAL":
             return "NUMERIC_INCONSISTENCY", 0.9, f"Mismatch in {d1} values"
        
        # If General, be careful. 
        # But if similarity is VERY high, it might be a contradiction.
        if similarity > 0.9:
             return "NUMERIC_INCONSISTENCY", 0.85, "Numeric Mismatch in similar context"

    # --- GATE 4.5: EXCEPTION/HIERARCHY CHECK ---
    # If high similarity but one has exception language
    # We use a slightly lower threshold for exception detection to be safe
    exception_threshold = max(0.65, threshold - 0.05)
    if similarity > exception_threshold: 
        has_ex1 = has_exception_language(text1)
        has_ex2 = has_exception_language(text2)
        
        if (has_ex1 and not has_ex2) or (has_ex2 and not has_ex1):
            return "QUALIFICATION", similarity, "Legal Exception/Qualification detected (Not a Conflict)"

    # --- GATE 5: LOGICAL NEGATION ---
    if (has_negation(text1) and not has_negation(text2)) or \
       (has_negation(text2) and not has_negation(text1)):
        # Only flag if high similarity implies they are talking about the same thing
        # Negation check requires fairly high confidence they are related
        if similarity > 0.85:
            return "LEGAL_CONFLICT", 0.8, "Logical Negation detected"

    # --- FINAL GATE: CANDIDATE FOR NLI ---
    # If we are here, we passed the blocks. 
    # If similarity is high, let NLI decide.
    if similarity > threshold: 
        return "CANDIDATE", similarity, "High Similarity - Pending NLI"
        
    return None, 0.0, "Low Similarity"
