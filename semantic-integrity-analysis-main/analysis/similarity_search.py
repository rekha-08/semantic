def get_similar(index, vector, k=5):
    distances, indices = index.search(vector.reshape(1, -1), k)
    return indices[0], distances[0]
