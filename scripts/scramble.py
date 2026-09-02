"""Random-move scramble generator for a 3x3 (WCA-style notation).

Not a true random-state scramble, but avoids consecutive moves on the same
face/axis so 20 moves gives a reasonably uniform scramble for a pilot.
"""
import random

FACES = ["U", "D", "L", "R", "F", "B"]
AXIS = {"U": 0, "D": 0, "L": 1, "R": 1, "F": 2, "B": 2}
SUFFIX = ["", "'", "2"]


def generate(length: int = 20, seed: int | None = None) -> str:
    rng = random.Random(seed)
    moves = []
    prev_face, prev_axis = None, None
    for _ in range(length):
        while True:
            face = rng.choice(FACES)
            if face == prev_face:
                continue
            # allow opposite face once, but not three moves on the same axis
            if len(moves) >= 2 and AXIS[face] == prev_axis and AXIS[moves[-2][0]] == prev_axis:
                continue
            break
        moves.append(face + rng.choice(SUFFIX))
        prev_face, prev_axis = face, AXIS[face]
    return " ".join(moves)


if __name__ == "__main__":
    print(generate())
