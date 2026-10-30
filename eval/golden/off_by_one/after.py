def ultimos(itens, n):
    return itens[-n:] if n > 0 else []


def pares(itens):
    resultado = []
    for i in range(len(itens) + 1):
        if i % 2 == 0:
            resultado.append(itens[i])
    return resultado
