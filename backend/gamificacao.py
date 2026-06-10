import os
import math
from datetime import datetime, date

# Dicionário de Patentes e XP mínimo necessário
TABELA_PATENTES = [
    (500000, "General Supremo"), (400000, "General de Exército"), (300000, "General de Divisão"),
    (220000, "General de Brigada"), (160000, "Coronel"), (110000, "Tenente-Coronel"),
    (750000, "Major"), (50000, "Capitão"), (35000, "1º Tenente"), (25000, "2º Tenente"),
    (18000, "Aspirante"), (12000, "Subtenente"), (8000, "1º Sargento"), (5000, "2º Sargento"),
    (3000, "3º Sargento"), (1500, "Cabo"), (500, "Soldado"), (0, "Recruta")
]

def calcular_patente(xp_atual):
    """Retorna a patente correspondente ao XP do usuário"""
    for xp_minimo, nome_patente in TABELA_PATENTES:
        if xp_atual >= xp_minimo:
            return nome_patente
    return "Recruta"

def processar_xp_simulado(percentual_acertos, completou_rapido, primeiro_do_dia):
    """Calcula o XP ganho em um simulado com base nas regras do Estado-Maior"""
    if percentual_acertos < 60:
        return 0, []

    xp_ganho = 0
    medalhas = []

    # Tabela Base
    if 60 <= percentual_acertos <= 69: xp_ganho += 50
    elif 70 <= percentual_acertos <= 79: xp_ganho += 100
    elif 80 <= percentual_acertos <= 89: xp_ganho += 150
    elif 90 <= percentual_acertos <= 100: xp_ganho += 250

    # Bônus
    if primeiro_do_dia:
        xp_ganho += 25
    if completou_rapido:
        xp_ganho += 25
    if percentual_acertos == 100:
        xp_ganho += 100
        medalhas.append("Atirador de Elite")

    return xp_ganho, medalhas

def processar_xp_redacao(nota_redacao, aprovadas_na_semana):
    """Calcula o XP ganho na correção da redação"""
    if nota_redacao < 400:
        return 0, []

    xp_ganho = 0
    medalhas = []

    # Tabela Base
    if 400 <= nota_redacao <= 599: xp_ganho += 100
    elif 600 <= nota_redacao <= 699: xp_ganho += 150
    elif 700 <= nota_redacao <= 799: xp_ganho += 250
    elif 800 <= nota_redacao <= 899: xp_ganho += 400
    elif 900 <= nota_redacao <= 1000: xp_ganho += 600

    # Bônus
    if aprovadas_na_semana >= 2:
        xp_ganho += 100
    if nota_redacao >= 900:
        medalhas.append("Escritor de Ouro")

    return xp_ganho, medalhas

def obter_feedback_militar(nota, tipo="simulado"):
    """Gera frase motivacional da IA com base no desempenho corporativo"""
    limite_alto = 900 if tipo == "redacao" else 85
    limite_medio = 600 if tipo == "redacao" else 60

    if nota >= limite_alto:
        return "Excelente desempenho! O Estado-Maior registrou sua evolução militar."
    elif nota >= limite_medio:
        return "Bom trabalho. Sua promoção de carreira está cada vez mais próxima."
    else:
        return "Continue avançando, soldado. A disciplina vence o talento quando o talento não se disciplina."