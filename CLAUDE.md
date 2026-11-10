# Dirette live di Zona Wrestling — istruzioni operative per Claude

Questo repository è il ponte tra te (Claude) e zonawrestling.net. Tu scrivi file JSON nella coda;
GitHub Actions li invia all'API REST di WordPress (plugin "WP Wrestling Live Pro") e scrive l'esito in `results/`.
Tutto passa da `scripts/zw.py`: non chiamare mai il sito o le fonti in altro modo.

Lavori di notte, senza nessuno che controlla: Giuseppe legge solo il risultato finito.
Ogni blocco va online subito e porta la sua firma. La precisione conta più della velocità.

## 1. Preparazione (una volta all'inizio della sessione)

1. Leggi `config/shows.json` e individua lo show di stanotte (te lo dice il prompt: es. `raw`).
2. La **data dello show è quella USA** (la sera prima della notte italiana): Raw del lunedì in onda alle 2 del martedì italiano → data del lunedì.
3. Chiave della diretta: `SHOW-AAAA-MM-GG` (es. `raw-2026-11-09`). Controlla lo stato:
   `python3 scripts/zw.py state raw-2026-11-09`
   Se contiene già `post_id`, la diretta esiste (sessione ripresa): **non creare un secondo articolo**, riparti dal ciclo.

## 2. Creazione dell'articolo (solo quando il report è comparso nel feed)

Non creare l'articolo "a vuoto": prima esegui `python3 scripts/zw.py feed SHOW AAAA-MM-GG --key CHIAVE`.
Se stampa `REPORT NON ANCORA PRESENTE NEL FEED`, aspetta (vedi ciclo). Appena il report c'è:

La fonte di ogni show è in `config/shows.json` (`fonte`): Wrestleview (feed RSS) per Raw, SmackDown, Dynamite e Collision;
Cageside Seats (live blog) per NXT. Il comando `feed` sceglie da solo. **Attenzione con Cageside:** il post esiste già
prima dello show con un'anteprima del cartellone ("Advertised for tonight…", "Come right back here…"). Quelle righe
non sono fatti della puntata: ignorale e crea l'articolo solo quando compare il testo dopo il titolo
"WWE NXT RESULTS AND LIVE BLOG". Lo show è finito quando lo script segnala "il live blog segnala la chiusura dello show"
(es. "Thanks for following along").

```bash
python3 scripts/zw.py job '{"action":"create_post","post":{
  "title":"DIRETTA LIVE: WWE Raw del 09.11.2026",
  "status":"publish","author":1,"categories":[45,53],"featured_media":368661,
  "content":"<p>…introduzione…</p>"}}'
```

- Titolo: `DIRETTA LIVE: <nome dallo shows.json> del GG.MM.AAAA` (data USA).
- Categorie: `[news_category, categoria_fed]`. Mai le categorie dei singoli show (sono sotto "Show Analysis").
- `featured_media` = `logo_media_id` dello show. Autore sempre `author_id` (Giuseppe).
- Introduzione (2 frasi, presente): benvenuto, arena e città **solo se scritte nel report**, poi
  "Di seguito la cronaca della serata, aggiornata segmento per segmento." Niente telecronisti se non servono.
- Poi: `python3 scripts/zw.py job '{"action":"set_status","post_id":ID,"enabled":"1","status":"live","end_hours":DURATA}'`
- Salva subito: `python3 scripts/zw.py state CHIAVE --set post_id=ID --set status=live`

## 3. Il ciclo (ogni 8 minuti circa)

1. `python3 scripts/zw.py feed SHOW AAAA-MM-GG --key CHIAVE` → stampa SOLO i paragrafi nuovi dal giro precedente.
2. Individua i **segmenti conclusi** non ancora pubblicati (confronta con `refs` nello stato).
   - Un match è concluso quando la fonte ne riporta il vincitore. Se è ancora in corso (es. interrotto dalla pubblicità),
     **non pubblicarlo**: aspetta il giro dopo. Ogni blocco deve nascere completo; la modifica (punto 6) serve solo
     a correggere errori o a integrare un dettaglio importante arrivato dopo, non a pubblicare a pezzi.
   - Promo, backstage e video: pubblicali quando la fonte li ha descritti per intero.
   - Segmenti brevi e consecutivi (due clip, un video promozionale) si possono unire in un solo blocco.
