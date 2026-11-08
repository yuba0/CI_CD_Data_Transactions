"""Résultats attendus, calculés À LA MAIN à partir de pipeline/generate.py.

Ils ne sont volontairement PAS recalculés avec le code de la pipeline :
sinon un bug du traitement serait reproduit dans l'attendu et passerait inaperçu.
"""
from decimal import Decimal as D

FR1 = "FR7610001000010000000000001"
FR3 = "FR7610001000010000000000003"
FR2 = "FR7610002000020000000000002"
DE1 = "DE89370400440532013000"
ES1 = "ES9121000418450200051332"
IT1 = "IT60X0542811101000000123456"

FILES = {
    "transactions_2026-01-01.csv": 5,
    "transactions_2026-01-02.csv": 6,
    "transactions_2026-01-03.csv": 7,
}
TOTAL_TRANSACTIONS = 18
TOTAL_AMOUNT = D("60951.24")

SENT_BY_IBAN = {
    FR1: D("15150.00"),   # 1200 + 300 + 8000 + 150 + 5500
    FR2: D("12350.75"),   # 5000 + 450.75 + 6200 + 700
    DE1: D("20500.50"),   # 7500.50 + 1000 + 12000
    ES1: D("7600.00"),    # 5000.01 + 99.99 + 2500
    IT1: D("5249.99"),    # 250 + 4999.99
    FR3: D("100.00"),
}

SENT_BY_BANK = {
    "Banque Alpha": D("15250.00"),    # FR1 + FR3
    "Banque Beta": D("12350.75"),
    "Banque Gamma": D("20500.50"),
    "Banque Delta": D("7600.00"),
    "Banque Epsilon": D("5249.99"),
}

RECEIVED_BY_IBAN = {
    DE1: D("12250.73"),   # 1200 + 450.75 + 99.99 + 4999.99 + 5500
    FR1: D("16450.50"),   # 7500.50 + 250 + 6200 + 2500
    ES1: D("25100.00"),   # 5000 + 8000 + 12000 + 100
    IT1: D("2000.00"),    # 300 + 1000 + 700
    FR2: D("5150.01"),    # 5000.01 + 150
}

# montants > 5000 (5000.00 pile n'est PAS flaggé, 5000.01 l'est)
FLAGGED_AMOUNTS = sorted(
    [D("7500.50"), D("5000.01"), D("8000.00"), D("6200.00"), D("12000.00"), D("5500.00")]
)
