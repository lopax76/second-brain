# Esperimento NIENTE | ADESSO | DOPO — Suite Maestro COMPLETA (2026-06-14)

> Tre chat pulite separate, **stesse 4 domande**, **stesso perimetro**, condizioni isolate.
> Perimetro scelto: **suite completa CON le cache dati** (i 124k parquet contano come "dati").
> Esclusi: Assistente-AI, Second Brain, Albedo, ROMA-PoC, PowerShell (non-suite).

## Setup già fatto (da me)
- Indice Second Brain **già costruito** su `C:\Users\robys\Documents`, ritagliato alla sola
  suite tramite `C:\Users\robys\Documents\.secondbrainignore`. Store: `C:\Users\robys\Documents\.secondbrain\`
  (+ `assessment.md`). La chat "DOPO" deve solo **interrogarlo**.
- Invocazione corretta: **`py -m second_brain ...`** (NON `python -m secondbrain`, nome vecchio).

## Come si fa
Apri **3 chat nuove**, una alla volta. Incolla un prompt per chat. A fine di ognuna annota
**token di contesto** (status line / usage monitor) e **tempo**. Poi confronti le 3 risposte
con la "Verità di riferimento" in fondo e completiamo la tabella.

> Ordine consigliato: prima **ADESSO** (è il confronto che conta), poi **NIENTE**, poi **DOPO**.

---

## PROMPT 1 — "ADESSO" (metodo attuale)

```
ESPERIMENTO CONTROLLATO, SOLA LETTURA. Non modificare/creare/cancellare/spostare ALCUN file;
non eseguire comandi o script che SCRIVONO; NON avviare il protocollo di CHIUSURA/salvataggio.

CONDIZIONE "ADESSO": usa il tuo METODO NORMALE di lavoro su questa suite — lascia pure partire
il normale protocollo di apertura (documenti di riferimento PROGETTO.md / INDEX / DATA-MAP /
ARCHITETTURA-SUITE, memoria, Graphify, gli strumenti che già usi). NON usare Second Brain.

PROGETTO = la SUITE MAESTRO, che vive sotto C:\Users\robys\Documents in queste cartelle:
  Maestro (che contiene SEA), Syntrix, MasterAI, CryptoBOT  + i file sciolti nella radice
  Documents (es. PROGETTO.md). Considera SOLO queste. NON contare Assistente-AI, Second Brain,
  Albedo, ROMA-PoC, PowerShell.

Dammi un quadro COMPLETO e ACCURATO rispondendo a queste 4 domande:
1) quanti file TOTALI (esclusi SOLO immagini, ambienti virtuali .venv, .git, __pycache__; i file
   di DATI come .parquet/.db VANNO contati) con ripartizione per tipo: programma, struttura,
   config/stato, dati, rapporti, design — più quante decisioni;
2) elenco/numero di TUTTE le decisioni registrate nei documenti (token tipo D-XXX, ADR-N, RFC-N);
3) quali file sono TRONCATI/CORROTTI (byte null interni) o VUOTI (zero byte);
4) i 10 file PIÙ COLLEGATI (più referenziati/menzionati o importati dagli altri).
Quando hai finito: dimmi tempo impiegato e token di contesto consumati.
```

---

## PROMPT 2 — "NIENTE" (nessuna struttura)

```
ESPERIMENTO CONTROLLATO, SOLA LETTURA. Non modificare/creare/cancellare/spostare ALCUN file;
non eseguire comandi o script che SCRIVONO; NON avviare ALCUN protocollo di apertura o chiusura.

CONDIZIONE "NIENTE": SALTA qualunque protocollo di apertura e NON leggere documenti-riassunto,
indici, grafi o memoria pre-costruiti — niente PROGETTO.md, niente INDEX/DATA-MAP/ARCHITETTURA,
niente memoria, niente Graphify, niente Second Brain. Ricostruisci tutto esplorando DIRETTAMENTE
i file grezzi.

PROGETTO = la SUITE MAESTRO, sotto C:\Users\robys\Documents in: Maestro (contiene SEA), Syntrix,
MasterAI, CryptoBOT + i file sciolti nella radice Documents. Considera SOLO queste. NON contare
Assistente-AI, Second Brain, Albedo, ROMA-PoC, PowerShell.

