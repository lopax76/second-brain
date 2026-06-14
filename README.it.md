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

![Viewer 3D di Second Brain — backbone anonimizzato di un workspace multi-progetto reale](docs/assets/ui-suite.png)

<sub>Il viewer 3D offline su un workspace multi-progetto reale (nomi anonimizzati): nodi colorati
per tipo, qui raggruppati per tipo, con pannello di dettaglio cliccabile.</sub>

---

## Perché nasce

Un progetto diventa più complesso col tempo. I file derivano, alcuni restano orfani o si rompono
in silenzio, lo schema mentale di "cosa c'è e come si collega" si fa sempre più sfocato, e un
assistente AI **perde il filo tra una chat e l'altra** — così ogni sessione riparte rileggendo e
ri-cercando i file. È lento, incompleto e **brucia token ripetutamente** — e peggiora man mano che
il progetto cresce.

Second Brain costruisce il grafo del progetto **una volta sola** e lo mantiene fresco in modo
incrementale (fuori dal modello, a costo di token quasi nullo). L'assistente lo **interroga** e
ottiene risposte compatte; una persona apre la **vista 3D** e vede l'intero progetto a colpo
d'occhio.

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
- **Viewer offline** — una mappa 2D piatta, colorata e raggruppata per community; i dati sono inline
  e la libreria di rendering è bundlata accanto alla pagina, quindi funziona completamente offline,
  niente CDN, niente che un blocco-script possa rompere.
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

## Avvio rapido

```bash
second-brain build  .          # indicizza un progetto -> .secondbrain/graph.json
second-brain gate   .          # check anti-deriva: ref rotte, file stantii, orfani
second-brain view   .          # scrive il viewer 3D offline -> .secondbrain/view.html
second-brain stats  .          # conteggi rapidi per tipo nodo/arco
second-brain map    .          # digest compatto: aree, dimensioni, file più connessi
second-brain find   util .     # trova nodi per nome o path
second-brain neighbors second_brain/model.py .   # un nodo e le sue connessioni
second-brain impact second_brain/model.py .      # raggio d'impatto: cosa si rompe / da cosa dipende
second-brain report .          # scrive GRAPH_REPORT.md: god node, community, decisioni, problemi
second-brain assess .          # report prima/dopo: problemi + risparmio token
second-brain symbols second_brain/model.py       # firme funzioni/classi di un file Python
second-brain agent install .   # aggiunge la direttiva SB a CLAUDE.md/AGENTS.md + un hook Claude Code
second-brain hook install .    # git post-commit/post-checkout: tiene il grafo fresco da solo
```

**Drill-down** puntando lo strumento su una sottocartella — `second-brain view ./src/api`
renderizza solo quell'area in pieno dettaglio, mentre la vista d'insieme resta leggera grazie alla
modalità *backbone* (aree + nucleo connesso per conoscenza; i file-dati isolati sono riassunti sul
nodo-area).

### Aprire il grafo 3D

1. **Genera il viewer:** `second-brain view .`
2. **Aprilo:** doppio clic sul file creato — `.secondbrain/view.html` — in un browser qualsiasi.
   Niente server, niente installazione: i dati sono inline e la libreria 3D è inclusa accanto alla
   pagina, quindi funziona completamente offline.
3. **Esplora:** il grafo è disposto come una **mappa 2D** piatta, con i file colorati e raggruppati
   in **community** (rilevate da come si collegano). Rotella per lo zoom, trascina col tasto destro
   per spostarti, doppio clic su un nodo per i dettagli (incluso il suo raggio d'impatto). Dal
   pannello a sinistra puoi cercare, cambiare raggruppamento (community / area / cartella / tipo),
   isolare una singola community o mostrare solo gli orfani.

## Layer di query (per gli assistenti AI)

`second-brain map`, `find`, `neighbors`, `impact` e `report` restituiscono risposte compatte e
budgettate (id, tipi, dimensioni, connessioni — mai il contenuto dei file). Un **server MCP**
opzionale espone le stesse query agli assistenti compatibili MCP:

```bash
pip install "second-brain-graph[mcp]"
second-brain-mcp .      # serve map / find / neighbors / subgraph / impact / report / health
```

Vedi [`docs/mcp.md`](docs/mcp.md) per i tool e le forme dei dati.

## Come funziona

1. **Index** — percorre il progetto, classifica ogni file in un nodo tipizzato ed estrae gli archi:
   import Python (via `ast`), import JS/TS, riferimenti di documentazione (link markdown,
   `[[wikilink]]` e **menzioni di path in prosa** — il pezzo che gli strumenti standard mancano) e
   appartenenza ad area. Vengono aggiunti anche i nodi operativi (decisioni trovate nei documenti,
   sessioni dai commit git).
2. **Stay fresh** — il diffing per content-hash ricostruisce solo ciò che è cambiato (fuori dal
   modello).
3. **Query / view** — una persona ottiene la vista 3D; un assistente interroga il layer a basso
   costo di token.

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

## Stato & roadmap

Alpha. Funzionante oggi: grafo tipizzato, gate anti-deriva, viewer **mappa 2D a community**
offline, layer di query a basso costo (`map`/`find`/`neighbors`/`subgraph`), nodi operativi
(decisioni/sessioni) e server MCP opzionale. **v0.3** aggiunge il **rilevamento delle community**
(i moduli reali scoperti da come i file si collegano), le **query d'impatto** (`impact` — cosa si
rompe se tocchi un nodo), il **`GRAPH_REPORT.md` one-pager** (`report`, rigenerato a ogni build) e
l'**integrazione con gli agent** (`agent install` scrive una direttiva in CLAUDE.md/AGENTS.md + un
hook `PreToolUse` di Claude Code; `hook install` aggiunge hook git che ricostruiscono il grafo
gratis). Porta avanti anche la **tassonomia configurabile `.secondbrain.json`** e il **layer di
simboli Python** (`symbols`) di v0.2. Prossimi passi: risoluzione dei riferimenti più ricca e layer
di simboli per altri linguaggi.

## Sviluppo

```bash
pip install -e ".[dev,mcp]"
ruff check second_brain tests
pytest -q
```

I contributi sono benvenuti — vedi [CONTRIBUTING.md](CONTRIBUTING.md) e i
[principi di design](CONTRIBUTING.md#design-principles-please-keep-these-intact) (read-only,
zero-deps, basso costo di token, deterministico). Segnalazioni di sicurezza: [SECURITY.md](SECURITY.md).

## Licenza

[MIT](LICENSE).
