import contextlib
import time
from contextvars import ContextVar


auditlog_value = ContextVar("auditlog_value")
auditlog_disabled = ContextVar("auditlog_disabled", default=False)


@contextlib.contextmanager
def set_actor(actor, remote_addr=None, remote_port=None):
    """Guarda informações do ator e contexto de rede na ContextVar."""
    context_data = {
        "user": actor,
        "remote_addr": remote_addr,
        "remote_port": remote_port,
        "timestamp": time.time(),
    }

    token = auditlog_value.set(context_data)

    try:
        yield
    finally:
        auditlog_value.reset(token)


@contextlib.contextmanager
def disable_auditlog():
    token = auditlog_disabled.set(True)
    try:
        yield
    finally:
        try:
            auditlog_disabled.reset(token)
        except LookupError:
            pass
