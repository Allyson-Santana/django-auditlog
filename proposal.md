Claro! Aqui está a **tradução para inglês**, já **formatada como uma proposta de Pull Request (PR)** pronta para ser postada no GitHub. Mantive a estrutura e estilo do seu texto, com ajustes para clareza, consistência e tom formal em inglês técnico:

---

## Proposal: Support for Bulk Operations and Optimized Log Persistence in `django-auditlog`

Hi everyone!

I'd like to share two challenges we've encountered, along with proposed solutions, and gather your feedback on whether these ideas would be a good fit for the library.

---

### Context

It's quite common to perform bulk operations such as:

```python
Model.objects.bulk_create(...)
Model.objects.bulk_update(...)
Model.objects.update(...)
```

However, these operations do **not trigger Django signals**, which means `django-auditlog` currently does not capture them.

---

### 1. Support for Bulk Operations

**Problem:**

* Methods like `bulk_create`, `bulk_update`, and `update` do not trigger signals, and therefore are not audited.

**Proposed Solution:**

* Override `bulk_create`, `bulk_update`, and `update` to manually trigger custom signals, allowing audit logging for bulk operations at the database level.

> **A part of Example implementation:**
>
> ```python
> signal_global_enable = getattr(settings, "AUDITLOG_BULK_SIGNALS_ENABLE", False)
>
> def _skip_model_without_audit_log_recorded(model: models.Model, auditlog: "AuditlogModelRegistry") -> bool:
>     return model not in auditlog.get_models()
>
> def _skip_bulk_signals_just_this_once(kwargs) -> bool:
>     skip_signal = bool(kwargs.pop("skip_signal", False))
>     return skip_signal or not signal_global_enable
>
> def bulk_create(queryset, objs, **kwargs):
>     mode_name = queryset.model._meta.label
>     model = apps.get_model(mode_name)
>
>     # The _skip_bulk_signals_just_this_once function allows skipping audit for a specific call like:
>     # MyModel.objects.bulk_create(objs, skip_signal=True)
>
>     if _skip_bulk_signals_just_this_once(kwargs) or _skip_model_without_audit_log_recorded(model, auditlog):
>         return base_bulk_create(queryset, objs, **kwargs)
>
>     created_objects = base_bulk_create(queryset, objs, **kwargs)
>     auditlog_post_bulk_create.send(sender=model, objects=objs, **kwargs)
>
>     return created_objects
> ```

> **⚠️ Key Points:**
>
> * A `skip_signal=True` parameter allows users to skip auditing on a case-by-case basis.
> * Checking whether the model is registered in `auditlog` ensures this only affects tracked models.
> * A global flag (`AUDITLOG_BULK_SIGNALS_ENABLE`) makes this behavior entirely optional and safe for production environments.

---

### 2. Optimized Log Accumulation and Persistence

**Current Problem:**

Each signal triggered by `django-auditlog` results in an immediate write to the database. For example, updating 10 users individually results in 10 signal triggers and 10 log inserts — **20 total DB interactions**.

**Impact:**

In high-performance systems, this can significantly degrade throughput and increase latency.

#### Proposed Solution

1. **Per-request accumulation (sync/async):**

   * In synchronous contexts, events can be stored in `thread_local`.
   * In ASGI (async) environments, `thread_local` does not guarantee request isolation — so we propose this as an optional feature for users to enable, while we continue evaluating safe async-compatible strategies.

2. **Batch persistence:**

   * A middleware (or an extension to an existing one) would flush all accumulated records at the end of each request using `bulk_create`.
   * The temporary storage (e.g., thread-local) is cleared after flushing.
   * This can drastically reduce DB interaction. For instance, a system processing 1000 updates per second could go from 2000 DB writes to just **2 writes per request** when using log accumulation + `bulk_create`.

3. **Configuration & Feature Flags:**

   * Settings to enable/disable in-memory accumulation.
   * Optional max-record limits that trigger a flush automatically to avoid memory overflow.

---


> **A part of Example implementation:**
>
> ```python
> ############# File Middleware #############
>class AuditlogMiddleware:
>
>    def __call__(self, request):
>        remote_addr = self._get_remote_addr(request)
>        remote_port = self._get_remote_port(request)
>        user = self._get_actor(request)
>
>        set_cid(request)
>
>        with set_actor(actor=user, remote_addr=remote_addr, remote_port=remote_port):
>            response = self.get_response(request)
>
>        _save_log_entries_registered() # here
>
>        return response
>
> ############# File receivers #############
>@check_disable
>def log_bulk_create(*args, **kwargs):
>    sender: models.Model = kwargs['sender']
>    objects: models.Model = kwargs['objects']
>
>    log_entries = []
>
>    for instance in objects:
>        log_entry = _create_instance_log_entry(
>            action=LogEntry.Action.CREATE,
>            instance=instance,
>            sender=sender,
>            diff_old=None,
>            diff_new=instance,
>        )
>
>        if log_entry is not None:
>            log_entries.append(log_entry)
>
>    _register_log_entry(log_entries)
>
>def _create_instance_log_entry(
>    action, instance, sender, diff_old, diff_new, fields_to_check=None, force_log=False
>) -> LogEntry:
>    pre_log_results = pre_log.send(
>        sender,
>        instance=instance,
>        action=action,
>    )
>
>    if any(item[1] is False for item in pre_log_results):
>        return
>
>    log_entry, changes, error = _create_log_entry(action, instance, diff_old, diff_new, fields_to_check, force_log)
>
>    if log_entry or error:
>        post_log.send(
>            sender,
>            instance=instance,
>            instance_old=diff_old,
>            action=action,
>            error=error,
>            pre_log_results=pre_log_results,
>            changes=changes,
>            log_entry=log_entry,
>            log_created=log_entry is not None,
>        )
>    if error:
>        raise error
>
>    return log_entry
>
> # The file called register should have a line like this in __init__:
> # self._signals[auditlog_post_bulk_create] = log_bulk_create
> ```



### Conclusion

In both cases, we already have working proof-of-concept implementations.

I would like to know your opinion:

* Do these features add value for your use cases?
* Does it make sense to incorporate them into the current roadmap of the library?

Thanks in advance!

---