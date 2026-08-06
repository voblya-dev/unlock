"""Genetic search for a DPI-bypass strategy tuned to this specific link.

The preset benchmark asks "which of the 21 shipped configs works here?". This
asks a bigger question: "what is the best config for *this* provider?" — and
the answer is usually not one of the 21, because DPI vendors, firmware versions
and even regional policies differ, while the pack's configs are tuned against
whatever their authors could test.

The loop is a plain genetic algorithm over ``genome.Genome``:

    generation 0   the shipped configs, plus mutants to fill the population
    fitness        the share of probes that pass, latency as the tie-break
    selection      tournament, so a merely-good genome still gets a chance
    reproduction   crossover of two parents, then mutation
    elitism        the best few survive untouched

Fitness is measured, not modelled: each candidate is really started and really
probed, which is what makes the result trustworthy and also what makes the run
slow. Every lever here exists to spend that budget well — the cache skips
genomes already seen, elites are never re-probed, and the run stops early once
generations stop improving.

The search is strictly an improvement on the benchmark: generation zero *is*
the benchmark, so the winner is at worst the best preset.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

from .benchmark import StrategyResult, probe_strategy
from .constants import (
    EVOLUTION_CROSSOVER_CHANCE,
    EVOLUTION_ELITES,
    EVOLUTION_GENERATIONS,
    EVOLUTION_MUTATION_RATE,
    EVOLUTION_POPULATION,
    EVOLUTION_PROBE_PROTOCOLS,
    EVOLUTION_PROBE_TARGETS,
    EVOLUTION_SETTLE_DELAY,
    EVOLUTION_STALL_LIMIT,
    EVOLUTION_TIME_BUDGET,
    EVOLUTION_TOURNAMENT,
    PROBE_TARGETS,
)
from .dpi_engine import DpiEngine
from .genome import Genome, crossover, mutate, seed_population
from .logger import get_logger
from .strategies import DpiStrategy, expand_args, save_evolved

log = get_logger("evolution")

ProgressFn = Callable[[int, str], None]


@dataclass
class Individual:
    genome: Genome
    result: StrategyResult | None = None
    origin: str = "seed"

    @property
    def fitness(self) -> float:
        """Pass ratio, nudged by latency so ties resolve toward the faster one.

        The bonus is capped well below the value of a single probe, so a genome
        can never win on speed while unblocking less — correctness first, and
        speed only among equals.
        """
        if self.result is None:
            return 0.0
        if not self.result.total:
            return 0.0
        ratio = self.result.passed / self.result.total
        latency = self.result.latency_ms
        if ratio == 0.0 or latency == float("inf"):
            return ratio
        # 1000 ms -> ~0, 0 ms -> 0.05 of a probe's worth.
        bonus = max(0.0, 1.0 - latency / 1000.0) * 0.05
        return ratio + bonus / max(self.result.total, 1)


@dataclass
class EvolutionReport:
    best: StrategyResult | None = None
    best_args: list[str] = field(default_factory=list)     # unexpanded tokens
    baseline: StrategyResult | None = None                 # best shipped preset
    generations: int = 0
    evaluated: int = 0
    history: list[float] = field(default_factory=list)     # best fitness per generation
    saved_name: str | None = None

    @property
    def improved(self) -> bool:
        """Did the search beat the best preset it started from?

        Compares pass *ratios*: the baseline was scored on the reduced target
        set the search ranks with, the winner on the full one, so the raw
        counts are not on the same scale.
        """
        if self.best is None or self.baseline is None:
            return False
        if not self.best.total or not self.baseline.total:
            return False
        best_ratio = self.best.passed / self.best.total
        baseline_ratio = self.baseline.passed / self.baseline.total
        if abs(best_ratio - baseline_ratio) > 1e-9:
            return best_ratio > baseline_ratio
        return self.best.latency_ms < self.baseline.latency_ms

    def as_dict(self) -> dict:
        return {
            "best": self.best.as_dict() if self.best else None,
            "baseline": self.baseline.as_dict() if self.baseline else None,
            "generations": self.generations,
            "evaluated": self.evaluated,
            "history": [round(f, 4) for f in self.history],
            "saved_name": self.saved_name,
            "improved": self.improved,
        }


class Evolution:
    """Runs the search. One instance per run; ``cancel`` is thread-safe."""

    def __init__(
        self,
        engine: DpiEngine,
        *,
        game_filter: bool = False,
        seed: int | None = None,
    ) -> None:
        self._engine = engine
        self._game_filter = game_filter
        self._rng = random.Random(seed)
        self._cancelled = False
        self._cache: dict[str, StrategyResult] = {}
        self._evaluated = 0

    def cancel(self) -> None:
        self._cancelled = True

    # ---------------------------------------------------------------- run

    def run(
        self,
        *,
        population_size: int = EVOLUTION_POPULATION,
        generations: int = EVOLUTION_GENERATIONS,
        time_budget: float = EVOLUTION_TIME_BUDGET,
        progress: ProgressFn | None = None,
    ) -> EvolutionReport:
        self._cancelled = False
        self._cache.clear()
        self._evaluated = 0

        report = EvolutionReport()
        # Checked between evaluations, so a run can overshoot by at most one
        # candidate — a winws restart plus a probe sweep, not a whole generation.
        deadline = time.monotonic() + time_budget

        population = [
            Individual(genome) for genome in seed_population(self._rng, population_size)
        ]
        if not population:
            log.warning("No configs to seed the search from")
            return report

        # Total work is dominated by probe runs, so progress counts those.
        planned = max(1, population_size * generations)

        def emit(message: str) -> None:
            if progress:
                percent = min(99, int(self._evaluated / planned * 100))
                progress(percent, message)

        best: Individual | None = None
        stalled = 0

        for generation in range(generations):
            if self._cancelled or time.monotonic() > deadline:
                break

            label = "gen 0 (shipped configs)" if generation == 0 else f"gen {generation}"
            for index, individual in enumerate(population, 1):
                if self._cancelled or time.monotonic() > deadline:
                    break
                if individual.result is None:
                    emit(f"{label}: testing {index}/{len(population)} — {individual.genome.summary()}")
                    individual.result = self._score(individual, generation, index)

            scored = [i for i in population if i.result is not None]
            if not scored:
                break

            scored.sort(key=lambda i: -i.fitness)
            report.generations = generation + 1
            report.history.append(scored[0].fitness)

            if generation == 0:
                # Generation zero is exactly the preset benchmark, so its winner
                # is the bar the search has to clear to be worth the wall-clock.
                report.baseline = scored[0].result

            if best is None or scored[0].fitness > best.fitness:
                best = scored[0]
                stalled = 0
            else:
                stalled += 1

            result = scored[0].result
            emit(
                f"{label} best: {result.passed}/{result.total} probes "
                f"({scored[0].genome.summary()})"
            )

            if best.result and best.result.passed == best.result.total and generation:
                # Everything passes and the tie-break bonus is worth less than a
                # probe, so no further generation can score higher.
                log.info("Perfect score reached, stopping early")
                break
            if stalled >= EVOLUTION_STALL_LIMIT:
                log.info("No improvement for %d generations, stopping", stalled)
                break
            if generation == generations - 1:
                break

            population = self._next_generation(scored, population_size)

        report.evaluated = self._evaluated
        if best is not None and best.result is not None:
            if self._cancelled:
                report = self._finalise_cancelled(report, best)
            else:
                report = self._finalise(report, best, progress)
        if progress:
            progress(100, "Search complete")
        return report

    # ------------------------------------------------------------- steps

    def _score(self, individual: Individual, generation: int, index: int) -> StrategyResult:
        """Fitness of one genome, from cache when the vector was already tried."""
        signature = individual.genome.signature
        cached = self._cache.get(signature)
        if cached is not None:
            return cached

        name = f"gen{generation}-{index}"
        strategy = DpiStrategy(
            name=name,
            description=individual.genome.summary(),
            args=expand_args(individual.genome.to_args(), self._game_filter),
        )
        result = probe_strategy(
            self._engine,
            strategy,
            targets=EVOLUTION_PROBE_TARGETS,
            protocols=EVOLUTION_PROBE_PROTOCOLS,
            settle=EVOLUTION_SETTLE_DELAY,
            measure_link=False,
        )
        self._cache[signature] = result
        self._evaluated += 1
        return result

    def _next_generation(self, scored: list[Individual], size: int) -> list[Individual]:
        """Elites, then children of tournament-selected parents.

        Elites keep their result so they are never re-probed; children carry
        none, which is what marks them as needing evaluation.
        """
        elites = scored[:min(EVOLUTION_ELITES, len(scored))]
        population = list(elites)

        guard = 0
        seen = {i.genome.signature for i in population}
        while len(population) < size and guard < size * 20:
            guard += 1
            parent = self._tournament(scored)
            if self._rng.random() < EVOLUTION_CROSSOVER_CHANCE and len(scored) > 1:
                other = self._tournament(scored)
                child = crossover(parent.genome, other.genome, self._rng)
                origin = "crossover"
            else:
                child = parent.genome
                origin = "mutation"
            child = mutate(child, self._rng, rate=EVOLUTION_MUTATION_RATE)

            signature = child.signature
            if signature in seen:
                continue
            seen.add(signature)

            cached = self._cache.get(signature)
            population.append(Individual(child, result=cached, origin=origin))

        return population

    def _tournament(self, scored: list[Individual]) -> Individual:
        entrants = self._rng.sample(scored, min(EVOLUTION_TOURNAMENT, len(scored)))
        return max(entrants, key=lambda i: i.fitness)

    def _finalise(
        self, report: EvolutionReport, best: Individual, progress: ProgressFn | None
    ) -> EvolutionReport:
        """Re-score the winner against the full target set, then persist it.

        The search ranks on a reduced target set for speed, so the winner has
        not actually been proven against everything the benchmark checks. This
        confirms it and stores the honest numbers.
        """
        args = best.genome.to_args()
        report.best_args = args

        if progress:
            progress(99, "Confirming the winner against every target")

        strategy = DpiStrategy(
            name="evolved",
            description=best.genome.summary(),
            args=expand_args(args, self._game_filter),
        )
        confirmed = probe_strategy(
            self._engine, strategy, targets=PROBE_TARGETS, settle=EVOLUTION_SETTLE_DELAY
        )
        report.best = confirmed

        if confirmed.passed:
            name = f"Evolved ({best.genome.summary()})"
            save_evolved(
                name,
                args,
                description=(
                    f"Evolved locally: {confirmed.passed}/{confirmed.total} probes, "
                    f"{confirmed.latency_ms:.0f} ms"
                ),
            )
            report.best = StrategyResult(
                name=name,
                ok=confirmed.ok,
                latency_ms=confirmed.latency_ms,
                link_ms=confirmed.link_ms,
                passed=confirmed.passed,
                total=confirmed.total,
                per_service=confirmed.per_service,
            )
            report.saved_name = name
        else:
            log.warning("Winner failed every probe on confirmation, not saving it")

        return report

    def _finalise_cancelled(
        self, report: EvolutionReport, best: Individual
    ) -> EvolutionReport:
        """When cancelled, save the best found without re-probing.

        The search already scored this genome on the reduced target set. That
        result is weaker than a full-probe confirmation, but when the user stops
        the search mid-run, reporting what was already confirmed beats forcing
        them to wait for one more winws restart.
        """
        args = best.genome.to_args()
        report.best_args = args
        report.best = best.result

        if best.result and best.result.passed:
            name = f"Evolved ({best.genome.summary()})"
            save_evolved(
                name,
                args,
                description=(
                    f"Evolved locally (partial): {best.result.passed}/{best.result.total} "
                    f"quick probes, {best.result.latency_ms:.0f} ms"
                ),
            )
            report.best = StrategyResult(
                name=name,
                ok=best.result.ok,
                latency_ms=best.result.latency_ms,
                link_ms=best.result.link_ms,
                passed=best.result.passed,
                total=best.result.total,
                per_service=best.result.per_service,
            )
            report.saved_name = name
        else:
            log.warning("Best genome passed nothing, not saving it")

        return report
