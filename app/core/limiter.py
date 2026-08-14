from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory storage is correct here (not a Redis-backed store): this API
# runs as a single process with no --workers flag, so per-process counters
# already give accurate, globally-consistent rate limiting for this
# deployment. Revisit if the deploy ever grows to multiple workers/machines.
#
# Lives in its own module (rather than app.main) so route modules can import
# it for the @limiter.limit(...) decorator without importing app.main itself
# (which imports every router, and would be a circular import).
limiter = Limiter(key_func=get_remote_address)
