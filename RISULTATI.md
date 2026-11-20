# Risultati automatici tramite GitHub (ponte temporaneo)

Questo file vale SOLO per l'attività "Risultati automatici". Le regole di CLAUDE.md riguardano le dirette:
per i risultati non si usano feed, stato, refs né blocchi `add_update`.

Si usa quando lo scenario Make 9888949 non è disponibile (crediti esauriti). Pubblica un articolo di risultati
con immagine in evidenza, esattamente come faceva lo scenario.

## Leggere le fonti e il sito (WebFetch nelle attività programmate è bloccato)
- Elenco Fightful: `python3 scripts/zw.py read https://www.fightful.com/wrestling/results/ --links results`
- Articolo Fightful (meta og:image, article:published_time/modified_time e testo completo):
  `python3 scripts/zw.py read URL_ARTICOLO`
- Sito (doppioni, tag, link interni): `python3 scripts/zw.py job '{"action":"get","path":"wp/v2/posts?categories=2&per_page=10&_fields=id,title,date,link,status"}'`
  oppure `wp/v2/posts?search=NOME&per_page=5&_fields=title,link,date`, `wp/v2/tags?search=NOME&_fields=id,name,count`.
  Puoi mettere più job in un solo invio con `zw.py send f1.json f2.json` per risparmiare tempo.

## Pubblicare un articolo
Scrivi il job in un file e invialo (GitHub Actions lo esegue in meno di un minuto e scrive l'esito):

```bash
python3 scripts/zw.py send /tmp/risultato-1.json
```

```json
{"action": "create_post_image",
 "post": {"title": "RISULTATI: AEW Collision 14.11.2026", "content": "<!-- wp:paragraph -->…", "author": 1,
          "slug": "risultati-aew-collision-14-11-2026", "categories": [2, 10805], "tags": [123, 456]},
 "image_url": "https://…/og-image.jpg",
 "file_name": "risultati-aew-collision-14-11-2026.jpg",
 "image_title": "AEW Collision", "alt_text": "AEW Collision",
 "final_status": "publish"}
```

- `post` è il corpo per `wp/v2/posts` (stessi campi del `post_json` di Make; aggiungi `"date"` solo se serve retrodatare).
  Lo stato lo decide `final_status`: non serve mettere `status` in `post`.
- L'esito (`[201] create_post_image ...`) contiene `image.ok`, `image.media_id` e `post.id`, `post.status`, `post.link`.
- Se l'immagine non si scarica o non si carica, l'articolo viene creato **in bozza** senza immagine (`image.ok: false`
  con il motivo): segnalalo nel resoconto, non rilanciare (si creerebbe un doppione).
- Domini immagine consentiti: fightful.com e sottodomini, ytimg.com, cloudfront.net, wp.com, i principali siti di wrestling
  (elenco `IMAGE_DOMAINS` in `scripts/process_queue.py`). Per verificare un'immagine senza scrivere nulla sul sito:
  `python3 scripts/zw.py job '{"action":"check_image","image_url":"https://…"}'`.
- Un job per articolo, un invio alla volta. In caso di timeout dell'invio, prima di rilanciare controlla su
  `results/` e sul sito che l'articolo non sia già stato creato.
- Letture del sito: si possono fare con WebFetch sull'API pubblica oppure con
  `python3 scripts/zw.py job '{"action":"get","path":"wp/v2/posts?search=...&per_page=5"}'`.
