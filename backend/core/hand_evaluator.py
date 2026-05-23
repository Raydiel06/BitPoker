"""
core/hand_evaluator.py
Evaluación de manos Texas Hold'em.
Dados 2 cartas del jugador + hasta 5 comunitarias,
determina la mejor mano de 5 y su ranking.
Sin dependencias externas.
"""

from collections import Counter
from itertools import combinations
from dataclasses import dataclass
from typing import Optional

from core.deck import Card


# ══════════════════════════════════════════════════════
#  RANKING DE MANOS (mayor = mejor)
# ══════════════════════════════════════════════════════

class HandRank:
    HIGH_CARD       = 1
    ONE_PAIR        = 2
    TWO_PAIR        = 3
    THREE_OF_A_KIND = 4
    STRAIGHT        = 5
    FLUSH           = 6
    FULL_HOUSE      = 7
    FOUR_OF_A_KIND  = 8
    STRAIGHT_FLUSH  = 9
    ROYAL_FLUSH     = 10

HAND_NAMES: dict[int, str] = {
    1:  "Carta Alta",
    2:  "Pareja",
    3:  "Doble Pareja",
    4:  "Trío",
    5:  "Escalera",
    6:  "Color",
    7:  "Full House",
    8:  "Póker",
    9:  "Escalera de Color",
    10: "Escalera Real",
}


# ══════════════════════════════════════════════════════
#  RESULTADO DE EVALUACIÓN
# ══════════════════════════════════════════════════════

@dataclass
class HandResult:
    rank: int                   # HandRank value
    name: str                   # Nombre legible
    best_five: list[Card]       # Las 5 cartas que forman la mano
    tiebreakers: list[int]      # Para resolver empates

    def __gt__(self, other: "HandResult") -> bool:
        if self.rank != other.rank:
            return self.rank > other.rank
        return self.tiebreakers > other.tiebreakers

    def __eq__(self, other: "HandResult") -> bool:
        return self.rank == other.rank and self.tiebreakers == other.tiebreakers

    def __lt__(self, other: "HandResult") -> bool:
        return not self.__gt__(other) and not self.__eq__(other)

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "name": self.name,
            "best_five": [c.to_dict() for c in self.best_five],
            "tiebreakers": self.tiebreakers,
        }


# ══════════════════════════════════════════════════════
#  EVALUACIÓN DE 5 CARTAS
# ══════════════════════════════════════════════════════

def _evaluate_five(cards: list[Card]) -> HandResult:
    """Evalúa exactamente 5 cartas y devuelve su HandResult."""
    assert len(cards) == 5

    values  = sorted([c.value for c in cards], reverse=True)
    suits   = [c.suit for c in cards]
    counts  = Counter(values)
    is_flush    = len(set(suits)) == 1
    is_straight = _is_straight(values)

    # Escalera Real
    if is_flush and is_straight and values[0] == 14 and values[4] == 10:
        return HandResult(HandRank.ROYAL_FLUSH, HAND_NAMES[10], cards, values)

    # Escalera de Color
    if is_flush and is_straight:
        return HandResult(HandRank.STRAIGHT_FLUSH, HAND_NAMES[9], cards, values)

    # Póker
    if 4 in counts.values():
        quad = [v for v, c in counts.items() if c == 4][0]
        kicker = [v for v in values if v != quad]
        return HandResult(HandRank.FOUR_OF_A_KIND, HAND_NAMES[8], cards, [quad] + kicker)

    # Full House
    if 3 in counts.values() and 2 in counts.values():
        trio = [v for v, c in counts.items() if c == 3][0]
        pair = [v for v, c in counts.items() if c == 2][0]
        return HandResult(HandRank.FULL_HOUSE, HAND_NAMES[7], cards, [trio, pair])

    # Color
    if is_flush:
        return HandResult(HandRank.FLUSH, HAND_NAMES[6], cards, values)

    # Escalera
    if is_straight:
        return HandResult(HandRank.STRAIGHT, HAND_NAMES[5], cards, values)

    # Trío
    if 3 in counts.values():
        trio = [v for v, c in counts.items() if c == 3][0]
        kickers = sorted([v for v in values if v != trio], reverse=True)
        return HandResult(HandRank.THREE_OF_A_KIND, HAND_NAMES[4], cards, [trio] + kickers)

    # Doble Pareja
    pairs = sorted([v for v, c in counts.items() if c == 2], reverse=True)
    if len(pairs) == 2:
        kicker = [v for v in values if v not in pairs]
        return HandResult(HandRank.TWO_PAIR, HAND_NAMES[3], cards, pairs + kicker)

    # Pareja
    if len(pairs) == 1:
        kickers = sorted([v for v in values if v != pairs[0]], reverse=True)
        return HandResult(HandRank.ONE_PAIR, HAND_NAMES[2], cards, pairs + kickers)

    # Carta Alta
    return HandResult(HandRank.HIGH_CARD, HAND_NAMES[1], cards, values)


def _is_straight(values: list[int]) -> bool:
    """Detecta escalera incluyendo el caso especial A-2-3-4-5."""
    sorted_vals = sorted(set(values))
    if len(sorted_vals) < 5:
        return False
    # Escalera normal
    if sorted_vals[-1] - sorted_vals[0] == 4:
        return True
    # Rueda: A-2-3-4-5 (A vale 1 en este caso)
    if sorted_vals == [2, 3, 4, 5, 14]:
        return True
    return False


# ══════════════════════════════════════════════════════
#  EVALUACIÓN DE 7 CARTAS (2 hole + 5 community)
# ══════════════════════════════════════════════════════

def evaluate_hand(hole: list[Card], community: list[Card]) -> HandResult:
    """
    Recibe 2 cartas del jugador y entre 3 y 5 comunitarias.
    Devuelve la mejor mano posible de 5 cartas.
    """
    all_cards = hole + community
    if len(all_cards) < 5:
        raise ValueError(f"Se necesitan al menos 5 cartas, recibidas: {len(all_cards)}")

    best: Optional[HandResult] = None
    for combo in combinations(all_cards, 5):
        result = _evaluate_five(list(combo))
        if best is None or result > best:
            best = result

    return best


# ══════════════════════════════════════════════════════
#  COMPARAR DOS JUGADORES
# ══════════════════════════════════════════════════════

def compare_hands(
    hole_a: list[Card], hole_b: list[Card], community: list[Card]
) -> tuple[int, HandResult, HandResult]:
    """
    Compara las manos de dos jugadores contra las mismas cartas comunitarias.
    Devuelve:
        ( 1, result_a, result_b) → gana A
        (-1, result_a, result_b) → gana B
        ( 0, result_a, result_b) → empate (split pot)
    """
    result_a = evaluate_hand(hole_a, community)
    result_b = evaluate_hand(hole_b, community)

    if result_a > result_b:
        return 1, result_a, result_b
    elif result_b > result_a:
        return -1, result_a, result_b
    else:
        return 0, result_a, result_b
