from django.apps import AppConfig, apps
from django.utils.translation import gettext_lazy as _
from django.db import transaction, models
from django.db.models.query import QuerySet
from django.conf import settings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auditlog.registry import AuditlogModelRegistry


class AuditlogConfig(AppConfig):
    name = "auditlog"
    verbose_name = _("Audit log")
    default_auto_field = "django.db.models.AutoField"

    def _skip_model_without_audit_log_recorded(self, model: models.Model, auditlog: "AuditlogModelRegistry") -> bool:
        return model not in auditlog.get_models()

    def _skip_bulk_signals(self, kwargs) -> bool:
        skip_signal = bool(kwargs.pop("skip_signal", False))
        return skip_signal or not self.signal_global_enable

    def ready(self):
        self.signal_global_enable = getattr(settings, "AUDITLOG_BULK_SIGNALS_ENABLE", False)

        from auditlog.registry import auditlog

        auditlog.register_from_settings()

        from auditlog import models

        models.changes_func = models._changes_func()

        # Bulk Operation signals

        from auditlog.signals_bulk_operation import (
            auditlog_post_bulk_create,
            auditlog_pre_bulk_update,
            auditlog_pre_query_update,
        )

        base_bulk_create = QuerySet.bulk_create

        def bulk_create(queryset, objs, **kwargs):
            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_bulk_signals(kwargs) or self._skip_model_without_audit_log_recorded(model, auditlog):
                return base_bulk_create(queryset, objs, **kwargs)

            created_objects = base_bulk_create(queryset, objs, **kwargs)
            auditlog_post_bulk_create.send(sender=model, objects=objs, **kwargs)

            return created_objects

        QuerySet.bulk_create = bulk_create

        base_bulk_update = QuerySet.bulk_update

        def bulk_update(queryset, objs, fields, **kwargs):
            queryset._hints["is_bulk_update"] = True

            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_bulk_signals(kwargs) or self._skip_model_without_audit_log_recorded(model, auditlog):
                return base_bulk_update(queryset, objs, fields, **kwargs)

            with transaction.atomic():
                auditlog_pre_bulk_update.send(sender=model, objects=objs, fields=fields, **kwargs)
                return_value = base_bulk_update(queryset, objs, fields, **kwargs)

                return return_value

        QuerySet.bulk_update = bulk_update

        base_update = QuerySet.update

        def update(queryset, **kwargs):
            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_bulk_signals(kwargs) or self._skip_model_without_audit_log_recorded(model, auditlog):
                return base_update(queryset, **kwargs)

            if queryset._hints.get("is_bulk_update", False):
                return base_update(queryset, **kwargs)

            with transaction.atomic():
                auditlog_pre_query_update.send(sender=model, queryset=queryset, update_kwargs=kwargs)
                return_val = base_update(queryset, **kwargs)
                return return_val

        QuerySet.update = update
