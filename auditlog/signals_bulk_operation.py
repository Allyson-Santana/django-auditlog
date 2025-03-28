import django.dispatch


pre_bulk_create = django.dispatch.Signal()
post_bulk_create = django.dispatch.Signal()

pre_bulk_update = django.dispatch.Signal()
post_bulk_update = django.dispatch.Signal()

pre_query_update = django.dispatch.Signal()
post_query_update = django.dispatch.Signal()
