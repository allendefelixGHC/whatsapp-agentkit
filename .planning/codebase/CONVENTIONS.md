# Coding Conventions

**Analysis Date:** 2026-03-27

## Naming Patterns

**Files:**
- Snake_case for all Python modules: `brain.py`, `email_service.py`, `test_flows.py`
- Descriptive names that match the module's role: `ghl.py` (integration), `session.py` (cache), `providers/whapi.py` (adapter)

**Functions:**
- Snake_case in Spanish for domain functions: `generar_respuesta`, `guardar_mensaje`, `obtener_historial`, `parsear_webhook`
- Private/internal helpers prefixed with underscore: `_headers()`, `_get_config()`, `_ejecutar_herramienta()`, `_descargar_imagen_base64()`, `_construir_respuesta_interactiva()`
- Async functions named identically to sync equivalents — asyncness is inferred from context

**Variables:**
- Snake_case in Spanish for domain variables: `proveedor`, `historial`, `respuesta`, `telefono`, `mensajes`
- ALL_CAPS for module-level constants: `CACHE_TTL`, `API_BASE`, `GHL_API_KEY`, `PIPELINE_ID`, `STAGES`, `TELEFONO_BASE`
- Underscore-prefixed for module-level mutable state: `_config_cache`, `_propiedades_cache`, `_round_robin_counter`, `_cache`

**Classes:**
- PascalCase: `ProveedorWhatsApp`, `ProveedorWhapi`, `MensajeEntrante`, `Respuesta`, `Boton`, `FilaLista`, `SeccionLista`, `Mensaje`
- Dataclasses used for value objects (no methods, pure data): `MensajeEntrante`, `Respuesta`, `Boton`, `FilaLista`, `SeccionLista`
- ABC for interfaces: `ProveedorWhatsApp(ABC)` in `agent/providers/base.py`

**Loggers:**
- Always named `"agentkit"` across all modules: `logger = logging.getLogger("agentkit")`
- Single logger name enables unified log filtering

## Code Style

**Formatting:**
- No formatter config file detected (no `.prettierrc`, `pyproject.toml` with black config, or `.flake8`)
- Code style is consistent but enforced manually
- 4-space indentation throughout
- Single blank line between methods, double blank line between top-level definitions

**Linting:**
- No linting config detected
- f-strings used universally for string formatting (no `.format()` or `%`)
- Type hints used on function signatures throughout, including `list[dict]`, `str | None`, `dict | int | None`

**Line length:**
- No enforced limit; long lines appear in inline comments and string literals

## Import Organization

**Order:**
1. Standard library (`os`, `re`, `yaml`, `json`, `logging`, `datetime`, `asyncio`, `base64`, `smtplib`)
2. Third-party (`fastapi`, `anthropic`, `httpx`, `sqlalchemy`, `dotenv`)
3. Local imports (`from agent.brain import ...`, `from agent.providers import ...`)

**Import style:**
- Explicit named imports preferred: `from agent.brain import generar_respuesta`
- Module aliasing only when collision exists: `import httpx as httpx_client` in `agent/main.py`
- `load_dotenv()` called at module top-level in every file that reads env vars

**Path aliases:**
- None — all imports use full dotted paths from project root (e.g., `from agent.providers.base import Respuesta`)

## Error Handling

**Strategy:** Broad `try/except Exception as e` at the boundary, with specific fallback behavior inside.

**Patterns:**
- All async HTTP calls wrapped in `try/except Exception`: `ghl.py`, `brain.py`, `whapi.py`
- On external API failure: return a safe default (`{}`, `None`, `False`, fallback string) — never propagate to webhook handler
- Webhook handlers (`main.py`) use a final catch-all that raises `HTTPException(status_code=500)` for the main webhook, but returns `{"status": "error"}` for the GHL webhook (to avoid re-delivery retries)
- `traceback.format_exc()` imported inline inside `except` blocks (not at module top) and attached to error log
- Config file not found: log error + return `{}` — system continues with default fallback strings
- Token/credential not configured: log warning + return `False` or `{"error": "..."}` — never raise

