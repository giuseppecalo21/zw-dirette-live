# zw-dirette-live

Ponte tra Claude e il plugin WP Wrestling Live Pro di zonawrestling.net.

Claude salva un file JSON in `queue/`; GitHub Actions lo invia all'API REST di WordPress
(utente dedicato con password delle applicazioni nei segreti del repository) e scrive l'esito in `results/`.

Segreti richiesti: `WP_BASE_URL`, `WP_USER`, `WP_APP_PASSWORD`.
