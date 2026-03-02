import re

def extract_clauses(text_data):
    """
    Extracts clauses from text chunks with location data.
    Args:
        text_data: List[Dict] with 'text' and 'page' keys.
    Returns:
        List[Dict]: [{'id', 'text', 'page', 'line'}]
    """
    unique_clauses = []
    seen = set()
    clause_id = 0

    for chunk in text_data:
        raw_text = chunk.get("text", "")
        page_num = chunk.get("page", 1)
        
        # Split into lines first to track line numbers roughly
        # Or split by sentence and find position.
        
        # Simple approach: Split by sentence, then find approximate line number in chunk
        sentences = re.split(r'(?<=[.!?])\s+', raw_text)
        
        # Helper to find line number
        def get_line_number(substring, source_text):
            idx = source_text.find(substring)
            if idx == -1: return 1
            return source_text[:idx].count('\n') + 1

        for s in sentences:
            s_clean = s.strip()
            if len(s_clean) > 30 and s_clean not in seen:
                seen.add(s_clean)
                
                # Estimate line number within the page
                line_offset = get_line_number(s_clean, raw_text)
                
                unique_clauses.append({
                    "id": clause_id, 
                    "text": s_clean,
                    "page": page_num,
                    "line": line_offset
                })
                clause_id += 1
            
    return unique_clauses
