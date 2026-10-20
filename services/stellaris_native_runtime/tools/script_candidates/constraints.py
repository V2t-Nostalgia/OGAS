"""Partial script evaluation. Unknown syntax/facts never imply legality."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from enum import Enum

from .syntax import Node


class Truth(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def negate(self) -> Truth:
        return {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE}.get(self, self)


def conjunction(values) -> Truth:
    values = tuple(values)
    if Truth.FALSE in values:
        return Truth.FALSE
    return Truth.UNKNOWN if Truth.UNKNOWN in values else Truth.TRUE


def disjunction(values) -> Truth:
    values = tuple(values)
    if Truth.TRUE in values:
        return Truth.TRUE
    return Truth.UNKNOWN if Truth.UNKNOWN in values else Truth.FALSE


@dataclass(frozen=True, order=True)
class ObjectRef:
    native_type: str
    object_id: int


@dataclass(frozen=True)
class Fact:
    value: str | bool | int | Decimal | frozenset[str]
    source: str
    complete: bool = True
    trusted: bool = True


@dataclass
class World:
    facts: dict[ObjectRef, dict[str, Fact]] = field(default_factory=dict)
    links: dict[tuple[ObjectRef, str], ObjectRef] = field(default_factory=dict)
    collections: dict[tuple[ObjectRef, str], tuple[tuple[ObjectRef, ...], bool]] = field(default_factory=dict)

    def objects(self, native_type: str) -> tuple[ObjectRef, ...]:
        return tuple(sorted(ref for ref in self.facts if ref.native_type == native_type))


@dataclass(frozen=True)
class Scope:
    this: ObjectRef | None
    root: ObjectRef | None = None
    from_: ObjectRef | None = None
    prev: ObjectRef | None = None

    def enter(self, target: ObjectRef | None) -> Scope:
        return replace(self, this=target, prev=self.this)


@dataclass(frozen=True)
class Evaluation:
    truth: Truth
    unknown: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


class Evaluator:
    """Whitelisted declarative triggers, never effects or AI scoring scripts.

    Missing sets/collections are UNKNOWN, including under NOT. The evaluator
    cannot establish overall Command legality, even if every parsed rule passes.
    """

    def __init__(self, world: World, scripted: dict[str, Node] | None = None, budget: int = 10000, *, advisory: bool = False):
        self.world = world
        self.scripted = scripted or {}
        self.budget = budget
        self.advisory = advisory

    def evaluate(self, nodes: tuple[Node, ...], scope: Scope) -> Evaluation:
        self.remaining = self.budget
        self.unknown: set[str] = set()
        self.failures: set[str] = set()
        value = self._all(nodes, scope, ())
        return Evaluation(value, tuple(sorted(self.unknown)), tuple(sorted(self.failures)))

    def _unknown(self, why: str) -> Truth:
        self.unknown.add(why)
        return Truth.UNKNOWN

    def _all(self, nodes, scope, active) -> Truth:
        # Evaluate if/else_if/else as a chain, not as independent AND clauses.
        values = []
        index = 0
        while index < len(nodes):
            node = nodes[index]
            if node.key == "if":
                chain = [node]
                index += 1
                while index < len(nodes) and nodes[index].key in {"else_if", "else"}:
                    chain.append(nodes[index])
                    index += 1
                values.append(self._conditional(chain, scope, active))
                continue
            values.append(self._node(node, scope, active))
            index += 1
        return conjunction(values)

    def _conditional(self, chain, scope, active) -> Truth:
        outcomes = []
        fallthrough = True
        for node in chain:
            if not fallthrough:
                break
            limit = node.one("limit")
            condition = Truth.TRUE if node.key == "else" else (
                self._all(limit.children or (), scope, active) if limit else self._unknown("if:missing_limit")
            )
            if condition is not Truth.FALSE:
                body = tuple(n for n in node.children or () if n.key != "limit")
                outcomes.append(self._all(body, scope, active))
            if condition is Truth.TRUE:
                fallthrough = False
        if fallthrough:
            outcomes.append(Truth.TRUE)
        return outcomes[0] if outcomes and all(v == outcomes[0] for v in outcomes) else Truth.UNKNOWN

    def _node(self, node: Node, scope: Scope, active: tuple[str, ...]) -> Truth:
        self.remaining -= 1
        if self.remaining < 0 or len(active) > 32:
            return self._unknown("evaluation_budget")
        key, children, value = node.key or "", node.children, node.value
        upper = key.upper()
        if children is not None and node.operator != "=":
            return self._unknown("block_operator:" + node.operator)
        if upper in {"AND", "OR", "NOR", "NAND", "NOT"} and children is not None:
            if upper == "NOT":
                # Multi-statement NOT has engine-specific semantics; do not guess.
                return self._node(children[0], scope, active).negate() if len(children) == 1 else self._unknown("multi_statement_NOT")
            values = [self._node(n, scope, active) for n in children]
            result = disjunction(values) if upper in {"OR", "NOR"} else conjunction(values)
            return result.negate() if upper in {"NOR", "NAND"} else result
        if key in {"custom_tooltip", "hidden_trigger"} and children is not None:
            result = self._all(tuple(n for n in children if n.key not in {"fail_text", "success_text", "text"}), scope, active)
            if result is Truth.FALSE and node.scalar("fail_text"):
                self.failures.add(node.scalar("fail_text"))
            return result
        if key in self.scripted:
            if key in active or value not in {"yes", "no"} or children is not None or node.operator != "=":
                return self._unknown("scripted_trigger_parameters_or_cycle:" + key)
            result = self._all(self.scripted[key].children or (), scope, active + (key,))
            return result.negate() if value == "no" else result
        if key == "always" and value in {"yes", "no"} and node.operator == "=":
            return Truth.TRUE if value == "yes" else Truth.FALSE
        if children is not None and key.lower() in {"root", "this", "from", "prev"}:
            target = {"root": scope.root, "this": scope.this, "from": scope.from_, "prev": scope.prev}[key.lower()]
            return self._all(children, scope.enter(target), active) if target else self._unknown("scope:" + key)
        if children is not None and key in {"owner", "controller", "solar_system", "capital_scope"}:
            target = self.world.links.get((scope.this, key))
            return self._all(children, scope.enter(target), active) if target else self._unknown("link:" + key)
        if children is not None and key.startswith(("any_", "every_")):
            collection = self.world.collections.get((scope.this, key.split("_", 1)[1]))
            if collection is None:
                return self._unknown("collection:" + key)
            refs, complete = collection
            results = [self._all(children, scope.enter(ref), active) for ref in refs]
            if not complete:
                results.append(self._unknown("incomplete_collection:" + key))
            return disjunction(results) if key.startswith("any_") else conjunction(results)
        if children is not None or scope.this is None:
            return self._unknown("trigger_or_scope:" + key)
        facts = self.world.facts.get(scope.this, {})
        # This is a trigger-family mapping, not a per-Command adapter. Adapters
        # must explicitly prove the save/definition fact before it can be used.
        set_name = {"has_ascension_perk": "ascension_perks", "has_technology": "technologies",
                    "has_civic": "civics", "has_ethic": "ethics", "has_tradition": "traditions"}.get(key)
        if set_name:
            fact = facts.get(set_name)
            if fact is None or (not fact.trusted and not self.advisory) or not isinstance(fact.value, frozenset) or node.operator != "=":
                return self._unknown("fact:" + key)
            if value in fact.value:
                return Truth.TRUE
            return Truth.FALSE if fact.complete else self._unknown("incomplete_set:" + key)
        if key.startswith("has_") and key.endswith("_flag"):
            # Dynamic @scope identity, expiry and flag storage are not inferred.
            return self._unknown("flag_semantics:" + key)
        fact = facts.get(key)
        if fact is None or not fact.complete or (not fact.trusted and not self.advisory):
            return self._unknown("fact:" + key)
        if isinstance(fact.value, bool) and value in {"yes", "no"}:
            actual, expected = fact.value, value == "yes"
        elif isinstance(fact.value, str):
            actual, expected = fact.value, value
        else:
            try:
                actual, expected = Decimal(str(fact.value)), Decimal(value or "")
            except (ValueError, InvalidOperation):
                return self._unknown("comparison:" + key)
        operations = {"=": lambda: actual == expected, "==": lambda: actual == expected,
                      "!=": lambda: actual != expected, ">": lambda: actual > expected,
                      "<": lambda: actual < expected, ">=": lambda: actual >= expected,
                      "<=": lambda: actual <= expected}
        if node.operator not in operations:
            return self._unknown("operator:" + node.operator)
        try:
            return Truth.TRUE if operations[node.operator]() else Truth.FALSE
        except TypeError:
            return self._unknown("comparison_type:" + key)
