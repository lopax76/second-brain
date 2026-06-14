# Second Brain v0.2 — disegno (tassonomia configurabile + symbol-layer)

> Stato: DISEGNO, da ratificare con Roberto prima di costruire. Interno (gitignored).
> Origine: rilievi convergenti (valutazione esterna + Gemini + galimar #1, già chiusa in 0.1.2).
> Vincoli non negoziabili di SB: **read-only sui sorgenti**, **zero dipendenze runtime nel core**,
> **deterministico**, **a basso costo di token**, compatibile **Python 3.10–3.14**.

## Obiettivo
Due pilastri, entrambi a basso costo, che alzano l'adozione "pubblica" senza tradire la filosofia:

1. **Tassonomia di classificazione CONFIGURABILE** — oggi `classify.py` ha parole-chiave EN+IT
   hardcoded (`disegno/design`, `rapporto/report`, `collaudo/diagnosi/strumentazione`…) e
   `_STRUCTURE_NAMES` con nomi personali (`progetto.md`, `data-map.md`). Per un pubblico ampio
   vanno (a) de-personalizzati i default e (b) resi sovrascrivibili per-progetto.
2. **Symbol-layer** — indicizzare nomi + firme di funzioni/classi via `ast` (stdlib, zero-dep).
   Risponde al rilievo "se la mappa omette le firme, l'AI può allucinare" senza gonfiare il grafo.

---

## Pilastro A — Tassonomia configurabile

### D-SB-11 — Dove/come vive la config
- **A (consigliata)** — file `.secondbrain.json` alla RADICE del progetto (JSON = stdlib ovunque,
  3.10-compatibile, stesso pattern utente di `.secondbrainignore`, fuori dallo store rigenerato).
- B — sezione `[tool.second-brain]` in `pyproject.toml` (TOML: `tomllib` è 3.11+, servirebbe
  fallback per 3.10; e non tutti i progetti hanno pyproject).

### D-SB-12 — Semantica di merge
- **A (consigliata)** — le regole utente ESTENDONO i default (aggiungi le tue parole-chiave,
  i default EN/IT restano). Minima sorpresa.
- B — la config SOSTITUISCE i default (controllo totale, ma devi ridefinire tutto).
- (Possibile supportare entrambe con un campo `"mode": "extend" | "replace"`, default `extend`.)

### D-SB-13 — De-personalizzare i default
Togliere `progetto.md`/`data-map.md` dai `_STRUCTURE_NAMES` di default (restano generici:
`readme`/`changelog`/`license`/`index`/`contributing`). Roberto li riaggiunge nel SUO
`.secondbrain.json`. **Consigliata**: i default del tool devono essere neutri.

### Forma proposta di `.secondbrain.json`
```json
{
  "classify": {
    "mode": "extend",
    "structure_names": ["progetto.md", "data-map.md"],
    "keywords": {
      "design":   ["disegno", "blueprint"],
      "report":   ["collaudo", "diagnosi", "strumentazione"],
      "decision_id_prefixes": ["D", "ADR", "RFC"]
    }
  }
}
```
- `decision_id_prefixes` rende configurabile anche la **regex delle decisioni** di `operational.py`
  (oggi `D-[A-Z]{1,8}-\d+|ADR-\d+|RFC-\d+`) per chi usa altri schemi (es. `DEC-`, `Y-`).
- Default invariati se il file manca → **byte-identico** all'attuale (back-compat totale).

---

## Pilastro B — Symbol-layer

### D-SB-14 — Come si espone (lean vs grafo)
- **A (consigliata)** — comando on-demand `second-brain symbols <file>`: estrae le firme dal vivo
  via `ast`, NON le mette nel grafo. Resta lean (zero bloat sui ~1.700 .py della suite), token-cheap
  (solo il file chiesto), fedele alla filosofia "interroga, non versare tutto".
- B — simboli come NODI del grafo (mappa completa nel 3D, ma +migliaia di nodi = grafo gonfio).
- (Ibrido possibile: A di default + flag `build --symbols` per chi vuole B.)

### D-SB-15 — Linguaggi
Solo **Python** per 0.2 (via `ast`, stdlib → zero-dep preservato). JS/TS dopo (richiedono un parser
non-stdlib → romperebbe lo zero-dep; rinviati). **Consigliata.**

### Output proposto di `symbols <file>`
```
src/app.py
  def main(argv: list[str] | None = None) -> int   [L12]
  class Server(Base)                                [L40]
    def start(self, port: int = 8000) -> None       [L48]
```
Estrazione: `ast.parse` → `FunctionDef`/`AsyncFunctionDef`/`ClassDef`; firma da `ast.arguments` +
annotazioni + return; classi con basi. Costo zero, deterministico, ordinato.

---

## Fuori scope 0.2 (annotati)
- Query lineari O(n): irrilevanti alla scala attuale (128k file in pochi secondi) → eventuale
  indice quando/se servirà su grafi enormi.
- JS/TS symbol-layer (zero-dep). UI 3D dei simboli.

## Piano di lavoro (a ratifica fatta)
1. A — config loader `.secondbrain.json` + merge nei moduli `classify`/`operational` (TDD, default
   byte-identico, +test su override e su file assente). De-personalizzare i default.
2. B — modulo `symbols.py` (ast) + comando CLI `symbols` (TDD su fixture).
3. README/docs: documentare `.secondbrain.json` + `symbols`; bump 0.2.0 + CHANGELOG.
4. Cross-check avversariale prima del rilascio; build+twine; push+upload.

> Tutto retro-compatibile: senza `.secondbrain.json` e senza usare `symbols`, 0.2 = 0.1.2.
