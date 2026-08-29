"""Skill: flip a coin. Voice: 'flip a coin' (via agent loop)."""


def register(registry, ctx):
    import random

    registry.register(
        "coin_flip",
        "Flip a coin, heads or tails",
        {},
        lambda: {"result": random.choice(["heads", "tails"])},
    )