Rispondi alle stesse 4 domande:
1) quanti file TOTALI (esclusi SOLO immagini, .venv, .git, __pycache__; i file di DATI
   .parquet/.db VANNO contati) con ripartizione per tipo: programma, struttura, config/stato,
   dati, rapporti, design — più quante decisioni;
2) elenco/numero di TUTTE le decisioni registrate (D-XXX, ADR-N, RFC-N);
3) quali file sono TRONCATI/CORROTTI (byte null) o VUOTI (zero byte);
4) i 10 file PIÙ COLLEGATI.
Quando hai finito: dimmi tempo impiegato e token di contesto consumati.
```

---

## PROMPT 3 — "DOPO" (Second Brain)

```
ESPERIMENTO CONTROLLATO, SOLA LETTURA. Non modificare/creare/cancellare/spostare ALCUN file del
progetto; NON ricostruire l'indice; NON avviare alcun protocollo di apertura/chiusura.

CONDIZIONE "DOPO": è già attivo "Second Brain", un indice della suite GIÀ COSTRUITO che si
interroga da riga di comando senza rileggere i file. L'indice è già limitato alla suite Maestro.
USA SOLO questi comandi (NON leggere/esplorare i file del progetto, NON leggere PROGETTO.md /
INDEX / memoria):
  py -m second_brain map    "C:\Users\robys\Documents"
  py -m second_brain stats  "C:\Users\robys\Documents"
  py -m second_brain find <testo>      "C:\Users\robys\Documents"
  py -m second_brain neighbors <id-file> "C:\Users\robys\Documents"
e leggi il rapporto già generato: C:\Users\robys\Documents\.secondbrain\assessment.md

Rispondi alle stesse 4 domande:
1) quanti file e ripartizione per tipo (+ quante decisioni);
2) elenco/numero di TUTTE le decisioni registrate;
3) quali file sono TRONCATI/CORROTTI o VUOTI;
4) i file PIÙ COLLEGATI.
Quando hai finito: dimmi tempo impiegato e token di contesto consumati.
```

---

## Verità di riferimento (output Second Brain, esatto e riproducibile)

Perimetro suite (con cache), `C:\Users\robys\Documents` ritagliato via `.secondbrainignore`:

- **128.667 file**, **5 aree**, 130.925 collegamenti, **9,6 GB**.
  - CryptoBOT 1.036 (6,8 GB) · Syntrix 125.537 (2,0 GB) · MasterAI 378 (703 MB) · Maestro 1.689 (119 MB, incl. SEA) · (root) 27.
- **Ripartizione per tipo**: dati **124.666** · config 1.769 · programma 1.719 · struttura 233 · rapporti 167 · design 68.
- **Decisioni: 305** (D-SYN / D-SEA / D-CB / D-MAE / D-PD / D-PA / D-PB / ADR ecc. sui 4 repo).
- **Igiene**: **12 troncati**, **72 vuoti**, **3 riferimenti rotti**, ~127.836 orfani (~99%, perché i 124k file-dati non hanno collegamenti di conoscenza).
- **10 più collegati**: PROGETTO.md (366) · PROGETTO-storia.md (87) · Maestro/docs/architettura-suite/ARCHITETTURA-SUITE-completa.md (41) · Maestro/docs/llm-touchpoints-audit_2026-06-10.md (37) · Syntrix/.../esperimento_1/live_runner.py (27) · Syntrix/.../esperimento_2/paper_runner.py (27) · Maestro/ui-v2/ACTIVATION.md (22) · Maestro/SEA/tests/unit/ui/_synthetic.py (19) · [le restanti nel digest `map`].
- **Costo per orientarsi**: leggere tutto ≈ 2,57 **miliardi** di token (9,6 GB); solo i documenti ≈ **18,8 M** token; con SB (`map`) **≈ 220 token**. Build una-tantum ≈ **12 s**.

> Nota: i numeri sopra sono il metro oggettivo. Confrontiamo quanto NIENTE e ADESSO ci si
> avvicinano (e con quanto tempo/token), e se concordano tra loro.

## Pulizia a fine esperimento
Quando abbiamo finito, da rimuovere (scaffolding SB, non sorgenti):
`Remove-Item "C:\Users\robys\Documents\.secondbrain" -Recurse -Force` e
`Remove-Item "C:\Users\robys\Documents\.secondbrainignore" -Force`.
