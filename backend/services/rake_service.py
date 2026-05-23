"""
services/rake_service.py
Cálculo y registro del rake.
Separado para facilitar ajustes futuros sin tocar el motor.
"""

import config


def calculate_rake(pot: int) -> int:
    """
    Calcula el rake sobre el pot.
    Aplica RAKE_RATE con techo en RAKE_CAP.
    Siempre devuelve entero (centavos).
    """
    raw = int(pot * config.RAKE_RATE)
    cap = int(pot * config.RAKE_CAP)
    return min(raw, cap)


def breakdown(pot: int) -> dict:
    """
    Desglose completo para mostrar al usuario o registrar.
    """
    rake = calculate_rake(pot)
    return {
        "pot": pot,
        "rake": rake,
        "rake_rate": config.RAKE_RATE,
        "winner_receives": pot - rake,
    }
