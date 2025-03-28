from django.apps import AppConfig, apps
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from auditlog.signals_bulk_operation import (
    pre_bulk_create,
    post_bulk_create,
    pre_bulk_update,
    post_bulk_update,
    pre_query_update,
    post_query_update,
)
from django.db import transaction
from registry import auditlog


class AuditlogConfig(AppConfig):
    name = "auditlog"
    verbose_name = _("Audit log")
    default_auto_field = "django.db.models.AutoField"

    def _skip_signal(self, kwargs):
        skip_key = getattr(settings, "BULK_SIGNALS_SKIP_KEY", "skip_signal")
        return kwargs.pop(skip_key, False) is True

    def _skip_model_without_audit_log_recorded(self, model_label: str):
        return model_label not in auditlog.get_models()

    def ready(self):
        from auditlog.registry import auditlog

        auditlog.register_from_settings()

        from auditlog import models

        models.changes_func = models._changes_func()

        # Bulk Operation signals

        from django.db.models.query import QuerySet

        base_bulk_create = QuerySet.bulk_create

        def bulk_create(queryset, objs, **kwargs):
            mode_name = queryset.model._meta.label

            if self._skip_signal(kwargs) or self._skip_model_without_audit_log_recorded(mode_name):
                return base_bulk_create(queryset, objs, **kwargs)

            model = apps.get_model(mode_name)

            pre_bulk_create.send(sender=model, objects=objs, **kwargs)
            created_objects = base_bulk_create(queryset, objs, **kwargs)
            post_bulk_create.send(sender=model, objects=objs, **kwargs)

            return created_objects

        QuerySet.bulk_create = bulk_create

        base_bulk_update = QuerySet.bulk_update

        def bulk_update(queryset, objs, fields, **kwargs):
            queryset._hints["is_bulk_update"] = True

            mode_name = queryset.model._meta.label

            if self._skip_signal(kwargs) or self._skip_model_without_audit_log_recorded(mode_name):
                return base_bulk_update(queryset, objs, fields, **kwargs)

            model = apps.get_model(mode_name)

            with transaction.atomic():
                pre_bulk_update.send(sender=model, objects=objs, fields=fields, **kwargs)
                return_value = base_bulk_update(queryset, objs, fields, **kwargs)
                post_bulk_update.send(sender=model, objects=objs, fields=fields, **kwargs)

                return return_value

        QuerySet.bulk_update = bulk_update

        base_update = QuerySet.update

        def update(queryset, **kwargs):
            mode_name = queryset.model._meta.label

            if self._skip_signal(kwargs) or self._skip_model_without_audit_log_recorded(mode_name):
                return base_update(queryset, **kwargs)

            model = apps.get_model(mode_name)

            if queryset._hints.get("is_bulk_update", False):
                return base_update(queryset, **kwargs)

            with transaction.atomic():
                pre_query_update.send(sender=model, queryset=queryset, update_kwargs=kwargs)
                return_val = base_update(queryset, **kwargs)
                post_query_update.send(
                    sender=model,
                    queryset=queryset,
                    update_kwargs=kwargs,
                    update_count=return_val,
                )

                return return_val

        QuerySet.update = update
