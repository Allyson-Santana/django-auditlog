Claro! Abaixo está sua proposta original com pequenas edições para melhorar a clareza, fluidez e incorporar os pontos de atenção que comentei — tudo isso mantendo a estrutura e estilo quase idênticos ao seu original:

---

## Proposta de Novas Funcionalidades para django-auditlog

Olá, pessoal!

Hoje trago dois desafios enfrentados e as respectivas ideias de soluções, e gostaria de contar com a opinião de vocês sobre as propostas.

---

### Contexto

É comum precisarmos capturar e registrar logs de operações em massa, como:

```python
Model.objects.bulk_create(...)
Model.objects.bulk_update(...)
Model.objects.update(...)
```

Porém, essas operações não disparam sinais (signals) do Django, portanto, não são registradas pelo django-auditlog.

---

### 1. Suporte a Operações em Massa

**Problema:**

* `bulk_create`, `bulk_update` e `update` em massa não geram sinais, portanto não são auditados.

**Proposta:**

* Sobrescrever os métodos `bulk_create`, `bulk_update` e `update` para disparar signals. Assim podemos auditar essas operações em massa no banco.

> **Exemplo de código:**
>
> ```python
> signal_global_enable = getattr(settings, "AUDITLOG_BULK_SIGNALS_ENABLE", False)
>
> def _skip_model_without_audit_log_recorded(model: models.Model, auditlog: "AuditlogModelRegistry") -> bool:
>    return model not in auditlog.get_models()
>
> def _skip_bulk_signals_just_this_once(kwargs) -> bool:
>    skip_signal = bool(kwargs.pop("skip_signal", False))
>    return skip_signal or not signal_global_enable
>
> def bulk_create(queryset, objs, **kwargs):
>    mode_name = queryset.model._meta.label
>    model = apps.get_model(mode_name)
>
>    # A função _skip_bulk_signals_just_this_once serve apenas para pular a feature passando um parâmetro customizado como MyModel.objects.bulk_create(objs, skip_signal=True) 
>
>    if _skip_bulk_signals_just_this_once(kwargs) or _skip_model_without_audit_log_recorded(model, auditlog):
>        return base_bulk_create(queryset, objs, **kwargs)
>
>    created_objects = base_bulk_create(queryset, objs, **kwargs)
>    auditlog_post_bulk_create.send(sender=model, objects=objs, **kwargs)
>
>    return created_objects
> ```

> **⚠️ Observações Importantes:**
>
> * A proposta inclui um parâmetro `skip_signal=True` que pode ser passado para ignorar os sinais de auditoria em chamadas específicas.
> * A verificação se o modelo está registrado na `auditlog` garante que a feature afete apenas os modelos desejados.
> * O uso de um flag global (`AUDITLOG_BULK_SIGNALS_ENABLE`) mantém a funcionalidade opcional e segura para uso em produção.

---

### 2. Acúmulo e Persistência Otimizada de Logs

**Problema atual:**

Para cada sinal disparado, o django-auditlog grava imediatamente no banco. Em um update de 10 usuários um por vez, por exemplo, são 10 sinais disparados com mais 10 inserções de log da lib auditlog — no total, 20 interações com o banco de dados.

**Impacto:**

Em sistemas de alta performance, esse volume de chamadas pode degradar a latência e o throughput.

#### Solução proposta

1. **Acúmulo de eventos por requisição (sync/async):**

   * Em cenários síncronos, os eventos podem ser armazenados em um `thread_local`. Contudo, em ambientes assíncronos (ASGI), o `thread_local` não garante isolamento por requisição — mas podemos deixar isso como algo opcional para o cliente ativar e dar tempo pra analisamos os casos para evitar qualquer problemas sistemas com uso de ASGI.

2. **Persistência em lote:**

   * Em um middleware (ou no mesmo middlware existente), ao final da requisição, todos os registros acumulados são gravados de uma só vez com `bulk_create`.
   * O armazenamento (thread-local) é limpo após a gravação.
   * Isso pode reduzir drasticamente a quantidade de interações com o banco. Por exemplo, em um sistema que processa 1000 atualizações por segundo, podemos reduzir de 2000 interações com o banco de dados para apenas 2 por requisição com o uso de bulk create e acumulo de auditlogEntity.

3. **Configurações e feature flags:**

   * Opções para habilitar/desabilitar o acúmulo em memória.
   * Definição de um limite máximo de registros antes de disparar automaticamente o `bulk_create`, evitando estouro de memória.

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


### Conclusão

Em ambos os casos, já possuo implementações quase finalizadas de exemplo funcionando.

Gostaria de saber:

* Essas funcionalidades agregam valor para vocês?
* Faz sentido incorporá-las ao cenário atual da biblioteca?

---
