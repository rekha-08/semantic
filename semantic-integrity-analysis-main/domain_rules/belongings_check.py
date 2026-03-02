def belongings_conflict(text1, text2):
    t1 = text1.lower()
    t2 = text2.lower()
    if ("included" in t1 and "excluded" in t2) or \
       ("excluded" in t1 and "included" in t2):
        return True
    return False
