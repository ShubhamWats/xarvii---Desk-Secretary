"""Skill: roll dice. Voice: 'roll a d20'."""


def register(registry, ctx):
    import random

    def roll(sides: int = 6) -> dict:
        return {"roll": random.randint(1, max(2, sides))}

    registry.register("dice_roll", "Roll an N-sided die",
                      {"sides": {"type": "integer"}}, roll)
