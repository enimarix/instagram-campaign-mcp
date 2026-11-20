"""Gym (sets.json `gym`), Polytoon Gym props (CC0): a flat bench in the middle (sit on it to
curl), squat station, dumbbell rack, treadmill, bike, punching bag, plyo box, a rubber floor
with a mat for floor work."""
from kit import box, gym, lamp, mat, room


def build(cfg, spec):
    room(mat("gym_wall", (0.85, 0.82, 0.76), rough=0.9), mat("rubber", (0.12, 0.12, 0.13), rough=0.95),
         mat("gym_ceiling", (0.7, 0.7, 0.7), rough=0.95), back=2.0, left=-3.0, h=3.2)
    box("stripe", (12, 0.02, 0.35), (0, 1.99, 1.3), mat("stripe", (0.95, 0.35, 0.1), rough=0.6))
    box("mat", (1.9, 0.75, 0.02), (-0.75, -1.5, 0.01), mat("mat", (0.15, 0.45, 0.6), rough=0.8))
    gym("Bench", (0, -0.5), 90, 0.45)
    gym("Squat_Station", (-1.7, 1.2), 0, 2.2)
    gym("Dumbell Rack", (1.0, 1.6), 0, 0.9)
    gym("Treadmill", (2.3, 0.4), -90, 1.4)
    gym("Sports Bicycle", (2.2, -1.0), -90, 1.1)
    gym("PunchingBag", (-2.4, -0.6), 0, 1.9)
    gym("Plyo Box", (0.6, 1.0), 20, 0.6)
    lamp("gym_light", (0, -0.3, 3.0), (1.0, 0.9, 0.75), 250, 1.0)
    return None
