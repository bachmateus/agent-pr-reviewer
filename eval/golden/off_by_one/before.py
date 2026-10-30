def ultimos(itens, n):
    return itens[-n:] if n > 0 else []


def pares(itens):
    return [itens[i] for i in range(0, len(itens), 2)]
