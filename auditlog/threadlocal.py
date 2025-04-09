from threading import local
from typing import List
from .models import LogEntry
from django.conf import settings


_audit_log_thread_locals = local()
_audit_log_key = getattr(settings, "AUDIT_LOG_THREAD_LOCAL_KEY", "audit_log_entries")


def get_audit_log_entries() -> List[LogEntry]:
    if not hasattr(_audit_log_thread_locals, _audit_log_key):
        return []
    return getattr(_audit_log_thread_locals, _audit_log_key).copy()


def clear_audit_log_entries() -> None:
    setattr(_audit_log_thread_locals, _audit_log_key, [])


def register_log_entry(log_entry_list: List[LogEntry]) -> None:
    setattr(_audit_log_thread_locals, _audit_log_key, log_entry_list.copy())
