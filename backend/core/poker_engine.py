"""
core/poker_engine.py
Motor de Texas Hold'em 1v1.
Maneja el estado completo de una mano desde el reparto
hasta la resolución. Sin dependencias de base de datos.
Todo el estado es serializable a dict para guardarlo en JSON.
"""

from dataclasses import dataclass, field
from typing import Optional
import time

from core.deck import Deck, Card, new_shuffled_deck, cards_to_dict, cards_from_dict
from core.hand_evaluator import evaluate_hand, compare_hands, HandResult
import config


# ══════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════

class Stage:
    PREFLOP  = "preflop"
    FLOP     = "flop"
    TURN     = "turn"
    RIVER    = "river"
    SHOWDOWN = "showdown"

STAGE_ORDER = [Stage.PREFLOP, Stage.FLOP, Stage.TURN, Stage.RIVER, Stage.SHOWDOWN]

class Action:
    FOLD  = "fold"
    CHECK = "check"
    CALL  = "call"
    RAISE = "raise"
    BET   = "bet"


# ══════════════════════════════════════════════════════
#  JUGADOR DENTRO DEL MOTOR
# ══════════════════════════════════════════════════════

@dataclass
class PlayerState:
    user_id: int
    stack: int                      # fichas disponibles
    hole_cards: list[Card] = field(default_factory=list)
    bet_in_stage: int = 0           # lo apostado en la ronda actual
    total_bet: int = 0              # total apostado en la mano
    is_folded: bool = False
    is_all_in: bool = False

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "stack": self.stack,
            "hole_cards": cards_to_dict(self.hole_cards),
            "bet_in_stage": self.bet_in_stage,
            "total_bet": self.total_bet,
            "is_folded": self.is_folded,
            "is_all_in": self.is_all_in,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerState":
        obj = cls(user_id=d["user_id"], stack=d["stack"])
        obj.hole_cards = cards_from_dict(d["hole_cards"])
        obj.bet_in_stage = d["bet_in_stage"]
        obj.total_bet = d["total_bet"]
        obj.is_folded = d["is_folded"]
        obj.is_all_in = d["is_all_in"]
        return obj


# ══════════════════════════════════════════════════════
#  RESULTADO DE UNA MANO
# ══════════════════════════════════════════════════════

@dataclass
class HandOutcome:
    winner_id: int
    loser_id: int
    pot: int
    rake: int
    winner_profit: int              # pot - rake
    is_split: bool = False
    winner_hand: Optional[HandResult] = None
    loser_hand: Optional[HandResult] = None
    reason: str = "showdown"        # "showdown" | "fold" | "timeout"

    def to_dict(self) -> dict:
        return {
            "winner_id": self.winner_id,
            "loser_id": self.loser_id,
            "pot": self.pot,
            "rake": self.rake,
            "winner_profit": self.winner_profit,
            "is_split": self.is_split,
            "winner_hand": self.winner_hand.to_dict() if self.winner_hand else None,
            "loser_hand": self.loser_hand.to_dict() if self.loser_hand else None,
            "reason": self.reason,
        }


# ══════════════════════════════════════════════════════
#  MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════

