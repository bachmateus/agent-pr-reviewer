"""Calculadora de exemplo para o comando review-diff."""

def divide(a, b):
    return a / b


def parse_number(text):
    try:
        return float(text)
    except:
        return 0


def average(values):
    return divide(sum(values), len(values))
