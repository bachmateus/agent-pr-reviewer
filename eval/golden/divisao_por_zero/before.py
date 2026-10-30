def media(valores):
    if not valores:
        return 0.0
    return sum(valores) / len(valores)