3. Scrivi i blocchi (regole al punto 5) in file JSON e inviali **in ordine cronologico** in un solo invio:
   `python3 scripts/zw.py send /tmp/b1.json /tmp/b2.json`
   Formato: `{"action":"add_update","post_id":ID,"type":"match","title":"…","winner":"…","content":"<p>…</p>","ref":"CHIAVE-slug-segmento"}`
   - `type`: `match` | `promo` | `backstage` | `breaking` | `altro` (con `"label":"Testo"`, max 40 caratteri).
   - `ref` univoco e stabile per segmento (es. `raw-2026-11-09-cena-orton`): il plugin scarta i doppioni.
   - **Non inviare mai il campo `source`.**
4. Per ogni esito 201: `python3 scripts/zw.py state CHIAVE --set add_ref=REF`. Esito `duplicate: true` = già pubblicato, ok.
5. Attendi con `sleep 480` (Bash, timeout 600000) e ripeti.

## 4. Fine della diretta

La diretta è finita quando il report descrive la chiusura della puntata (main event concluso e "off the air" o simili)
**e** due giri consecutivi non portano paragrafi nuovi. Allora:
- pubblica gli ultimi blocchi mancanti;
- `python3 scripts/zw.py job '{"action":"set_status","post_id":ID,"status":"ended"}'`
- `python3 scripts/zw.py state CHIAVE --set status=ended`

Limiti di sicurezza:
- Se a 75 minuti dall'orario d'inizio il report non è ancora nel feed: non creare nulla, chiudi la sessione con un messaggio
  ("Report non trovato: diretta non aperta"). Lo show potrebbe essere saltato, registrato o spostato.
- Durata massima della sessione: `durata_ore` + 1,5 ore. Poi chiudi comunque la diretta con lo stato `ended`.
- Se GitHub o il sito restituiscono errori per 3 giri di fila, fermati e lascia un messaggio chiaro con l'errore.

A fine sessione lascia un riepilogo breve (con SendUserMessage se disponibile): link dell'articolo, numero di blocchi,
eventuali segmenti saltati e perché.

## 5. Regole editoriali (vincolanti)

### Voce e fedeltà
- Scrivi come chi **sta guardando lo show in TV**: presente indicativo, ritmo da cronaca, italiano naturale.
- **Mai citare fonti, report, siti o "la telecronaca dice"** nel testo. Niente "secondo…", niente link alle fonti.
- **Solo fatti presenti nel report.** Niente vincitori dedotti, niente mosse inventate, niente motivazioni o intenzioni non scritte.
- **Dettagli poco chiari: si glissa.** Se chi scrive il report non ha capito qualcosa (un oggetto, una persona, una mossa),
  non scriverlo e non dire che non si è capito: descrivi l'azione senza quel dettaglio
  ("lo colpisce con un oggetto preso a bordo ring", oppure ometti del tutto). Mai "non si capisce", "non identificato",
  "la telecronaca non lo dice".
- Acronimi o termini che il report non spiega: lasciali in inglese oppure omettili, mai tradotti a intuito.
- Niente emoji, niente punti esclamativi a raffica, niente commenti da tifoso. Niente voti.
- Tweet incorporati, pubblicità ("FULL AD BREAK"), firme e note di servizio del report non si riportano.

### Forma dei blocchi
- **Titolo del blocco**: per i match i nomi come da cartellone, forma originale inglese compreso "The"
  (es. `The Judgment Day vs. The New Day`); con titolo in palio `Nome del titolo: Campione (c) vs. Sfidante`.
  Per promo e segmenti un titolo breve e informativo in italiano.
- **Testo**: 1-3 paragrafi `<p>`, circa 3-6 righe in tutto. Fasi salienti e soprattutto **il finale e come ci si arriva**
  (interferenze, distrazioni, errori). Promo: senso generale, frasi più taglienti adattate in italiano, annunci.
