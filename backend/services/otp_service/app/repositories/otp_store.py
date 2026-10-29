"""Redis key layout for OTPs (all keys expire on their own -> TTL requirement is enforced by Redis).

  otp:txn:<transaction_id>  -> HASH {code_hash, attempts}      EX = OTP_TTL_SECONDS (300)
        one active OTP per transaction; issuing again overwrites (resend invalidates the old code)
  otp:code:<code_hash>      -> <transaction_id>                SET NX EX 300
        guarantees a code is not shared by two ACTIVE OTPs of different transactions (retry generation on NX failure)
  otp:issued:<transaction_id>   -> INCR counter, EX = window   (max OTPs per transaction: initial + resends)
  otp:cooldown:<transaction_id> -> SET NX EX = cooldown        (min gap between two OTPs of one transaction)

Only a SHA-256 of the code is stored, never the code itself. Save and verify are Lua scripts, so each runs
atomically inside Redis: two concurrent verifies of the same code cannot both succeed (single-use).
"""
import hashlib
from enum import Enum
from redis import Redis

# KEYS[1]=otp:txn:<id>  KEYS[2]=otp:code:<new_hash>   ARGV: txn_id, new_hash, ttl
_SAVE = """
if not redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[3]) then return 0 end
local old = redis.call('HGET', KEYS[1], 'code_hash')
if old and old ~= ARGV[2] then redis.call('DEL', 'otp:code:' .. old) end
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], 'code_hash', ARGV[2], 'attempts', 0)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

# KEYS[1]=otp:txn:<id>   ARGV: candidate_hash, max_attempts
# returns 1 ok | 0 wrong code | -1 no active OTP (expired / used) | -2 wrong code and now locked
_VERIFY = """
local h = redis.call('HGET', KEYS[1], 'code_hash')
if not h then return -1 end
if h == ARGV[1] then
  redis.call('DEL', KEYS[1], 'otp:code:' .. h)
  return 1
end
local n = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if n >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1], 'otp:code:' .. h)
  return -2
end
return 0
"""


class VerifyResult(str, Enum):
    OK = "ok"
    INVALID = "invalid"
    EXPIRED = "expired"
    LOCKED = "locked"


_VERIFY_CODES = {1: VerifyResult.OK, 0: VerifyResult.INVALID, -1: VerifyResult.EXPIRED, -2: VerifyResult.LOCKED}


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class OtpStore:
    def __init__(self, r: Redis, ttl_seconds: int = 300, max_attempts: int = 5):
        self.r, self.ttl, self.max_attempts = r, ttl_seconds, max_attempts
        self._save = r.register_script(_SAVE)
        self._verify = r.register_script(_VERIFY)

    def save(self, transaction_id: str, code: str) -> bool:
        """Make `code` the only active OTP of the transaction. False if another active OTP already uses this code."""
        h = code_hash(code)
        return self._save(keys=[f"otp:txn:{transaction_id}", f"otp:code:{h}"], args=[transaction_id, h, self.ttl]) == 1

    def verify_and_consume(self, transaction_id: str, code: str) -> VerifyResult:
        return _VERIFY_CODES[int(self._verify(keys=[f"otp:txn:{transaction_id}"], args=[code_hash(code), self.max_attempts]))]

    def attempts_left(self, transaction_id: str) -> int:
        used = self.r.hget(f"otp:txn:{transaction_id}", "attempts")
        return max(self.max_attempts - int(used or 0), 0)

    def acquire_issue_slot(self, transaction_id: str, max_issues: int, cooldown_s: int, window_s: int) -> int:
        """Rate limit OTP issuing per transaction. Returns 0 if allowed, else seconds to wait (Retry-After)."""
        cooldown_key = f"otp:cooldown:{transaction_id}"
        if not self.r.set(cooldown_key, 1, nx=True, ex=cooldown_s):
            return max(int(self.r.ttl(cooldown_key)), 1)
        issued_key = f"otp:issued:{transaction_id}"
        with self.r.pipeline() as p:
            n, _ = p.incr(issued_key).expire(issued_key, window_s, nx=True).execute()
        if n > max_issues:
            return max(int(self.r.ttl(issued_key)), 1)
        return 0
