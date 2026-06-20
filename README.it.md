# Second Brain (SB)

[![CI](https://github.com/lopax76/second-brain/actions/workflows/ci.yml/badge.svg)](https://github.com/lopax76/second-brain/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/second-brain-graph.svg)](https://pypi.org/project/second-brain-graph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Runtime deps](https://img.shields.io/badge/dipendenze%20runtime-nessuna-success.svg)](pyproject.toml)

**Una mappa viva, sempre fresca e a basso costo di token di ogni progetto** — file, collegamenti,
aree e meccaniche — che un assistente AI può **interrogare** invece di rileggere tutto, e che una
persona può esplorare come una **mappa 2D a community** navigabile.

🇬🇧 [Read in English →](README.md)

> Non "un altro posto dove mettere roba". È il quadro canonico, per-progetto, che resta in sync
> con i tuoi file così non perdi mai il filo: niente pezzi dimenticati, niente "ne avevamo parlato
> tre chat fa", niente documenti stantii.

![Viewer di Second Brain — backbone anonimizzato di un workspace multi-progetto reale](docs/assets/ui-suite.png)

<sub>Il viewer offline su un workspace multi-progetto reale (nomi anonimizzati): una mappa 2D piatta
con i file colorati e raggruppati in community auto-rilevate, e un pannello di dettaglio cliccabile.</sub>

---

## Perché nasce

Un progetto diventa più complesso col tempo. I file derivano, alcuni restano orfani o si rompono
in silenzio, lo schema mentale di "cosa c'è e come si collega" si fa sempre più sfocato, e un
assistente AI **perde il filo tra una chat e l'altra** — così ogni sessione riparte rileggendo e
ri-cercando i file. È lento, incompleto e **brucia token ripetutamente** — e peggiora man mano che
il progetto cresce.

Second Brain costruisce il grafo del progetto e lo mantiene onesto man mano che il progetto
cambia — un **gate** per content-hash segnala esattamente cosa è andato fuori sync, e il rebuild è
un re-walk completo veloce (fuori dal modello, a costo di token quasi nullo). L'assistente lo
**interroga** e ottiene risposte compatte; una persona apre la **mappa 2D a community** e vede
l'intero progetto a colpo d'occhio.

**Non è un sistema RAG**: niente embedding, niente vector store, nessun LLM per costruire il grafo.
Mappa le relazioni *strutturali* tra i file, il che lo rende complementare al RAG e mirato a una
cosa sola: **consapevolezza del contesto a costo di token bassissimo.**

## Cosa lo rende diverso

- **Read-only sui sorgenti** — indicizza, non modifica mai i tuoi file. Lo esegui su qualsiasi cosa
  senza rischio.
- **I file sono la verità** — il grafo è derivato (in `.secondbrain/`) e sempre rigenerabile; i
  contenuti non vengono mai duplicati dentro.
- **Zero dipendenze runtime** — il core gira con la sola libreria standard di Python. Nessun
  conflitto, installazione istantanea, funziona in CI / container / macchine air-gapped.
- **Basso costo di token per design** — le query restituiscono id, tipi, dimensioni e collegamenti,
  mai il contenuto dei file: orientare un assistente costa qualche centinaio di token, non decine di
  migliaia.
- **Gate anti-deriva** — rifiuta di dichiarare il grafo "a posto" finché c'è qualcosa di stantio,
  orfano o rotto.
- **Community e impatto** — rileva da solo i moduli reali del progetto da come i file si collegano
  (non dalle cartelle) e risponde a "cosa si rompe se tocco questo?" (impatto upstream/downstream)
  in una sola chiamata.
- **`GRAPH_REPORT.md` one-pager** — l'artefatto che l'agente legge per primo invece di grep-are:
  god node, community, collegamenti sorprendenti, decisioni e problemi, rigenerato a ogni build.
- **Viewer offline** — una mappa interattiva force-directed (vis-network), colorata per community,
  con ricerca, pannello nodo cliccabile con navigazione dei vicini e legenda community con
  mostra/nascondi. Dati e libreria sono inline in un unico file HTML, quindi funziona completamente
  offline. Il viewer è **adattato da [Graphify](https://github.com/safishamsi/graphify)** (MIT) —
  vedi [Riferimenti & fonti](#riferimenti--fonti).
- **Ranking per importanza (PageRank)** — i "god node" sono ordinati per *importanza strutturale*
  (i file da cui dipendono i file importanti), non per numero di link — implementazione pura-Python,
  deterministica.
- **Recupero mirato al compito (`focus`)** — gli dai un compito e restituisce il *sottografo minimo
  di valore* per quel compito entro un budget di token (PageRank personalizzato seedato sui file che
  matchano), invece dell'intero digest.
- **Query auto-aggiornanti** — ogni query controlla una firma leggera size+mtime e ricostruisce solo
  quando il progetto è davvero cambiato (modifiche non committate incluse): a un assistente non viene
  mai servita una mappa stantia — senza scheduler e senza dipendenze.
- **Call-graph dei simboli opzionale** — `build --symbols` aggiunge nodi funzione/classe e archi
  `calls` intra-file per Python (risoluzione conservativa, nessun arco indovinato); off di default
  per tenere la mappa leggera.
- **Export GraphML** — `export --format graphml` apre il grafo in Gephi / yEd / Cytoscape / networkx.
- **Server MCP opzionale** — espone le stesse query a basso costo agli assistenti MCP, dietro un
  extra opzionale così il core resta senza dipendenze.

## Visto su un progetto reale (anonimizzato)

Misura **read-only** su un progetto maturo multi-repo (identità non rivelata): ~1.684 file di
conoscenza in 17 aree di primo livello, indicizzato in **~1,3 s** (indice `graph.json` = 0,91 MB).

Tre modi di rispondere alle stesse quattro domande sul progetto — *cosa c'è, elenca ogni decisione
registrata, quali file sono troncati/vuoti, i file più collegati* — in tre chat pulite separate:

| Metrica | NIENTE (manuale) | ADESSO (manuale) | CON Second Brain |
|---|---|---|---|
| Tempo | ~8,5 min | ~9 min | **~3–4 min** |
| Token di lavoro | opachi | opachi | **~3–4k, auto-misurabili** |
| **Decisioni trovate** | 112 | 131 | **112 (esatto, ogni volta)** |
| **File troncati** | 3 | 0 (mancati) | **2 (esatto)** |
| File contati | 2.174 | 2.174 | **1.684 (esatto)** |
| Riproducibile / verificabile | no | no | **sì** |

Due cose saltano all'occhio. (1) I due run manuali **non concordano tra loro** — 112 vs 131
decisioni, 3 vs 0 troncati (il secondo li ha mancati del tutto) — quindi il metodo a mano è
non-deterministico e non verificabile: non sai distinguere la risposta giusta (112) da una
sbagliata (131). (2) Second Brain dà la **stessa risposta a ogni run** — 112, il conteggio
corretto — con molti meno token e in meno della metà del tempo. Il vantaggio non è un numero
che a mano non raggiungi, ma uno esatto, riproducibile e interrogabile invece di un terno al lotto.

Solo per *orientare* un assistente sull'intero progetto — cosa che paghi **ogni sessione** —
rileggere i documenti curati sorgente-di-verità costa **~229.000 token**; il digest
`second-brain map` costa **~270 token**: **~800× in meno**, e ~costante mentre il progetto cresce
(l'indice completo si interroga, non entra mai nel contesto).

<p align="center">
  <img src="docs/assets/chart-tokens.png" width="90%" alt="Token per orientarsi (scala log): ~26,7M per leggere tutto, ~4,09M tutti i documenti, ~229.000 i documenti curati di oggi, ~270 il digest di Second Brain">
</p>

<p align="center">
  <img src="docs/assets/chart-accuracy.png" width="48%" alt="Accuratezza: i due run manuali non concordano (112 / 131); Second Brain dà il 112 corretto a ogni run">
  <img src="docs/assets/chart-time.png" width="48%" alt="Tempo per rispondere: ~8,5 / ~9 min manuale vs ~3–4 min con Second Brain; build indice ~1,3 s una-tantum">
</p>

E fa emergere ciò che persino i documenti curati non vedono: file **realmente
troncati/corrotti** (esclusi i falsi positivi UTF-16/encoding), **~45 file vuoti**, **~1.390 file
orfani (~80%)**, **112 decisioni** e **~626 riferimenti incrociati** ora espliciti e interrogabili,
più **13 file già stantii a pochi secondi** dall'indicizzazione (un sistema vivo che riscrive di
continuo) — ed è proprio per questo che la mappa deve aggiornarsi da sola.

<p align="center">
  <img src="docs/assets/chart-memory.png" width="72%" alt="Illustrativo: nel corso di molte chat una mappa tenuta a mano deriva, mentre un grafo interrogabile resta aggiornato">
</p>

<sub>Illustrativo — il problema di continuità che SB elimina: nel corso di molte sessioni una
mappa tenuta a mano deriva (orfani e file stantii si accumulano), mentre un grafo interrogabile
resta sempre aggiornato.</sub>

### La stessa struttura, il layer di codice

Il layer di import-codice di Second Brain rende l'intero workspace come un grafo davvero leggibile:

![Vista Graphify del grafo di codice del workspace](docs/assets/graphify-suite.png)

## Installazione

```bash
pip install second-brain-graph              # da PyPI
pip install "second-brain-graph[mcp]"       # + server MCP opzionale
pip install -e .                            # oppure da un clone
```

[Su PyPI](https://pypi.org/project/second-brain-graph/). Richiede Python 3.10+. Dipendenze
runtime: **nessuna** (solo libreria standard). Il pacchetto installa il comando `second-brain`
e il modulo di import `second_brain`.

## Comandi

Ogni comando accetta un path di progetto opzionale (default `.`). **Le query si auto-aggiornano** —
fanno il build al primo uso e ricostruiscono solo quando il progetto è davvero cambiato — così un
assistente non risponde mai da una mappa stantia (vedi *Sempre fresco* sotto).

**Build & freschezza**
```bash
second-brain build .              # indicizza il progetto -> .secondbrain/ (grafo + GRAPH_REPORT.md)
second-brain build . --symbols    # indicizza anche il layer simboli Python (funzioni/classi + calls)
second-brain gate .               # check anti-deriva: ref rotte, file stantii, orfani (exit≠0 se derivato)
```

**Orientarsi — leggi questi per primi**
```bash
second-brain report .   # GRAPH_REPORT.md: god node (PageRank), community, churn, decisioni, problemi
second-brain communities .   # i moduli reali del progetto (cluster da import+riferimenti) + ponti tra moduli
second-brain map .      # digest compatto: aree, dimensioni, file più connessi
second-brain assess .   # prima/dopo: problemi + risparmio token
second-brain stats .    # conteggi rapidi per tipo nodo/arco
```

**Interrogare**
```bash
second-brain find util .                            # nodi il cui nome/path contiene "util"
second-brain neighbors second_brain/model.py .      # un nodo e le sue connessioni
second-brain impact second_brain/model.py .         # raggio d'impatto: cosa si rompe / da cosa dipende
second-brain impact second_brain/model.py . --up    # solo chi dipende da esso (eseguilo prima di modificare!)
second-brain impact --diff . --up                    # raggio d'impatto delle tue modifiche NON committate (git diff)
second-brain why second_brain/cli.py second_brain/model.py .   # percorso minimo: come sono collegati due nodi?
second-brain focus "budget token nel report" .      # mirato al compito: il sottografo minimo che conta
second-brain focus "flusso di auth" . --budget 4000 #   ...entro ~4000 token (default 2000)
second-brain symbols second_brain/model.py .        # firme funzioni/classi di un file Python
```

**Vedere & esportare**
```bash
second-brain view .             # viewer mappa 2D a community offline -> .secondbrain/view.html
second-brain view ./src/api     # drill-down su un'area in pieno dettaglio (la vista d'insieme resta leggera)
second-brain export . --format graphml --out graph.graphml   # GraphML per Gephi/yEd/Cytoscape/networkx
```

**Integrazione agente & freschezza automatica**
```bash
second-brain agent install .    # aggiunge la direttiva SB a CLAUDE.md/AGENTS.md + un hook Claude Code
second-brain hook install .     # git post-commit/post-checkout: ricostruisce il grafo a ogni commit
```

**Drill-down** puntando qualsiasi comando su una sottocartella — `second-brain map ./src/api`
lavora solo su quell'area; la vista d'insieme resta leggera grazie alla modalità *backbone* (aree +
nucleo connesso per conoscenza; i file-dati isolati sono riassunti sul nodo-area).

### Personalizzazione per-progetto (`.secondbrain.json`)

Un `.secondbrain.json` nella radice del progetto estende la tassonomia di classificazione o
fissa il tipo di un file quando l'euristica sbaglia (fail-safe: i nomi-tipo sconosciuti sono
ignorati, e senza il file il comportamento è byte-identico):

```json
{ "classify": { "type_overrides": { "data/seed.json": "data", "notes/SPEC.md": "design" } } }
```

### Sempre fresco (auto-refresh)

Le query (`map` / `find` / `neighbors` / `impact` / `focus` / `report`, e i tool MCP) controllano
una **firma leggera size+mtime** prima di rispondere e **ricostruiscono solo se il progetto è
cambiato** — modifiche **non ancora committate** incluse. Così la mappa è aggiornata ogni volta che
l'assistente la usa, **senza scheduler e senza dipendenze**. Il primo uso di un progetto fa il build
da solo. Per servire il grafo salvato così com'è (saltando il controllo): `SECOND_BRAIN_AUTO_REFRESH=0`.
Su un progetto a grafo unico enorme puoi limitare il controllo con `SECOND_BRAIN_REFRESH_TTL=<secondi>`.
Il controllo solo-`stat` ha un unico punto cieco — una modifica a parità di dimensione entro lo stesso
tick del filesystem dell'ultimo build — che `second-brain gate` (content-hash) cattura con precisione.

| Interruttore | Effetto |
|--------------|---------|
| `SECOND_BRAIN_AUTO_REFRESH=0` | disattiva l'auto-refresh (serve il grafo salvato, più veloce, può essere stantio) |
| `SECOND_BRAIN_REFRESH_TTL=<sec>` | limita il controllo di freschezza a una volta per finestra (grafi monorepo enormi) |
| `build --symbols` | include il layer di funzioni/classi + chiamate (off di default per tenere la mappa leggera) |
| `focus … --budget N` | dimensiona il contesto-compito restituito da `focus` (default 2000 token) |
| `impact … --up` / `--down` / `--depth N` | restringe/limita la camminata del raggio d'impatto |
| `view --backbone` | forza il rendering backbone a qualsiasi dimensione (automatico oltre ~8000 nodi) |

### Aprire il grafo

1. **Genera il viewer:** `second-brain view .`
2. **Aprilo:** doppio clic sul file creato — `.secondbrain/view.html` — in un browser qualsiasi.
   Niente server, niente installazione: i dati e la libreria di rendering sono inline nella singola
   pagina, quindi funziona completamente offline.
3. **Esplora:** il grafo è disposto come una **mappa 2D** piatta, con i file colorati e raggruppati
   in **community** (rilevate da come si collegano). Rotella per lo zoom, trascina col tasto destro
   per spostarti, doppio clic su un nodo per i dettagli (incluso il suo raggio d'impatto). Dal
   pannello a sinistra puoi cercare, cambiare raggruppamento (community / area / cartella / tipo),
   isolare una singola community o mostrare solo gli orfani.

## Layer di query (per gli assistenti AI)

`second-brain map`, `find`, `neighbors`, `impact`, `why`, `focus` e `report` restituiscono risposte
compatte e budgettate (id, tipi, dimensioni, connessioni — mai il contenuto dei file). Un **server
MCP** opzionale espone le stesse query agli assistenti compatibili MCP:

```bash
pip install "second-brain-graph[mcp]"
second-brain-mcp .   # project_map / find / neighbors / subgraph / impact / impact_diff / why / communities / focus / report / health
```

Vedi [`docs/mcp.md`](docs/mcp.md) per i tool e le forme dei dati.

## Come funziona

1. **Index** — percorre il progetto, classifica ogni file in un nodo tipizzato ed estrae gli archi:
   import Python (via `ast`), import JS/TS, riferimenti di documentazione (link markdown,
   `[[wikilink]]` e **menzioni di path in prosa** — il pezzo che gli strumenti standard mancano) e
   appartenenza ad area. Vengono aggiunti anche i nodi operativi (decisioni trovate nei documenti,
   sessioni dai commit git).
2. **Stay fresh** — il diffing per content-hash dice al **gate** esattamente cosa è cambiato
   dall'ultimo build; il rebuild è un re-walk completo veloce (fuori dal modello). Le query inoltre
   si **auto-aggiornano**: ricostruiscono da sole quando il progetto è cambiato (modifiche non
   committate incluse), così un assistente non lavora mai su una mappa stantia.
3. **Query / view** — una persona ottiene la mappa 2D a community; un assistente interroga il layer a
   basso costo di token, e chiede `focus "<compito>"` per la sola fetta che serve al lavoro in corso.

**Sui falsi positivi:** le menzioni di path in prosa sono intrinsecamente rumorose. Second Brain
le gestisce in modo asimmetrico — link markdown e wikilink sono intenzionali (uno non risolto è
segnalato come *rotto*), ma una menzione in prosa è usata **solo se risolve** a un file reale;
altrimenti viene scartata come rumore e non crea mai un riferimento rotto. Il parsing profondo degli
import oggi è Python e JS/TS; gli altri linguaggi contribuiscono via link di documentazione.

La tassonomia completa nodi/archi, lo schema di `graph.json` e le regole di classificazione sono
documentati in [`docs/graph-format.md`](docs/graph-format.md).

## Prova tu il prima/dopo

Esegui questi in **chat pulite separate** (read-only), poi confronta le risposte e il costo
token/tempo. Sostituisci `/path/al/progetto` con un progetto reale.

**ADESSO (il tuo metodo attuale):**

```
SOLO LETTURA: non modificare, creare, cancellare o spostare alcun file. Sul progetto in
/path/al/progetto, lavora col tuo METODO NORMALE (documenti di riferimento, memoria, gli
strumenti che usi di solito). Dammi un quadro COMPLETO e ACCURATO rispondendo a 4 domande:
1) quanti file (esclusi immagini, venv, cache, .git) e ripartizione per tipo;
2) elenca TUTTE le decisioni registrate nei documenti (D-XXX, ADR-N, RFC-N);
3) quali file sono troncati/corrotti (null-byte) o vuoti (zero-byte);
4) i 10 file più collegati. Quando hai finito, dimmi tempo e token consumati.
```

**CON Second Brain** (indice già costruito — interrogalo, non rileggere i file):

```
SOLO LETTURA. L'indice di Second Brain è già costruito — va solo interrogato. Usa SOLO:
  python -m second_brain map   "/path/al/progetto"
  python -m second_brain stats "/path/al/progetto"
  python -m second_brain find <testo> "/path/al/progetto"
e leggi /path/al/progetto/.secondbrain/assessment.md. Rispondi alle stesse 4 domande, poi
dimmi tempo e token consumati.
```

## Architettura & moduli

Read-only sui sorgenti, zero dipendenze runtime, deterministico. Tutto vive nel package
`second_brain/` — ogni modulo pubblico e cosa fa:

| Modulo | Responsabilità |
|--------|----------------|
| [`cli.py`](second_brain/cli.py) | Interfaccia a riga di comando — ogni comando `second-brain`. |
| [`mcp_server.py`](second_brain/mcp_server.py) | Server MCP opzionale: i tool di query a basso costo su stdio (extra `[mcp]`). |
| [`model.py`](second_brain/model.py) | Modello dati del grafo: nodi/archi tipizzati, colori, contenitore JSON + indice di adiacenza. |
| [`indexer.py`](second_brain/indexer.py) | Costruisce il grafo: nodi-file, aree, archi import/riferimento, layer simboli opzionale. |
| [`classify.py`](second_brain/classify.py) | Classifica ogni file in un nodo tipizzato (euristica, configurabile per progetto). |
| [`config.py`](second_brain/config.py) | Config per-progetto `.secondbrain.json` (estende/sostituisce la tassonomia + `type_overrides` per-file). |
| [`ignore.py`](second_brain/ignore.py) | Pattern `.secondbrainignore` + ignore di default sensati. |
| [`references.py`](second_brain/references.py) | Estrae i riferimenti dai documenti: link markdown, `[[wikilink]]`, path-in-prosa. |
| [`pycode.py`](second_brain/pycode.py) | Archi import: Python via `ast`, JS/TS best-effort (commenti rimossi). |
| [`pysymbols.py`](second_brain/pysymbols.py) | Call-graph Python intra-file (funzioni/classi + `calls` conservativo). |
| [`symbols.py`](second_brain/symbols.py) | Firme funzioni/classi di un singolo file Python (comando `symbols`). |
| [`freshness.py`](second_brain/freshness.py) | Manifest content-hash, firma leggera e query auto-aggiornanti. |
| [`gate.py`](second_brain/gate.py) | Il gate anti-deriva: ref rotte / file stantii / orfani. |
| [`store.py`](second_brain/store.py) | Persiste lo store derivato in `.secondbrain/` (graph, manifest, signature, mode). |
| [`query.py`](second_brain/query.py) | Layer di query a basso costo: `map` / `find` / `neighbors` / `subgraph` / `impact` / `focus`. |
| [`bm25.py`](second_brain/bm25.py) | Rilevanza lessicale Okapi BM25 (stdlib) — il segnale task-file che innesca `focus`. |
| [`budget.py`](second_brain/budget.py) | Stima costo-token + fit a budget (stdlib) — l'unico posto dove `focus` / `impact` contano i token. |
| [`rank.py`](second_brain/rank.py) | PageRank per importanza (globale + personalizzato) — motore dietro god-node e `focus`. |
| [`communities.py`](second_brain/communities.py) | Community detection (label propagation deterministica) + archi cross-community sorprendenti. |
| [`operational.py`](second_brain/operational.py) | Nodi operativi: decisioni dai documenti, sessioni dai commit git. |
| [`report.py`](second_brain/report.py) | Genera `GRAPH_REPORT.md` (god node, community, churn, decisioni, problemi). |
| [`assess.py`](second_brain/assess.py) | Valutazione prima/dopo one-shot: problemi nascosti + risparmio token. |
| [`viewer.py`](second_brain/viewer.py) | Viewer mappa 2D a community offline (vis-network, adattato da Graphify). |
| [`export.py`](second_brain/export.py) | Esporta il grafo in GraphML. |
| [`agent_integration.py`](second_brain/agent_integration.py) | Integra SB negli agent AI: direttiva CLAUDE.md/AGENTS.md, hook Claude Code, hook git. |

Doc di riferimento: lo [schema & tassonomia di `graph.json`](docs/graph-format.md) e i
[tool MCP](docs/mcp.md).

## Stato & roadmap

Beta — **v0.8.0**. Funzionante oggi: il grafo tipizzato; il **gate** anti-deriva; le **query
auto-aggiornanti** (ricostruiscono solo quando il progetto è cambiato, senza scheduler); il viewer
**mappa 2D a community** offline; il layer di query a basso costo (`map` / `find` / `neighbors` /
`subgraph` / `impact` — **più `--diff` per il raggio d'impatto delle tue modifiche non committate** —
/ **`why`** (percorso minimo tra due nodi) / **`focus`** / **`communities`** — i moduli reali del progetto + ponti cross-modulo); il ranking per importanza **PageRank**; il
**rilevamento delle community**; il **`GRAPH_REPORT.md`** one-pager; i nodi operativi
(decisioni/sessioni); il **call-graph dei simboli Python** opzionale (`build --symbols`); l'**export
GraphML**; la tassonomia configurabile `.secondbrain.json` **con `type_overrides` per-file**; l'**integrazione con gli agent**
(`agent install` + git `hook install`); e il **server MCP** opzionale. Prossimi passi: un build
davvero incrementale per grafi molto grandi, risoluzione dei riferimenti più ricca, layer di simboli
per altri linguaggi e un layer semantico locale opzionale.

## Sviluppo

```bash
pip install -e ".[dev,mcp]"
ruff check second_brain tests
pytest -q
```

I contributi sono benvenuti — vedi [CONTRIBUTING.md](CONTRIBUTING.md) e i
[principi di design](CONTRIBUTING.md#design-principles-please-keep-these-intact) (read-only,
zero-deps, basso costo di token, deterministico). Segnalazioni di sicurezza: [SECURITY.md](SECURITY.md).

## Riferimenti & fonti

**Basato su / adattato da**

- **[Graphify](https://github.com/safishamsi/graphify)** di Safi Shamsi (MIT) — il viewer
  interattivo è modellato sul viewer di Graphify; con gratitudine.
- **[vis-network](https://github.com/visjs/vis-network)** (Apache-2.0 OR MIT) — la libreria di
  rendering, inclusa offline. Testi di licenza completi in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

**Concetti & specifiche**

- **BM25 (rilevanza lessicale)** — S. Robertson & H. Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond* (2009); vedi [Okapi BM25](https://en.wikipedia.org/wiki/Okapi_BM25). Ordina i file-ancora del task per `focus`.
- **Design della repo map** — la mappa ranked-PageRank, budgeted e con firme è ispirata dalla [repo map di aider](https://aider.chat/docs/repomap.html) e dal progetto gemello [veridge](https://github.com/galimar/veridge).
- **PageRank** — S. Brin & L. Page, *The Anatomy of a Large-Scale Hypertextual Web Search Engine*
  (1998); vedi [PageRank](https://it.wikipedia.org/wiki/PageRank). Usato per il ranking d'importanza
  e per `focus` mirato al compito (PageRank personalizzato).
- **Label propagation** — Raghavan, Albert & Kumara, *Near linear time algorithm to detect community
  structures* (2007); vedi [Label propagation](https://en.wikipedia.org/wiki/Label_propagation_algorithm).
  Usato per il rilevamento deterministico delle community.
- **Model Context Protocol** — [modelcontextprotocol.io](https://modelcontextprotocol.io); il server
  MCP lo parla.
- **GraphML** — [graphml.graphdrawing.org](http://graphml.graphdrawing.org); il formato di `export`.
- **`ast` di Python** — [docs.python.org/3/library/ast](https://docs.python.org/3/library/ast.html);
  parsing preciso di import e simboli Python.
- **BLAKE2** — [blake2.net](https://www.blake2.net); l'hash di contenuto (stdlib) usato per la freschezza.
- **Keep a Changelog** — [keepachangelog.com](https://keepachangelog.com) ·
  **Semantic Versioning** — [semver.org](https://semver.org).

**Documentazione del progetto**

- [`docs/graph-format.md`](docs/graph-format.md) — store su disc