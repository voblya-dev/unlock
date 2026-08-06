"""Genome invariants, checked against the 21 shipped configs. No admin needed.

    python tools/selftest_genome.py

Covers what the genetic search silently depends on: an unmutated genome must
re-render its config token-for-token, mutation must change something without
corrupting the skeleton, and crossover must not invent a stanza neither parent
had.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unlock.genome import (  # noqa: E402
    GENE_FLAGS,
    TTL_FLAGS,
    Genome,
    crossover,
    gene_pools,
    mutate,
    seed_population,
)
from unlock.strategies import load_raw_configs  # noqa: E402

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    configs = load_raw_configs()
    if not configs:
        print("No general*.bat found — run tools/fetch_zapret.py first.")
        return 1

    print(f"Loaded {len(configs)} configs")

    # 1. Round-trip: parsing then rendering has to be the identity.
    for name, args in configs:
        rendered = Genome.from_args(args).to_args()
        check(rendered == list(args), f"{name}: round-trip changed the vector")
        if rendered != list(args):
            for index, (want, got) in enumerate(zip(args, rendered)):
                if want != got:
                    print(f"  {name} token {index}: {want!r} -> {got!r}")
                    break
    print("Round-trip ok")

    # 2. Structure: every config is a header plus stanzas that all filter.
    for name, args in configs:
        genome = Genome.from_args(args)
        check(bool(genome.header), f"{name}: no --wf-* header")
        check(len(genome.sections) >= 2, f"{name}: expected several stanzas")
        for index, section in enumerate(genome.sections):
            check(bool(section.tokens), f"{name}: stanza {index} is empty")
            check(
                any(t.startswith("--filter-") for t in section.tokens),
                f"{name}: stanza {index} has no --filter-*",
            )
    print("Structure ok")

    # 3. Pools: harvested per transport, and never mixing TCP and UDP values.
    pools = gene_pools()
    check(bool(pools), "no gene pools harvested")
    tcp_modes = set(pools.get(("tcp", "--dpi-desync"), ()))
    udp_modes = set(pools.get(("udp", "--dpi-desync"), ()))
    check(bool(tcp_modes) and bool(udp_modes), "missing desync pool for a transport")
    check(
        "multisplit" not in udp_modes and "fakedsplit" not in udp_modes,
        f"TCP-only split modes leaked into the UDP pool: {sorted(udp_modes)}",
    )
    print(f"Pools ok ({len(pools)} buckets, tcp modes={sorted(tcp_modes)})")

    # 4. Mutation: changes the vector, keeps the skeleton, stays in-pool.
    rng = random.Random(1234)
    base = Genome.from_args(configs[0][1])
    changed = 0
    for _ in range(300):
        mutant = mutate(base, rng)
        if mutant.to_args() != base.to_args():
            changed += 1
        check(
            len(mutant.sections) == len(base.sections),
            "mutation changed the stanza count",
        )
        for before, after in zip(base.sections, mutant.sections):
            check(before.role == after.role, "mutation rewrote the skeleton")
        for section in mutant.sections:
            for token in section.tokens:
                if not token.startswith("--") or "=" not in token:
                    continue
                flag, _, value = token.partition("=")
                if flag in GENE_FLAGS:
                    pool = pools.get((section.transport, flag), ())
                    check(
                        not pool or value in pool,
                        f"mutation produced an off-pool value {flag}={value}",
                    )
    check(changed == 300, f"mutation was a no-op {300 - changed}/300 times")
    print(f"Mutation ok ({changed}/300 changed)")

    # 5. TTL genes: only ever attached to a fake-bearing stanza.
    seen_ttl = 0
    for _ in range(300):
        for section in mutate(base, rng).sections:
            for token in section.tokens:
                flag = token.partition("=")[0]
                if flag in TTL_FLAGS:
                    seen_ttl += 1
                    check(
                        any("fake" in mode for mode in section.desync_modes()),
                        f"{flag} landed on a stanza with no fake mode",
                    )
    check(seen_ttl > 0, "TTL mutation never fired")
    print(f"TTL genes ok ({seen_ttl} placements)")

    # 6. Crossover: every stanza traceable to a parent, structure preserved.
    for _ in range(200):
        first = Genome.from_args(rng.choice(configs)[1])
        second = Genome.from_args(rng.choice(configs)[1])
        child = crossover(first, second, rng)
        check(len(child.sections) == len(first.sections), "crossover resized the genome")
        parent_sections = {s.tokens for s in first.sections} | {s.tokens for s in second.sections}
        for section in child.sections:
            check(section.tokens in parent_sections, "crossover invented a stanza")
    print("Crossover ok")

    # 7. Seeding: presets lead, and the population is padded to size.
    population = seed_population(random.Random(7), 30)
    check(len(population) == 30, f"seed_population returned {len(population)}")
    check(
        population[0].to_args() == list(configs[0][1]),
        "seed population does not start from the pack default",
    )
    signatures = {g.signature for g in population}
    check(len(signatures) > 20, f"seed population is not diverse ({len(signatures)} unique)")
    print(f"Seeding ok ({len(signatures)}/30 unique)")

    if failures:
        print(f"\nFAILED ({len(failures)})")
        for message in failures[:20]:
            print(f"  - {message}")
        return 1
    print("\nAll genome selftests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
