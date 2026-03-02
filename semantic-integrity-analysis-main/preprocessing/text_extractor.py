
import pdfplumber
import docx
import io

def extract_text_from_file(file_obj, file_type):
    """
    Extracts text from various file formats with page/location tracking.
    Args:
        file_obj: The uploaded file object (bytes).
        file_type: 'pdf', 'docx', or 'txt'.
    Returns:
        List[Dict]: List of {'text': str, 'page': int}
    """
    extracted_data = []
    try:
        if file_type == "pdf":
            with pdfplumber.open(file_obj) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        extracted_data.append({
                            "text": page_text,
                            "page": i + 1
                        })
        
        elif file_type == "docx":
            doc = docx.Document(file_obj)
            # DOCX doesn't have strict pages, so we'll treat paragraphs/sections
            # as a stream. We'll mark it as Page 1 for now, or maybe
            # increment 'page' every N paragraphs to simulate flow?
            # Better: Return logical sections.
            full_text = ""
            for para in doc.paragraphs:
                full_text += para.text + "\n"
            
            extracted_data.append({
                "text": full_text,
                "page": 1 # DOCX treated as single continuous flow unless paginated
            })
                
        elif file_type == "txt":
            # Assuming utf-8 encoding
            text = file_obj.read().decode("utf-8")
            extracted_data.append({
                "text": text,
                "page": 1
            })
            
    except Exception as e:
        print(f"Error extracting text: {e}")
        return []

    return extracted_data
