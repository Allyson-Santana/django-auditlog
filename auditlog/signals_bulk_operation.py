import django.dispatch


auditlog_post_bulk_create = django.dispatch.Signal()

auditlog_pre_bulk_update = django.dispatch.Signal()

auditlog_pre_query_update = django.dispatch.Signal()
