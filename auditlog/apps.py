from django.apps import AppConfig, apps
from django.utils.translation import gettext_lazy as _
from django.db import transaction, models
from django.db.models.query import QuerySet
from django.conf import settings


class AuditlogConfig(AppConfig):
    name = "auditlog"
    verbose_name = _("Audit log")
    default_auto_field = "django.db.models.AutoField"

    def _skip_model_without_audit_log_recorded(self, model: models.Model):
        from auditlog.registry import auditlog

        return model not in auditlog.get_models()

    def ready(self):
        from auditlog.registry import auditlog

        auditlog.register_from_settings()

        from auditlog import models

        models.changes_func = models._changes_func()

        # Bulk Operation signals

        from auditlog.signals_bulk_operation import (
            pre_bulk_create,
            post_bulk_create,
            pre_bulk_update,
            post_bulk_update,
            pre_query_update,
            post_query_update,
        )
        from auditlog.registry import auditlog

        base_bulk_create = QuerySet.bulk_create

        def bulk_create(queryset, objs, **kwargs):
            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_model_without_audit_log_recorded(model):
                return base_bulk_create(queryset, objs, **kwargs)

            pre_bulk_create.send(sender=model, objects=objs, **kwargs)
            created_objects = base_bulk_create(queryset, objs, **kwargs)
            post_bulk_create.send(sender=model, objects=objs, **kwargs)

            return created_objects

        QuerySet.bulk_create = bulk_create

        base_bulk_update = QuerySet.bulk_update

        def bulk_update(queryset, objs, fields, **kwargs):
            queryset._hints["is_bulk_update"] = True

            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_model_without_audit_log_recorded(model):
                return base_bulk_update(queryset, objs, fields, **kwargs)

            with transaction.atomic():
                pre_bulk_update.send(sender=model, objects=objs, fields=fields, **kwargs)
                return_value = base_bulk_update(queryset, objs, fields, **kwargs)
                post_bulk_update.send(sender=model, objects=objs, fields=fields, **kwargs)

                return return_value

        QuerySet.bulk_update = bulk_update

        base_update = QuerySet.update

        def update(queryset, **kwargs):
            mode_name = queryset.model._meta.label
            model = apps.get_model(mode_name)

            if self._skip_model_without_audit_log_recorded(model):
                return base_update(queryset, **kwargs)

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
