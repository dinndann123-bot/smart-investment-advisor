"""Smart Investment Advisor startup bootstrap.

Kept intentionally small: presentation assets are explicit static modules and
strategy/data logic stays in the FastAPI application. No HTML rewriting,
route wrapping, fetch interception, cache deletion, or UI monkey patching.
"""
print("CANONICAL_STARTUP=true")
