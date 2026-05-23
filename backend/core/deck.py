"""
core/deck.py
Mazo estándar de 52 cartas. Sin dependencias externas.
"""

import random
from dataclasses import dataclass
from typing import Optional


# ══════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════

SUITS = ("s", "h", "d", "c")        # spades, hearts, diamonds, clubs
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")

RANK_VALUE: dict[str, int] = {r: i for i, r in enumerate(RANKS, start=2)}
# 2→2, 3→3, ... 10→10, J→11, Q→12, K→13, A→14

SUIT_SYMBOLS: dict[str, str] = {
    "s": "♠",
    "h": "♥",
    "d": "♦",
    "c": "♣",
}

SUIT_COLORS: dict[str, str] = {
    "s": "black",
    "h": "red",
    "d": "red",
    "c": "black",
}


# ══════════════════════════════════════════════════════
#  CARTA
# ══════════════════════════════════════════════════════

@dataclass(frozen=True)
class Card:
    rank: str   # "2" … "A"
    suit: str   # "s" | "h" | "d" | "c"

    @property
    def value(self) -> int:
        return RANK_VALUE[self.rank]

    @property
    def symbol(self) -> str:
        return SUIT_SYMBOLS[self.suit]

    @property
    def color(self) -> str:
        return SUIT_COLORS[self.suit]

    def to_dict(self) -> dict:
        """Serializable para guardar en JSON y enviar al frontend."""
        return {
            "rank": self.rank,
            "suit": self.suit,
            "symbol": self.symbol,
            "color": self.color,
            "value": self.value,
        }

    def __str__(self) -> str:
        return f"{self.rank}{self.symbol}"

    def __repr__(self) -> str:
        return self.__str__()

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(rank=data["rank"], suit=data["suit"])


# ══════════════════════════════════════════════════════
#  MAZO
# ══════════════════════════════════════════════════════

class Deck:
    def __init__(self) -> None:
        self._cards: list[Card] = [
            Card(rank, suit)
            for suit in SUITS
            for rank in RANKS
        ]
        self._dealt: int = 0

    def shuffle(self) -> "Deck":
        random.shuffle(self._cards)
        self._dealt = 0
        return self

    def deal(self, n: int = 1) -> list[Card]:
        """Reparte n cartas. Lanza ValueError si no quedan suficientes."""
        if self._dealt + n > len(self._cards):
            raise ValueError(
                f"No quedan suficientes cartas. "
                f"Solicitadas: {n}, disponibles: {len(self._cards) - self._dealt}"
            )
        cards = self._cards[self._dealt: self._dealt + n]
        self._dealt += n
        return cards

    def deal_one(self) -> Card:
        return self.deal(1)[0]

    @property
    def remaining(self) -> int:
        return len(self._cards) - self._dealt

    def __len__(self) -> int:
        return self.remaining

    def __repr__(self) -> str:
        return f"Deck(remaining={self.remaining})"


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════

def cards_to_dict(cards: list[Card]) -> list[dict]:
    return [c.to_dict() for c in cards]


def cards_from_dict(data: list[dict]) -> list[Card]:
    return [Card.from_dict(d) for d in data]


def new_shuffled_deck() -> Deck:
    return Deck().shuffle()
