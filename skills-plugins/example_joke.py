"""Example xarvii plugin: adds a 'random_fact' tool the agent can call."""


def register(registry, ctx):
    import random

    FACTS = [
        "Sea otters hold hands while sleeping so they don't drift apart.",
        "Wombat poop is cube-shaped.",
        "The shortest war in history lasted 38 minutes.",
    ]

    def random_fact() -> dict:
        return {"fact": random.choice(FACTS)}

    registry.register(
        "random_fact",
        "One random interesting fact",
        {},
        random_fact,
    )
