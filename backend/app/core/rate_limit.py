"""
Rate limiting for the public API.

Added after deployment made /trip/plan reachable by anyone on the
internet, burning real API quota/cost per request (Groq, Duffel, LiteAPI,
and a BILLED Google Places key) with no limit at all -- a real exposure,
not a hypothetical one, once the URL is public.

Per-IP limiting via slowapi, using Railway's forwarded client IP (see
Procfile's --proxy-headers flag -- without it, every request looks like
it comes from Railway's own proxy, and "per-IP" silently becomes "one
shared global limit for all users combined").

Known limitation, stated honestly: this stops one source hammering the
endpoint, but doesn't stop a determined attacker rotating IPs, and
doesn't protect the GLOBAL quota ceilings some providers enforce
regardless of caller (e.g. Groq's free tier is 30 req/min across the
whole app, not per-IP). A real fix for that would need an app-wide
throttle/queue -- out of scope for this pass.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
