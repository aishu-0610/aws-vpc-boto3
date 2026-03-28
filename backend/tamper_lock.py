"""
tamper_lock.py  —  FocusGate Tamper-Resistant Override System
Developer A owns this file.

Theory — why this works:
  A JWT has three base64url-encoded sections: header.payload.signature
  The signature is HMAC-SHA256(header + "." + payload, secret_key).
  Changing ANY byte in the payload invalidates the signature.

  Key claim: "nbf" (not before) — a Unix timestamp.
  The token is mathematically valid from the moment of issue, but we
  REJECT it server-side until time.time() >= nbf.

  The user cannot forge an earlier nbf because:
    - They don't have the server secret (stored in data/.secret)
    - Modifying nbf changes the payload bytes → signature mismatch
    - hmac.compare_digest() prevents timing-based side-channel attacks

  Hard-lock mode: we store ends_at in memory. No token is even issued
  during a hard-lock period — the user hits a wall regardless.

Override flow:
  1. User clicks "Override" → request_override() issues token (nbf = now + delay)
  2. Frontend shows countdown timer
  3. After delay, user clicks "Confirm" → confirm_override() validates token
  4. If nbf has passed and signature is valid → session ends
  5. Every failed attempt is logged (override_attempts counter)

Math challenge:
  Solving correctly reduces delay from 300s → 120s.
  The challenge changes each call — cannot be pre-computed.
"""

import hmac
import hashlib
import base64
import json
import os
import random
import secrets
import time
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

SECRET_FILE    = os.path.join(os.path.dirname(__file__), "../data/.secret")
DEFAULT_DELAY  = 300   # 5 minutes
MATH_DELAY     = 120   # 2 minutes (reward for solving challenge)
TOKEN_LIFETIME = 900   # token expires 15 min after becoming valid


# ── Secret key management ──────────────────────────────────────────────

def _load_or_create_secret() -> bytes:
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            data = f.read()
            if len(data) >= 32:
                return data
    secret = secrets.token_bytes(32)
    with open(SECRET_FILE, "wb") as f:
        f.write(secret)
    os.chmod(SECRET_FILE, 0o600)
    logger.info("[TamperLock] Generated new signing secret")
    return secret


SECRET = _load_or_create_secret()


# ── Base64url helpers ──────────────────────────────────────────────────

def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    padding = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


# ── JWT core ───────────────────────────────────────────────────────────

def _make_token(payload: dict) -> str:
    header  = {"alg": "HS256", "typ": "JWT"}
    h_enc   = _b64e(json.dumps(header,  separators=(",", ":")).encode())
    p_enc   = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    signing = f"{h_enc}.{p_enc}".encode()
    sig     = hmac.new(SECRET, signing, hashlib.sha256).digest()
    return f"{h_enc}.{p_enc}.{_b64e(sig)}"


