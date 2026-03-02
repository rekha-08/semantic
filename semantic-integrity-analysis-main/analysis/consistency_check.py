def check_inconsistency(text1, text2):
    keywords = ["shall", "must", "may"]
    return any(k in text1.lower() for k in keywords) and \
           any(k in text2.lower() for k in keywords)
