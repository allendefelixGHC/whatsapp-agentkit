# Testing Patterns

**Analysis Date:** 2026-03-27

## Test Framework

**Runner:**
- No pytest or unittest framework configured
- Tests are standalone async Python scripts executed directly with `python tests/test_flows.py`
- No `pytest.ini`, `setup.cfg`, or `pyproject.toml` test config

**Assertion Library:**
- Custom helper functions replacing assertions: `check_contiene()`, `check_tipo()`, `check_no_contiene()`, `check_tiene_botones()`
- No `assert` statements — failures are printed and counted, never raised

**Run Commands:**
```bash
python tests/test_flows.py                    # Run all 15 flows
python tests/test_flows.py --flow comprar     # Run a single flow
python tests/test_flows.py --verbose          # Show full bot responses
python tests/test_flows.py --list             # List available flows
python tests/test_local.py                    # Interactive REPL chat session
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root

**Files:**
- `tests/test_local.py` — interactive manual chat simulator (not automated)
- `tests/test_flows.py` — automated conversational flow tests (15 flows)
- `tests/TEST_PLAN.md` — human-readable test plan with manual and automated test cases
- `tests/__init__.py` — empty package init

**Naming:**
- Test functions prefixed with `test_` and named after the scenario: `test_cliente_nuevo`, `test_flujo_comprar_completo`, `test_terreno_sin_ambientes`

## Test Structure

**Suite Organization:**
```
tests/
├── __init__.py
├── test_local.py       # Interactive REPL — manual use only
├── test_flows.py       # 15 automated conversation flow tests
└── TEST_PLAN.md        # Manual test checklist + automated test reference
```

**Flow test pattern:**
```python
async def test_flujo_comprar_completo():
    """Test 3: Flujo COMPRAR completo — casa, zona, precio, resultados."""
    tel = f"{TELEFONO_BASE}-comprar-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)        # Isolated phone number per test run

    log_subtitulo("Step name")
    r = await enviar_mensaje(tel, "message or [lista:id] text or [btn:id] text")
    check_contiene(r, ["expected", "keywords"], "Human-readable check description")
    check_tipo(r, "lista", "Expected response type")
```

**Isolation approach:**
- Each test generates a unique phone number using timestamp: `f"{TELEFONO_BASE}-comprar-{int(datetime.now().timestamp())}"`
- `await limpiar_historial(tel)` called at the start of each test
- Tests share a real SQLite database (`agentkit.db`) — no mocking of storage layer

## Mocking

**Framework:** None — no mocking library is used.

**Approach:**
- Tests call the real `generar_respuesta()` function, which makes live Anthropic API calls
- The real database (`SQLite`) is used for all memory operations
- External services (GHL, Whapi.cloud) are not mocked — tests that trigger `registrar_lead_ghl` or `obtener_link_agendar` make real HTTP calls if configured

**What IS isolated:**
- Each test conversation uses a unique phone number to avoid state leakage between test scenarios
- `await limpiar_historial(tel)` ensures a clean slate before each test
- Pre-seeded history can be injected via `await guardar_mensaje(tel, role, content)` to simulate returning customers

**Pre-seeding pattern:**
```python
# Simulate a returning customer with conversation history
await guardar_mensaje(tel, "user", "Hola")
await guardar_mensaje(tel, "assistant", "Hola! Soy Lucía de Bertero. ¿En qué puedo ayudarte?")

r = await enviar_mensaje(tel, "Hola, volví")
check_no_contiene(r, ["soy lucía"], "NOT re-introduce themselves")
```

## Fixtures and Factories

**Test Data:**
- No fixture files or factory functions
- Test data is inline strings in each test function
- Interactive message types encoded as prefixed strings:
  - `"[lista:tipo_casa] Casa"` — simulates list selection with ID `tipo_casa`
  - `"[btn:btn_agendar_llamada] Agendar llamada"` — simulates button click with ID `btn_agendar_llamada`
  - Plain text — simulates free-text message

**Helper `enviar_mensaje` function in `test_flows.py`:**
```python
async def enviar_mensaje(telefono: str, texto: str, historial: list[dict] = None) -> Respuesta:
    """Simulates sending a message and getting a bot response."""
    # Parses [lista:id] and [btn:id] prefixes into context flags
    # Calls generar_respuesta() with proper context injection
    # Saves user message and bot response to memory
    # Returns Respuesta object for assertions
```

**Location:**
- No external fixtures — all test data lives in `tests/test_flows.py`

## Coverage

**Requirements:** None enforced — no coverage configuration or thresholds.

**View Coverage:**
```bash
# No coverage tooling configured. To add:
pip install pytest-cov
pytest tests/ --cov=agent --cov-report=term-missing
```

## Test Types

**Interactive Chat Simulator (`tests/test_local.py`):**
- Scope: Full agent stack (brain, memory, tools)
- Used for: Manual exploratory testing and debugging before automated runs
- Features: `limpiar` command to reset history, displays buttons/lists visually in terminal

**Automated Flow Tests (`tests/test_flows.py`):**
- Scope: End-to-end conversation scenarios including live AI API calls
- 15 flows covering: new client, returning client, buy/rent flows, property types (terreno skips ambientes), custom zone, custom price, schedule call, receive news, portal links, edge cases, fallback
- Each flow runs independently with isolated state
- CLI flags: `--flow <name>`, `--verbose`, `--list`

**Manual Test Plan (`tests/TEST_PLAN.md`):**
- Scope: Human-executed tests for cases that require visual or WhatsApp verification
- Organized into 13 sections covering all major flows + edge cases + error recovery
- Cases marked `(MANUAL)` are excluded from automation (e.g., low-quality photo handling, WhatsApp timeout behavior)

**E2E Tests:**
- Not used as a separate category — all automated tests are effectively E2E (real AI + real DB)

## Common Patterns

**Conversation step pattern:**
```python
log_subtitulo("Step description")
r = await enviar_mensaje(tel, "user input")
check_contiene(r, ["expected", "keywords"], "What we're checking")
```

**Soft assertions:**
- Failures are logged and counted, not raised
- Tests continue even after a failure: `log_fail("description", f"Got: {r.texto[:150]}")`
- Final summary shows total pass/fail count and lists failure descriptions

**Flexible keyword matching:**
```python
# check_contiene uses case-insensitive partial match with OR logic
check_contiene(r, ["lucía", "lucia", "asistente", "bertero"], "Introduces as agent")
# check_no_contiene uses AND logic — fails if ANY of the terms appear
check_no_contiene(r, ["soy lucía", "soy lucia", "asistente virtual de bertero"], "Does not re-introduce")
```

**Async Testing:**
```python
async def test_name():
    tel = f"{TELEFONO_BASE}-scenario-{int(datetime.now().timestamp())}"
    await limpiar_historial(tel)
    r = await enviar_mensaje(tel, "message")
    check_contiene(r, [...], "assertion description")

# Runner entry point
if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
```

**Error boundary in test runner:**
```python
for name, test_fn in tests.items():
    try:
        await test_fn()
    except Exception as e:
        log_fail(f"ERROR en {name}: {e}")
        if VERBOSE:
            traceback.print_exc()
```

**Windows encoding fix:**
```python
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
```
Applied in `test_flows.py` to handle Spanish characters (tildes, ñ) in Windows terminal.

---

*Testing analysis: 2026-03-27*