class PokerEngine:
    """
    Representa el estado de UNA mano de poker.
    Se instancia, serializa y deserializa en cada acción.
    """

    def __init__(
        self,
        player_a_id: int, stack_a: int,
        player_b_id: int, stack_b: int,
        dealer_id: int,
        hand_number: int = 1,
    ) -> None:
        self.player_a = PlayerState(player_a_id, stack_a)
        self.player_b = PlayerState(player_b_id, stack_b)
        self.dealer_id = dealer_id
        self.hand_number = hand_number

        self.community_cards: list[Card] = []
        self.pot: int = 0
        self.current_stage: str = Stage.PREFLOP
        self.current_player_id: int = 0
        self.current_bet: int = 0        # apuesta más alta en la ronda actual
        self.last_aggressor_id: int = 0  # quien hizo la última raise/bet
        self.turn_started_at: float = 0.0
        self.is_finished: bool = False
        self.outcome: Optional[HandOutcome] = None

        self._deck: Optional[Deck] = None

    # ── PROPIEDADES ────────────────────────────────────

    @property
    def non_dealer(self) -> PlayerState:
        return self.player_b if self.dealer_id == self.player_a.user_id else self.player_a

    @property
    def dealer(self) -> PlayerState:
        return self.player_a if self.dealer_id == self.player_a.user_id else self.player_b

    def _get_player(self, user_id: int) -> PlayerState:
        if self.player_a.user_id == user_id:
            return self.player_a
        return self.player_b

    def _get_opponent(self, user_id: int) -> PlayerState:
        if self.player_a.user_id == user_id:
            return self.player_b
        return self.player_a

    # ── INICIO DE MANO ─────────────────────────────────

    def start_hand(self) -> None:
        """Reparte cartas y cobra blinds. Listo para recibir acciones."""
        self._deck = new_shuffled_deck()

        # Dealer = Small Blind en 1v1
        sb_player = self.dealer
        bb_player = self.non_dealer

        # Cobrar blinds
        self._post_blind(sb_player, config.SMALL_BLIND)
        self._post_blind(bb_player, config.BIG_BLIND)

        # Repartir 2 cartas a cada jugador
        self.player_a.hole_cards = self._deck.deal(2)
        self.player_b.hole_cards = self._deck.deal(2)

        # En preflop actúa primero el SB (dealer en 1v1)
        self.current_player_id = sb_player.user_id
        self.current_bet = config.BIG_BLIND
        self.last_aggressor_id = bb_player.user_id
        self.turn_started_at = time.time()

    def _post_blind(self, player: PlayerState, amount: int) -> None:
        actual = min(amount, player.stack)
        player.stack -= actual
        player.bet_in_stage += actual
        player.total_bet += actual
        self.pot += actual
        if player.stack == 0:
            player.is_all_in = True

    # ── VALIDACIÓN DE ACCIONES ─────────────────────────

    def get_valid_actions(self, user_id: int) -> list[str]:
        if self.is_finished or self.current_player_id != user_id:
            return []

        player = self._get_player(user_id)
        opponent = self._get_opponent(user_id)
        to_call = self.current_bet - player.bet_in_stage

        actions = [Action.FOLD]

        if to_call == 0:
            actions.append(Action.CHECK)
        else:
            if player.stack >= to_call:
                actions.append(Action.CALL)

        # Puede raise si tiene fichas después de igualar
        min_raise = self.current_bet + config.BIG_BLIND
        if player.stack > to_call and not opponent.is_all_in:
            actions.append(Action.RAISE)

        return actions

    # ── PROCESAR ACCIÓN ────────────────────────────────

    def process_action(
        self, user_id: int, action: str, amount: int = 0
    ) -> Optional[HandOutcome]:
        """
        Procesa una acción del jugador.
        Devuelve HandOutcome si la mano terminó, None si continúa.
        Lanza ValueError si la acción es inválida.
        """
        if self.is_finished:
            raise ValueError("La mano ya terminó")
        if self.current_player_id != user_id:
            raise ValueError("No es tu turno")

        valid = self.get_valid_actions(user_id)
        if action not in valid:
            raise ValueError(f"Acción '{action}' no válida. Válidas: {valid}")

        player   = self._get_player(user_id)
        opponent = self._get_opponent(user_id)

        if action == Action.FOLD:
            return self._resolve_fold(player, opponent)

        elif action == Action.CHECK:
            pass  # no hay nada que cobrar

        elif action == Action.CALL:
            to_call = self.current_bet - player.bet_in_stage
            actual = min(to_call, player.stack)
            player.stack -= actual
            player.bet_in_stage += actual
            player.total_bet += actual
            self.pot += actual
            if player.stack == 0:
                player.is_all_in = True

        elif action == Action.RAISE:
            to_call = self.current_bet - player.bet_in_stage
            min_total = self.current_bet + config.BIG_BLIND
            if amount < min_total:
                raise ValueError(
                    f"Raise mínimo: {min_total}, recibido: {amount}"
                )
            if amount > player.stack + player.bet_in_stage:
                raise ValueError("No tienes suficientes fichas")
            actual_put = amount - player.bet_in_stage
            actual_put = min(actual_put, player.stack)
            player.stack -= actual_put
            player.bet_in_stage += actual_put
            player.total_bet += actual_put
            self.pot += actual_put
            self.current_bet = player.bet_in_stage
            self.last_aggressor_id = user_id
            if player.stack == 0:
                player.is_all_in = True

        self.turn_started_at = time.time()

        # Verificar si la ronda terminó
        return self._check_stage_end(user_id)

    def process_timeout(self, user_id: int) -> HandOutcome:
        """El turno expiró — fold automático."""
        player   = self._get_player(user_id)
        opponent = self._get_opponent(user_id)
        outcome = self._resolve_fold(player, opponent)
        if outcome:
            outcome.reason = "timeout"
        return outcome

    # ── LÓGICA DE RONDAS ───────────────────────────────

    def _check_stage_end(self, last_actor_id: int) -> Optional[HandOutcome]:
        """Determina si la ronda terminó y avanza o resuelve la mano."""
        player   = self._get_player(last_actor_id)
        opponent = self._get_opponent(last_actor_id)

        # La ronda termina cuando las apuestas están igualadas
        # y el último agresor ya actuó (o no hubo agresión)
        bets_equal = player.bet_in_stage == opponent.bet_in_stage
        aggressor_acted = (
            self.last_aggressor_id == 0 or
            self.last_aggressor_id == last_actor_id or
            opponent.is_all_in or
            player.is_all_in
        )

        if not (bets_equal and aggressor_acted):
            # Turno del oponente
            self.current_player_id = opponent.user_id
            return None

        # Avanzar de ronda
        return self._advance_stage()

    def _advance_stage(self) -> Optional[HandOutcome]:
        """Reparte cartas comunitarias o va al showdown."""
        # Resetear apuestas de la ronda
        self.player_a.bet_in_stage = 0
        self.player_b.bet_in_stage = 0
        self.current_bet = 0
        self.last_aggressor_id = 0

        stage_idx = STAGE_ORDER.index(self.current_stage)
        next_stage = STAGE_ORDER[stage_idx + 1]
        self.current_stage = next_stage

        if next_stage == Stage.FLOP:
            self.community_cards += self._deck.deal(3)
        elif next_stage == Stage.TURN:
            self.community_cards += self._deck.deal(1)
        elif next_stage == Stage.RIVER:
            self.community_cards += self._deck.deal(1)
        elif next_stage == Stage.SHOWDOWN:
            return self._resolve_showdown()

        # En postflop actúa primero el no-dealer
        self.current_player_id = self.non_dealer.user_id
        self.turn_started_at = time.time()
        return None

    # ── RESOLUCIÓN ─────────────────────────────────────

    def _resolve_fold(
        self, folder: PlayerState, winner: PlayerState
    ) -> HandOutcome:
        rake = self._calc_rake(self.pot)
        profit = self.pot - rake
        winner.stack += profit

        outcome = HandOutcome(
            winner_id=winner.user_id,
            loser_id=folder.user_id,
            pot=self.pot,
            rake=rake,
            winner_profit=profit,
            reason="fold",
        )
        self.is_finished = True
        self.outcome = outcome
        return outcome

    def _resolve_showdown(self) -> HandOutcome:
        result, res_a, res_b = compare_hands(
            self.player_a.hole_cards,
            self.player_b.hole_cards,
            self.community_cards,
        )

        rake = self._calc_rake(self.pot)
        profit = self.pot - rake

        if result == 1:    # gana A
            winner, loser = self.player_a, self.player_b
            w_hand, l_hand = res_a, res_b
        elif result == -1: # gana B
            winner, loser = self.player_b, self.player_a
            w_hand, l_hand = res_b, res_a
        else:              # empate — split pot
            half = profit // 2
            self.player_a.stack += half
            self.player_b.stack += half
            outcome = HandOutcome(
                winner_id=self.player_a.user_id,
                loser_id=self.player_b.user_id,
                pot=self.pot,
                rake=rake,
                winner_profit=profit,
                is_split=True,
                winner_hand=res_a,
                loser_hand=res_b,
                reason="showdown",
            )
            self.is_finished = True
            self.outcome = outcome
            return outcome

        winner.stack += profit
        outcome = HandOutcome(
            winner_id=winner.user_id,
            loser_id=loser.user_id,
            pot=self.pot,
            rake=rake,
            winner_profit=profit,
            winner_hand=w_hand,
            loser_hand=l_hand,
            reason="showdown",
        )
        self.is_finished = True
        self.outcome = outcome
        return outcome

    def _calc_rake(self, pot: int) -> int:
        raw = int(pot * config.RAKE_RATE)
        cap = int(pot * config.RAKE_CAP)
        return min(raw, cap)

    # ── SERIALIZACIÓN ──────────────────────────────────

    def to_dict(self) -> dict:
        """Estado completo serializable para guardar en la DB."""
        return {
            "player_a": self.player_a.to_dict(),
            "player_b": self.player_b.to_dict(),
            "dealer_id": self.dealer_id,
            "hand_number": self.hand_number,
            "community_cards": cards_to_dict(self.community_cards),
            "pot": self.pot,
            "current_stage": self.current_stage,
            "current_player_id": self.current_player_id,
            "current_bet": self.current_bet,
            "last_aggressor_id": self.last_aggressor_id,
            "turn_started_at": self.turn_started_at,
            "is_finished": self.is_finished,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PokerEngine":
        """Reconstruye el motor desde un dict guardado en la DB."""
        pa = PlayerState.from_dict(d["player_a"])
        pb = PlayerState.from_dict(d["player_b"])

        engine = cls(
            player_a_id=pa.user_id, stack_a=pa.stack,
            player_b_id=pb.user_id, stack_b=pb.stack,
            dealer_id=d["dealer_id"],
            hand_number=d["hand_number"],
        )
        engine.player_a = pa
        engine.player_b = pb
        engine.community_cards = cards_from_dict(d["community_cards"])
        engine.pot = d["pot"]
        engine.current_stage = d["current_stage"]
        engine.current_player_id = d["current_player_id"]
        engine.current_bet = d["current_bet"]
        engine.last_aggressor_id = d["last_aggressor_id"]
        engine.turn_started_at = d["turn_started_at"]
        engine.is_finished = d["is_finished"]
        return engine

    def state_for_player(self, user_id: int) -> dict:
        """
        Estado filtrado para enviar al frontend.
        Las cartas del oponente van ocultas excepto en showdown.
        """
        player   = self._get_player(user_id)
        opponent = self._get_opponent(user_id)
        reveal   = self.current_stage == Stage.SHOWDOWN or self.is_finished

        return {
            "game_stage": self.current_stage,
            "pot": self.pot,
            "current_bet": self.current_bet,
            "is_your_turn": self.current_player_id == user_id,
            "turn_started_at": self.turn_started_at,
            "community_cards": cards_to_dict(self.community_cards),
            "your_cards": cards_to_dict(player.hole_cards),
            "your_stack": player.stack,
            "your_bet": player.bet_in_stage,
            "opponent_stack": opponent.stack,
            "opponent_bet": opponent.bet_in_stage,
            "opponent_cards": (
                cards_to_dict(opponent.hole_cards) if reveal else []
            ),
            "valid_actions": self.get_valid_actions(user_id),
            "is_finished": self.is_finished,
        }