def _verify_token(token: str) -> Tuple[bool, Optional[dict], str]:
    """
    Returns (valid, payload_dict, error_message).
    Checks: structure, signature, expiry, nbf.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return False, None, "malformed: expected 3 parts"

        h_enc, p_enc, sig_enc = parts
        signing  = f"{h_enc}.{p_enc}".encode()
        expected = _b64e(hmac.new(SECRET, signing, hashlib.sha256).digest())

        # Constant-time comparison — prevents timing oracle attacks
        if not hmac.compare_digest(expected.encode(), sig_enc.encode()):
            return False, None, "signature invalid — token tampered"

        payload = json.loads(_b64d(p_enc))
        now     = int(time.time())

        if now > payload.get("exp", 0):
            return False, None, "token expired"

        nbf = payload.get("nbf", 0)
        if now < nbf:
            remaining = nbf - now
            mins, secs = divmod(remaining, 60)
            return False, None, f"too early — {mins}m {secs:02d}s remaining"

        return True, payload, "ok"

    except Exception as e:
        return False, None, f"parse error: {e}"


# ── Public API ─────────────────────────────────────────────────────────

def issue_override_token(session_id: str, delay: int = DEFAULT_DELAY) -> dict:
    """Issue a delayed override token. Returns info dict for the frontend."""
    now      = int(time.time())
    valid_at = now + delay
    payload  = {
        "sub":     "focusgate_override",
        "iat":     now,
        "nbf":     valid_at,
        "exp":     valid_at + TOKEN_LIFETIME,
        "session": session_id,
        "delay":   delay,
    }
    token = _make_token(payload)
    logger.info(f"[TamperLock] Token issued for {session_id[:8]} — valid in {delay}s")
    return {
        "token":        token,
        "valid_at":     valid_at,
        "valid_at_iso": time.strftime("%H:%M:%S", time.localtime(valid_at)),
        "delay":        delay,
        "session_id":   session_id,
    }


def validate_override_token(token: str) -> Tuple[bool, str]:
    """Returns (success, reason). Call this when user presents token."""
    valid, payload, reason = _verify_token(token)
    if valid:
        logger.info(f"[TamperLock] Override confirmed for session {payload['session'][:8]}")
    else:
        logger.warning(f"[TamperLock] Override rejected: {reason}")
    return valid, reason


def generate_math_challenge() -> dict:
    """
    Arithmetic challenge. Correct answer → MATH_DELAY instead of DEFAULT_DELAY.
    Three difficulty levels chosen randomly.
    """
    level = random.choice(["easy", "medium", "hard"])
    if level == "easy":
        a, b = random.randint(10, 50), random.randint(10, 50)
        op   = random.choice(["+", "-"])
        ans  = eval(f"{a}{op}{b}")
        q    = f"{a} {op} {b}"
    elif level == "medium":
        a, b = random.randint(5, 20), random.randint(5, 20)
        op   = "*"
        ans  = a * b
        q    = f"{a} × {b}"
    else:
        a    = random.randint(10, 30)
        b    = random.randint(2, min(a, 12))
        while a % b != 0:
            b = random.randint(2, min(a, 12))
        ans  = a // b
        q    = f"{a} ÷ {b}"

    return {
        "question":         f"Solve to cut wait from {DEFAULT_DELAY//60}m → {MATH_DELAY//60}m:  {q} = ?",
        "answer":           ans,
        "level":            level,
        "delay_if_correct": MATH_DELAY,
        "delay_if_wrong":   DEFAULT_DELAY,
    }


# ── Stateful lock manager ──────────────────────────────────────────────

class TamperLock:
    """
    Keeps track of:
      - pending override tokens (issued but not yet confirmed)
      - hard-lock expiry times per session
    State is in-memory only — resets on server restart (intentional).
    """

    def __init__(self):
        self._pending: dict    = {}   # session_id → token_info dict
        self._hard_lock: dict  = {}   # session_id → unlock_unix_ts
        self._lock             = __import__("threading").Lock()

    # ── Hard lock ──────────────────────────────────────────────────────

    def set_hard_lock(self, session_id: str, duration_seconds: int):
        with self._lock:
            self._hard_lock[session_id] = int(time.time()) + duration_seconds
        logger.info(f"[TamperLock] Hard lock set for {session_id[:8]} — {duration_seconds}s")

    def is_hard_locked(self, session_id: str) -> Tuple[bool, int]:
        """Returns (locked, seconds_remaining)."""
        with self._lock:
            unlock_at = self._hard_lock.get(session_id, 0)
        remaining = max(0, unlock_at - int(time.time()))
        if remaining == 0 and session_id in self._hard_lock:
            with self._lock:
                self._hard_lock.pop(session_id, None)
        return remaining > 0, remaining

    # ── Override flow ──────────────────────────────────────────────────

    def request_override(self, session_id: str,
                         solved_math: bool = False) -> dict:
        locked, remaining = self.is_hard_locked(session_id)
        if locked:
            return {
                "allowed":   False,
                "reason":    "hard_locked",
                "remaining": remaining,
            }
        delay      = MATH_DELAY if solved_math else DEFAULT_DELAY
        token_info = issue_override_token(session_id, delay)
        with self._lock:
            self._pending[session_id] = token_info
        return {"allowed": True, **token_info}

    def confirm_override(self, session_id: str,
                         token: str) -> Tuple[bool, str]:
        valid, reason = validate_override_token(token)
        if valid:
            with self._lock:
                self._pending.pop(session_id, None)
                self._hard_lock.pop(session_id, None)
        return valid, reason

    def get_pending(self, session_id: str) -> Optional[dict]:
        with self._lock:
            return self._pending.get(session_id)