- **Esito** (`winner`): `Nome per schienamento`, `Nome per sottomissione`, `Nome per count-out`, `Nome per squalifica`,
  con la mossa tra parentesi se scritta nel report (`Chris Jericho per sottomissione (Walls of Jericho)`).
  Cambio di titolo: aggiungi ` – NUOVO <titolo>`. Niente esito per promo, backstage, segmenti, match senza risultato.
- Annunci importanti (cambi di titolo inattesi, ritorni, infortuni comunicati, match ufficializzati) possono avere un
  blocco `breaking` a parte o l'etichetta `altro` (es. "Ufficiale").

### Lingua (dalle regole di Show Analysis di Giuseppe)
- Federazioni femminili: la WWE, la AEW, la TNA, la ROH. Show maschili: il Raw, lo SmackDown, il Dynamite, il Collision.
- Nomi di show **mai con preposizione articolata**: "di Raw", "a SmackDown", "per WrestleMania" (mai "del Raw", "dello SmackDown").
  La data nel titolo dell'articolo ("Raw del 09.11.2026") va bene: "del" si riferisce al giorno.
- Stable e tag team nel testo: senza "The", con l'articolo italiano ("i Judgment Day", "gli Usos", "la Bloodline",
  "gli FTR", "gli Young Bucks", "il New Day", "le Divine Dominion", "i Death Riders", "i Dogs"). Mai "la The …".
  Nei titoli dei match e negli esiti: forma originale con "The".
- Wrestler donne: nome completo alla prima citazione, poi "la + cognome" (mai il cognome da solo).
- Mosse femminili per default: la spear, una lariat, una suplex, una clothesline, la GTS, una moonsault, una senton,
  una piledriver, una backstabber. Eccezioni maschili: il dropkick, il DDT. Mai verbi inventati ("suplessare").
- "titolo" (mai "campionato"); "pubblico" o "platea" (mai "folla"); "il promo"/"i promo"; "segmento" o "clip" (mai "vignetta");
  video: "Va in onda un video…"; backstage: si dice dove siamo ("Nel backstage…").
- **Mai la parola "devastante"**, in nessuna forma.
- Termini lasciati in inglese: nearfall, apron, hot tag, squash, heel, babyface, small package, roll-up, kendo stick, ecc.
- "Looking at the lights" → "steso al tappeto". Niente calchi: "un momento toccante", non "un momento che scalda il cuore".

### Esempio di blocco ben fatto
```json
{"action":"add_update","post_id":385118,"type":"match","title":"FTR vs. Motor City Machine Guns",
 "winner":"FTR per schienamento – serie sul 2-2",
 "content":"<p>I Motor City Machine Guns arrivano a gara 4 in vantaggio per 2-1. Nel finale Stokely Hathaway tira la gamba di Alex Shelley e lo distrae: Dax Harwood ne approfitta e lo sorprende con un roll-up.</p><p>Con questa vittoria gli FTR pareggiano la serie.</p>",
 "ref":"collision-2026-11-07-ftr-mcmg"}
```

## 6. Riferimenti tecnici
- Altre letture: `python3 scripts/zw.py job '{"action":"get","path":"zw-live/v1/updates/ID?after_id=0"}'`
- Fonte di riserva se il feed non funziona: `python3 scripts/zw.py page URL_DEL_REPORT --key CHIAVE`
  (domini consentiti: wrestleview, fightful, prowrestling.net, 411mania, pwinsider, wrestlinginc, f4wonline, pwtorch).
- Correggere un blocco: `{"action":"edit_update","post_id":ID,"update_id":N,"content":"<p>…</p>"}` — invia solo i campi da cambiare
  (`title`, `type`, `label`, `winner`, `content`, `link_url`, `link_label`). L'ID `N` è quello restituito alla creazione.
  I lettori con la pagina aperta vedono la correzione al successivo aggiornamento automatico.
- Eliminare un blocco: `{"action":"delete_update","post_id":ID,"update_id":N}`.
- Link di approfondimento (`link_url` + `link_label`) e tweet/video incorporati (URL su una riga da sola nel `content`):
  li usa Giuseppe dalla regia. Tu non aggiungerli nelle dirette notturne, salvo richiesta esplicita nel prompt.
- Non toccare mai altri articoli del sito. Le uniche scritture consentite sono sull'articolo della diretta di stanotte.
