
# ai/policy_linucb.py
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass
class LinUCBArm:
    d: int
    alpha: float = 0.5
    A: np.ndarray = field(init=False)
    b: np.ndarray = field(init=False)

    def __post_init__(self):
        self.A = np.eye(self.d)
        self.b = np.zeros((self.d, 1))

    def theta(self) -> np.ndarray:
        A_inv = np.linalg.inv(self.A)
        return A_inv @ self.b

    def ucb(self, x: np.ndarray) -> float:
        x = x.reshape(-1, 1)
        A_inv = np.linalg.inv(self.A)
        mean = float((self.theta().T @ x)[0,0])
        bonus = self.alpha * float(np.sqrt(x.T @ A_inv @ x)[0,0])
        return mean + bonus

    def update(self, x: np.ndarray, reward: float) -> None:
        x = x.reshape(-1, 1)
        self.A += x @ x.T
        self.b += reward * x

class LinUCBPolicy:
    """
    A simple contextual bandit to choose between actions (arms)
    based on feature vector x. Each arm learns linearly.
    """
    def __init__(self, arms: Dict[str, LinUCBArm]):
        self.arms = arms

    def select(self, x: np.ndarray) -> str:
        scores = {a: arm.ucb(x) for a, arm in self.arms.items()}
        return max(scores, key=scores.get)

    def update(self, action: str, x: np.ndarray, reward: float) -> None:
        self.arms[action].update(x, reward)
