from functools import wraps

from django.conf import settings

from auditlog.context import auditlog_disabled
from auditlog.diff import model_instance_diff
from auditlog.models import LogEntry
from auditlog.signals import post_log, pre_log, pre_bulk_log, post_bulk_log
from typing import List
from auditlog.threadlocal import register_log_entry, get_audit_log_entries, clear_audit_log_entries
from auditlog.logging import setup_logger
from django.db import models
from copy import deepcopy

logger = setup_logger()


def save_log_entries_registered():
    try:
        log_entries = get_audit_log_entries()
        LogEntry.objects.bulk_create(log_entries)
    except Exception as exception:
        logger.exception(
            f"Save entries registered - Entries: {[entry.__dict__ for entry in log_entries]} - Error: {exception}"
        )
    finally:
        clear_audit_log_entries()


def check_disable(signal_handler):
    """
    Decorator that passes along disabled in kwargs if any of the following is true:
    - 'auditlog_disabled' from threadlocal is true
    - raw = True and AUDITLOG_DISABLE_ON_RAW_SAVE is True
    """

    @wraps(signal_handler)
    def wrapper(*args, **kwargs):
        try:
            auditlog_disabled_value = auditlog_disabled.get()
        except LookupError:
            auditlog_disabled_value = False
        if not auditlog_disabled_value and not (kwargs.get("raw") and settings.AUDITLOG_DISABLE_ON_RAW_SAVE):
            signal_handler(*args, **kwargs)

    return wrapper


@check_disable
def log_bulk_create(*args, **kwargs):
    sender: models.Model = kwargs['sender']
    objects: models.Model = kwargs['objects']

    pre_bulk_log.send(sender=sender, objects=objects, created=True)

    log_entries = []

    for instance in objects:
        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.CREATE,
            instance=instance,
            sender=sender,
            diff_old=None,
            diff_new=instance,
        )

        if log_entry is not None:
            log_entries.append(log_entry)

    register_log_entry(log_entries)

    post_bulk_log.send(sender=sender, objects=objects, created=True)


@check_disable
def log_bulk_update(*args, **kwargs):
    sender: models.Model = kwargs['sender']
    objects: models.Model = kwargs['objects']
    fields = kwargs['fields']

    original_instances = {obj.pk: obj for obj in sender._default_manager.filter(pk__in=[obj.pk for obj in objects])}

    pre_bulk_log.send(sender=sender, objects=original_instances, new_objects=objects, fields=fields, created=False)

    log_entries = []

    for new_instance in objects:
        instance = original_instances.get(new_instance.pk)

        if instance is None:
            logger.warning(f'Record not found or not access permission: Instance: {new_instance.__dict__}.')
            continue

        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.UPDATE,
            instance=instance,
            sender=sender,
            diff_old=instance,
            diff_new=new_instance,
            fields_to_check=fields,
        )

        if log_entry is not None:
            log_entries.append(log_entry)

    register_log_entry(log_entries)

    post_bulk_log.send(sender=sender, objects=original_instances, new_objects=objects, fields=fields, created=False)


@check_disable
def log_query_update(*args, **kwargs):
    sender = kwargs['sender']
    queryset = kwargs['queryset']
    update_kwargs = kwargs['update_kwargs']

    pre_bulk_log.send(sender=sender, queryset=queryset, update_kwargs=update_kwargs, created=False)

    log_entries = []

    for instance in queryset:
        new_instance = deepcopy(instance)
        update_fields = []

        for field, new_value in update_kwargs.items():
            setattr(new_instance, field, new_value)
            update_fields.append(field)

        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.UPDATE,
            instance=instance,
            sender=kwargs['sender'],
            diff_old=instance,
            diff_new=new_instance,
            fields_to_check=update_fields,
        )

        if log_entry is not None:
            log_entries.append(log_entry)

    register_log_entry(log_entries)

    post_bulk_log.send(sender=sender, queryset=queryset, update_kwargs=update_kwargs, created=False)


@check_disable
def log_create(sender, instance, created, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is first saved to the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if created:
        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.CREATE,
            instance=instance,
            sender=sender,
            diff_old=None,
            diff_new=instance,
        )

        if log_entry is not None:
            register_log_entry([log_entry])


@check_disable
def log_update(sender, instance, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is changed and saved to the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if not instance._state.adding:
        update_fields = kwargs.get("update_fields", None)
        old = sender._default_manager.filter(pk=instance.pk).first()

        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.UPDATE,
            instance=instance,
            sender=sender,
            diff_old=old,
            diff_new=instance,
            fields_to_check=update_fields,
        )

        if log_entry is not None:
            register_log_entry([log_entry])


@check_disable
def log_delete(sender, instance, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is deleted from the database.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if instance.pk is not None:
        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.DELETE,
            instance=instance,
            sender=sender,
            diff_old=instance,
            diff_new=None,
        )

        if log_entry is not None:
            register_log_entry([log_entry])


def log_access(sender, instance, **kwargs):
    """
    Signal receiver that creates a log entry when a model instance is accessed in a AccessLogDetailView.

    Direct use is discouraged, connect your model through :py:func:`auditlog.registry.register` instead.
    """
    if instance.pk is not None:
        log_entry = _create_instance_log_entry(
            action=LogEntry.Action.ACCESS,
            instance=instance,
            sender=sender,
            diff_old=None,
            diff_new=None,
            force_log=True,
        )

        if log_entry is not None:
            register_log_entry([log_entry])


def _create_instance_log_entry(action, instance, sender, diff_old, diff_new, fields_to_check=None, force_log=False) -> LogEntry:
    pre_log_results = pre_log.send(
        sender,
        instance=instance,
        action=action,
    )

    if any(item[1] is False for item in pre_log_results):
        return

    error = None
    log_entry = None
    changes = None
    
    try:
        changes = model_instance_diff(diff_old, diff_new, fields_to_check=fields_to_check)

        if force_log or changes:
            log_entry = LogEntry.objects.create_instance(
                instance,
                action=action,
                changes=changes,
                force_log=force_log,
            )
    except BaseException as e:
        error = e
    finally:
        if log_entry or error:
            post_log.send(
                sender,
                instance=instance,
                instance_old=diff_old,
                action=action,
                error=error,
                pre_log_results=pre_log_results,
                changes=changes,
                log_entry=log_entry,
                log_created=log_entry is not None,
            )
        if error:
            raise error

    return log_entry


def make_log_m2m_changes(field_name):
    """Return a handler for m2m_changed with field_name enclosed."""

    @check_disable
    def log_m2m_changes(signal, action, **kwargs):
        """Handle m2m_changed and call LogEntry.objects.log_m2m_changes as needed."""
        if action not in ["post_add", "post_clear", "post_remove"]:
            return

        if action == "post_clear":
            changed_queryset = kwargs["model"]._default_manager.all()
        else:
            changed_queryset = kwargs["model"]._default_manager.filter(pk__in=kwargs["pk_set"])

        log_entry = None

        if action in ["post_add"]:
            log_entry = LogEntry.objects.create_instance_log_m2m_changes(
                changed_queryset,
                kwargs["instance"],
                "add",
                field_name,
            )
        elif action in ["post_remove", "post_clear"]:
            log_entry = LogEntry.objects.create_instance_log_m2m_changes(
                changed_queryset,
                kwargs["instance"],
                "delete",
                field_name,
            )

        if log_entry:
            register_log_entry([log_entry])

    return log_m2m_changes
