"""A winws argument vector as a mutable parameter vector.

The zapret pack ships 21 hand-tuned configs. They are not 21 points in an
unrelated space: every one is the same skeleton — a global ``--wf-*`` header
followed by ``--new``-separated sections, one per traffic class — with
different values plugged into the same handful of desync knobs. That makes the
vector a genome:

* the **skeleton** (``--filter-*``, ``--hostlist*``, ``--ipset*``) is carried
  verbatim, because it decides *which packets* a section applies to, and
  recombining it would produce a config that filters nothing;
* the **desync knobs** (mode, repeats, fooling, split position, seqovl, fake
  payload, ttl) are genes, because they decide *how* those packets are mangled,
  which is exactly what differs between DPI vendors.

Genes are edited in place inside the token list, so a genome that has not been
mutated re-renders token-for-token — a property ``tools/selftest_genome.py``
asserts against all 21 shipped configs.

Values come from the corpus rather than from winws' documented ranges. A value
that appears in a shipped config is known to parse, and pools are collected per
transport, so a UDP section can never draw a TCP-only desync mode. Combinations
that are nonetheless invalid are not a correctness problem: winws exits at once
on a bad vector, ``DpiEngine.start`` turns that into an error, and the
individual scores zero and dies out.

Tokens here are *unexpanded* — ``%BIN%``, ``%LISTS%`` and ``%GameFilter*%`` are
still placeholders — so an evolved genome stays valid when the user toggles the
game filter.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache

from .strategies import load_raw_configs

SECTION_SEPARATOR = "--new"

# Knobs the search is allowed to rewrite. Everything else is skeleton.
GENE_FLAGS = frozenset({
    "--dpi-desync",
    "--dpi-desync-repeats",
    "--dpi-desync-fooling",
    "--dpi-desync-split-pos",
    "--dpi-desync-split-seqovl",
    "--dpi-desync-split-seqovl-pattern",
    "--dpi-desync-cutoff",
    "--dpi-desync-any-protocol",
    "--dpi-desync-badseq-increment",
    "--dpi-desync-fakedsplit-pattern",
    "--dpi-desync-fake-tls",
    "--dpi-desync-fake-tls-mod",
    "--dpi-desync-fake-http",
    "--dpi-desync-fake-quic",
    "--dpi-desync-fake-discord",
    "--dpi-desync-fake-stun",
    "--dpi-desync-fake-unknown-udp",
    "--dpi-desync-hostfakesplit-mod",
    "--ip-id",
})

# TTL genes. Absent from every shipped config, so they have no corpus pool and
# are instead inserted and removed as a unit. They are alternatives: autottl
# derives the TTL winws would have to guess, so pinning both is contradictory.
TTL_FLAGS = ("--dpi-desync-ttl", "--dpi-desync-autottl")
TTL_POOLS = {
    # Low TTLs are the point: the fake has to die between the DPI box and the
    # server. Past ~8 hops it reaches the server and breaks the real session.
    "--dpi-desync-ttl": tuple(str(n) for n in range(1, 9)),
    # Offset from the measured hop count to the server; negative counts back
    # from it. This is the form that survives a route change.
    "--dpi-desync-autottl": ("-1", "-2", "2", "3", "4", "5"),
}

# Flags whose full range is safe regardless of what the corpus happens to use.
AUGMENTED_POOLS = {
    "--dpi-desync-repeats": tuple(str(n) for n in range(1, 21)),
    "--dpi-desync-any-protocol": ("0", "1"),
}

TCP, UDP, ANY = "tcp", "udp", "any"


def _split_token(token: str) -> tuple[str | None, str | None]:
    """``--flag=value`` -> ``(flag, value)``; anything else -> ``(None, None)``."""
    if not token.startswith("--") or "=" not in token:
        return None, None
    flag, _, value = token.partition("=")
    return flag, value


@dataclass(frozen=True)
class Section:
    """One ``--new``-delimited stanza: a filter plus how to mangle its traffic."""

    tokens: tuple[str, ...]

    @property
    def transport(self) -> str:
        for token in self.tokens:
            flag, _ = _split_token(token)
            if flag == "--filter-udp":
                return UDP
            if flag == "--filter-tcp":
                return TCP
        # --filter-l7=discord,stun only ever appears on UDP stanzas in the pack.
        return UDP if any("--filter-l7" in t for t in self.tokens) else ANY

    @property
    def gene_indices(self) -> tuple[int, ...]:
        return tuple(
            i for i, token in enumerate(self.tokens)
            if _split_token(token)[0] in GENE_FLAGS
        )

    @property
    def role(self) -> tuple[str, ...]:
        """The skeleton: which packets this stanza claims.

        Two stanzas with the same role are interchangeable between genomes,
        which is what makes crossover meaningful — a YouTube stanza is only
        ever recombined with another YouTube stanza.
        """
        return tuple(
            token for token in self.tokens
            if _split_token(token)[0] not in GENE_FLAGS
            and _split_token(token)[0] not in TTL_FLAGS
        )

    def with_token(self, index: int, token: str) -> "Section":
        tokens = list(self.tokens)
        tokens[index] = token
        return Section(tuple(tokens))

    def desync_modes(self) -> tuple[str, ...]:
        for token in self.tokens:
            flag, value = _split_token(token)
            if flag == "--dpi-desync":
                return tuple(value.split(","))
        return ()

    def ttl_index(self) -> int | None:
        for i, token in enumerate(self.tokens):
            if _split_token(token)[0] in TTL_FLAGS:
                return i
        return None


@dataclass(frozen=True)
class Genome:
    """A full winws argument vector, split into header and sections."""

    header: tuple[str, ...]
    sections: tuple[Section, ...]

    @classmethod
    def from_args(cls, args) -> "Genome":
        tokens = list(args)
        # The global filter comes first and is not part of any stanza.
        split_at = next(
            (i for i, t in enumerate(tokens) if not t.startswith("--wf-")),
            len(tokens),
        )
        header, rest = tokens[:split_at], tokens[split_at:]

        sections, current = [], []
        for token in rest:
            if token == SECTION_SEPARATOR:
                sections.append(Section(tuple(current)))
                current = []
            else:
                current.append(token)
        if current:
            sections.append(Section(tuple(current)))

        return cls(tuple(header), tuple(sections))

    def to_args(self) -> list[str]:
        args = list(self.header)
        for index, section in enumerate(self.sections):
            if index:
                args.append(SECTION_SEPARATOR)
            args.extend(section.tokens)
        return args

    @property
    def signature(self) -> str:
        """Cache key. Two genomes that render alike are the same experiment."""
        return "\x00".join(self.to_args())

    def replace_section(self, index: int, section: Section) -> "Genome":
        sections = list(self.sections)
        sections[index] = section
        return Genome(self.header, tuple(sections))

    def summary(self) -> str:
        """Compact description of what distinguishes this genome."""
        modes, extras = [], []
        for section in self.sections:
            for mode in section.desync_modes():
                if mode not in modes:
                    modes.append(mode)
            for token in section.tokens:
                flag, value = _split_token(token)
                if flag in TTL_FLAGS and value not in extras:
                    extras.append(f"{flag.rsplit('-', 1)[-1]}={value}")
        return " ".join(["+".join(modes) or "none", *extras])


# ------------------------------------------------------------------- pools


@lru_cache(maxsize=1)
def gene_pools() -> dict[tuple[str, str], tuple[str, ...]]:
    """Observed values per ``(transport, flag)``, harvested from the 21 configs.

    Keying on transport is what keeps a mutation type-correct without encoding
    winws' rules: TCP-only desync modes are never in a UDP stanza's pool, and a
    ``--dpi-desync-fake-quic`` gene can only ever draw a QUIC payload, because
    those are the only values the corpus pairs with that flag.
    """
    observed: dict[tuple[str, str], list[str]] = {}
    for _, args in load_raw_configs():
        for section in Genome.from_args(args).sections:
            transport = section.transport
            for token in section.tokens:
                flag, value = _split_token(token)
                if flag in GENE_FLAGS:
                    bucket = observed.setdefault((transport, flag), [])
                    if value not in bucket:
                        bucket.append(value)

    pools = {key: tuple(values) for key, values in observed.items()}
    for (transport, flag) in list(pools):
        if flag in AUGMENTED_POOLS:
            pools[(transport, flag)] = AUGMENTED_POOLS[flag]
    return pools


def pool_for(transport: str, flag: str) -> tuple[str, ...]:
    return gene_pools().get((transport, flag), ())


# --------------------------------------------------------------- operators


def mutate(genome: Genome, rng: random.Random, *, rate: float = 0.25) -> Genome:
    """Rewrite a few genes at random. Always changes at least one.

    Guarantees a change so a generation cannot silently fill with clones of its
    parents — each individual costs a live probe run, so duplicates are wasted
    wall-clock, not just wasted diversity.
    """
    candidates = [
        (section_index, token_index)
        for section_index, section in enumerate(genome.sections)
        for token_index in section.gene_indices
        if len(pool_for(section.transport, _split_token(section.tokens[token_index])[0])) > 1
    ]
    if not candidates:
        return _mutate_ttl(genome, rng) or genome

    count = max(1, int(round(len(candidates) * rate)))
    mutated = genome
    for section_index, token_index in rng.sample(candidates, min(count, len(candidates))):
        section = mutated.sections[section_index]
        flag, value = _split_token(section.tokens[token_index])
        alternatives = [v for v in pool_for(section.transport, flag) if v != value]
        if not alternatives:
            continue
        new_token = f"{flag}={rng.choice(alternatives)}"
        mutated = mutated.replace_section(
            section_index, section.with_token(token_index, new_token)
        )

    # TTL is the one knob the pack never varies, so it gets an independent roll.
    if rng.random() < 0.3:
        mutated = _mutate_ttl(mutated, rng) or mutated
    return mutated


def _mutate_ttl(genome: Genome, rng: random.Random) -> Genome | None:
    """Add, retune or drop the TTL gene of one randomly chosen stanza."""
    fake_sections = [
        i for i, section in enumerate(genome.sections)
        if any("fake" in mode for mode in section.desync_modes())
    ]
    if not fake_sections:
        return None

    index = rng.choice(fake_sections)
    section = genome.sections[index]
    existing = section.ttl_index()
    tokens = list(section.tokens)

    if existing is not None and rng.random() < 0.25:
        tokens.pop(existing)
        return genome.replace_section(index, Section(tuple(tokens)))

    flag = rng.choice(TTL_FLAGS)
    token = f"{flag}={rng.choice(TTL_POOLS[flag])}"
    if existing is not None:
        tokens[existing] = token
    else:
        # Sit next to the mode it modifies rather than at the end of the stanza.
        anchor = next(
            (i for i, t in enumerate(tokens) if _split_token(t)[0] == "--dpi-desync"),
            len(tokens) - 1,
        )
        tokens.insert(anchor + 1, token)
    return genome.replace_section(index, Section(tuple(tokens)))


def crossover(first: Genome, second: Genome, rng: random.Random) -> Genome:
    """Take each stanza from one parent or the other, matched by role.

    Stanzas are paired by what they filter, not by position: the configs differ
    in stanza count, and splicing a Discord-voice stanza onto a YouTube filter
    would be recombination in name only. A stanza the other parent does not
    have is inherited from the primary one unchanged.
    """
    donors: dict[tuple, list[Section]] = {}
    for section in second.sections:
        donors.setdefault(section.role, []).append(section)

    taken: dict[tuple, int] = {}
    sections = []
    for section in first.sections:
        role = section.role
        available = donors.get(role, ())
        position = taken.get(role, 0)
        if position < len(available) and rng.random() < 0.5:
            sections.append(available[position])
        else:
            sections.append(section)
        taken[role] = position + 1

    return Genome(first.header, tuple(sections))


def seed_population(rng: random.Random, size: int) -> list[Genome]:
    """Shipped configs first, then mutants of them to fill the population.

    Generation zero is deliberately the pack itself: it starts the search at the
    best known point instead of at random, so the result can only improve on
    what the plain benchmark would have picked.
    """
    presets = [Genome.from_args(args) for _, args in load_raw_configs()]
    if not presets:
        return []

    population = presets[:size]
    while len(population) < size:
        population.append(mutate(rng.choice(presets), rng))
    return population