**Example pattern:**
```python
try:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload, headers=_headers())
        if r.status_code in (200, 201):
            return {...}
        else:
            logger.error(f"Error GHL: {r.status_code} — {r.text}")
            return {"error": f"Error {r.status_code}"}
except Exception as e:
    logger.error(f"Error descriptivo: {e}")
    return {"error": str(e)}
```

## Logging

**Framework:** Python standard `logging`, single logger named `"agentkit"` in every module.

**Log levels:**
- `DEBUG` — interactive/typing indicators, raw parsed data: `logger.debug(f"Reply raw data: {reply_data}")`
- `INFO` — successful operations and key decisions: `logger.info(f"Oportunidad {opp_id} movida a: {stage}")`
- `WARNING` — missing config or expected-but-absent data: `logger.warning("WHAPI_TOKEN no configurado")`
- `ERROR` — caught exceptions and API failures: `logger.error(f"Error GHL: {r.status_code} — {r.text}")`

**Log format conventions:**
- Include relevant identifiers: `f"Contacto GHL creado: {contact.get('id')} — {nombre} ({tel_limpio})"`
- Truncate long strings in logs: `{respuesta.texto[:100]}`, `{url[:80]}`
- Include `\n{traceback.format_exc()}` appended to error log when exception traceback is needed

**Level switching:**
- Log level set at startup based on `ENVIRONMENT` env var: `DEBUG` in development, `INFO` in production

## Comments

**When to comment:**
- Module docstring always present (triple-quoted, explains purpose and usage)
- One-line `# comment` before non-obvious code blocks
- Inline comments (`# "user" o "assistant"`) on model field definitions for context
- Section delimiters with `# ====` used in `tools.py` and `test_flows.py` for long files

**Header convention:**
Every file starts with a comment on line 1:
```python
# agent/module.py — Short description
# Generado por AgentKit
```

**Language:**
- Comments are in Spanish
- Variable names are Spanish
- English is used only in third-party API field names and HTTP headers

## Function Design

**Size:** Functions are generally 20-50 lines. The longest functions (`generar_respuesta` in `brain.py`, `webhook_handler` in `main.py`) are 80-100 lines but handle complex multi-step flows.

**Parameters:**
- Default parameters used extensively for optional fields: `nombre: str = ""`, `pagina: int = 1`
- `telefono: str` appears as a first or key parameter across all public API functions
- No `**kwargs` used; all parameters are explicit

**Return values:**
- Consistent return types per module: `ghl.py` returns `dict` (with `"error"` key on failure), `memory.py` returns `list[dict]`, providers return `bool`
- `None` returned when a lookup finds nothing: `buscar_contacto_por_email`, `buscar_oportunidad_por_contacto`
- `Respuesta` dataclass used as the return type for all AI-generated content (`brain.py`)

## Module Design

**Exports:**
- No `__all__` defined; public API is conventional (no leading underscore)
- `agent/providers/__init__.py` exports a factory function `obtener_proveedor()` — consumers never import provider classes directly

**Initialization pattern:**
- Module-level config loaded at import time: `DATABASE_URL`, `GHL_API_KEY`, `MODEL`, `API_BASE`
- In-memory caches initialized as module-level variables: `_config_cache = None`, `_propiedades_cache = []`
- Lazy loading used for config that requires file I/O: `_get_config()` reads `prompts.yaml` on first call and caches

**Dataclasses:**
- Used for all structured data that crosses layer boundaries: `MensajeEntrante`, `Respuesta`, `Boton`, `FilaLista`, `SeccionLista` in `agent/providers/base.py`
- `field(default_factory=list)` used for mutable default fields

---

*Convention analysis: 2026-03-27*
