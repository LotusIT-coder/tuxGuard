#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Policy-Engine für den optionalen TuxGuard-System-Login.

Die Policy kapselt bewusst nur Entscheidung/Rate-Limit-Logik.
Die eigentliche biometrische Prüfung erfolgt im Auth-Daemon.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict

from config import Config

MODE_FACE_OR_PASSWORD = "face_or_password"
MODE_FACE_AND_PIN = "face_and_pin"
MODE_PASSWORD_ONLY = "password_only"
_VALID_MODES = {MODE_FACE_OR_PASSWORD, MODE_FACE_AND_PIN, MODE_PASSWORD_ONLY}


@dataclass
class LoginPolicy:
    enabled: bool
    mode: str
    max_attempts: int
    attempt_window_seconds: float
    lockout_seconds: float

    @classmethod
    def from_config(cls) -> "LoginPolicy":
        mode = str(getattr(Config, "SYSTEM_LOGIN_MODE", MODE_FACE_OR_PASSWORD)).lower()
        if mode not in _VALID_MODES:
            mode = MODE_FACE_OR_PASSWORD
        return cls(
            enabled=bool(getattr(Config, "SYSTEM_LOGIN_ENABLED", False)),
            mode=mode,
            max_attempts=max(1, int(getattr(Config, "SYSTEM_LOGIN_MAX_ATTEMPTS", 5))),
            attempt_window_seconds=max(
                1.0, float(getattr(Config, "SYSTEM_LOGIN_ATTEMPT_WINDOW_SECONDS", 60.0))
            ),
            lockout_seconds=max(1.0, float(getattr(Config, "SYSTEM_LOGIN_LOCKOUT_SECONDS", 120.0))),
        )


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    fallback_to_password: bool


class AttemptLimiter:
    """Einfacher In-Memory Rate-Limiter pro Nutzername."""

    _MAX_TRACKED_USERS = 1000

    def __init__(self, policy: LoginPolicy):
        self.policy = policy
        self._attempts: Dict[str, list[float]] = {}
        self._locked_until: Dict[str, float] = {}

    def _prune(self, now: float) -> None:
        """Begrenzt den Speicher gegen DoS mit vielen erfundenen Nutzernamen."""
        window_start = now - self.policy.attempt_window_seconds
        for user in list(self._attempts):
            if not any(t >= window_start for t in self._attempts[user]):
                del self._attempts[user]
        for user in list(self._locked_until):
            if now >= self._locked_until[user]:
                del self._locked_until[user]
        if len(self._attempts) > self._MAX_TRACKED_USERS:
            oldest = sorted(self._attempts, key=lambda u: max(self._attempts[u]))
            for user in oldest[: len(self._attempts) - self._MAX_TRACKED_USERS]:
                del self._attempts[user]

    def allow(self, user_name: str) -> PolicyDecision:
        now = time.time()
        self._prune(now)
        user = (user_name or "").strip().lower() or "*"

        locked_until = float(self._locked_until.get(user, 0.0))
        if now < locked_until:
            return PolicyDecision(
                allowed=False,
                reason="locked",
                fallback_to_password=True,
            )

        window_start = now - self.policy.attempt_window_seconds
        attempts = [t for t in self._attempts.get(user, []) if t >= window_start]
        self._attempts[user] = attempts
        if len(attempts) >= self.policy.max_attempts:
            self._locked_until[user] = now + self.policy.lockout_seconds
            return PolicyDecision(
                allowed=False,
                reason="too_many_attempts",
                fallback_to_password=True,
            )

        return PolicyDecision(allowed=True, reason="ok", fallback_to_password=False)

    def register_attempt(self, user_name: str, success: bool) -> None:
        now = time.time()
        user = (user_name or "").strip().lower() or "*"
        if success:
            self._attempts.pop(user, None)
            self._locked_until.pop(user, None)
            return
        self._attempts.setdefault(user, []).append(now)


def decide_before_auth(policy: LoginPolicy, limiter: AttemptLimiter, user_name: str) -> PolicyDecision:
    if not policy.enabled or policy.mode == MODE_PASSWORD_ONLY:
        return PolicyDecision(
            allowed=False,
            reason="biometric_disabled",
            fallback_to_password=True,
        )
    return limiter.allow(user_name)


def requires_pin_second_factor(policy: LoginPolicy) -> bool:
    return policy.mode == MODE_FACE_AND_PIN
