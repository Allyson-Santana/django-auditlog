from threading import local
from typing import List
from .models import LogEntry
from django.conf import settings


_audit_log_thread_locals = local()
_audit_log_key = getattr(settings, "AUDIT_LOG_THREAD_LOCAL_KEY", "audit_log_entries")


def get_audit_log_entries() -> List[LogEntry]:
    if not hasattr(_audit_log_thread_locals, _audit_log_key):
        setattr(_audit_log_thread_locals, _audit_log_key, [])
    return getattr(_audit_log_thread_locals, _audit_log_key)


def clear_audit_log_entries() -> None:
    if hasattr(_audit_log_thread_locals, _audit_log_key):
        setattr(_audit_log_thread_locals, _audit_log_key, [])


def register_log_entry(log_entry_list: List[LogEntry]):
    audit_log_entries = get_audit_log_entries()
    audit_log_entries.extend(log_entry_list)
