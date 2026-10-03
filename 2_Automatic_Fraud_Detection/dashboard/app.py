"""Tableau de bord de monitoring de la détection de fraude.

Mini-API FastAPI qui lit la base fraud et sert une page web unique
affichant, en temps réel, l'état du pipeline : paiements traités,
fraudes détectées, quarantaine, derniers paiements et suivi.
"""

from __future__ import annotations

import os

import psycopg2
import psycopg2.extras
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

DB = {
    "host": os.environ.get("FRAUD_DB_HOST", "postgres"),
    "port": int(os.environ.get("FRAUD_DB_PORT", "5432")),
    "dbname": os.environ.get("FRAUD_DB_NAME", "fraud"),
    "user": os.environ.get("FRAUD_DB_USER", "fraud"),
    "password": os.environ.get("FRAUD_DB_PASSWORD", ""),
}

app = FastAPI(title="Tableau de bord - Détection de fraude")


def requete(sql, params=None, un_seul=False):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return cur.fetchone() if un_seul else cur.fetchall()
    finally:
        conn.close()


@app.get("/api/stats")
def stats():
    glob = requete(
        """
        SELECT
            count(*) AS paiements,
            coalesce(sum(CASE WHEN prediction = 1 THEN 1 ELSE 0 END), 0) AS fraudes,
            coalesce(sum(amt), 0) AS montant_total
        FROM transactions
        """,
        un_seul=True,
    )
    quar = requete("SELECT count(*) AS n FROM quarantaine", un_seul=True)
    suivi = requete(
        """
        SELECT count(*) AS passages,
               coalesce(round(avg(duree_ms) FILTER (WHERE duree_ms > 0)), 0) AS duree_moy
        FROM suivi_executions
        """,
        un_seul=True,
    )
    derniers = requete(
        """
        SELECT to_char(recu_le AT TIME ZONE 'Europe/Paris', 'HH24:MI:SS') AS heure,
               amt, category, prediction
        FROM transactions
        ORDER BY id DESC
        LIMIT 8
        """
    )
    return JSONResponse(
        {
            "paiements": int(glob["paiements"]),
            "fraudes": int(glob["fraudes"]),
            "montant_total": float(glob["montant_total"]),
            "quarantaine": int(quar["n"]),
            "passages": int(suivi["passages"]),
            "duree_moy": int(suivi["duree_moy"]),
            "derniers": [
                {
                    "heure": r["heure"],
                    "amt": float(r["amt"]) if r["amt"] is not None else 0.0,
                    "category": r["category"],
                    "prediction": int(r["prediction"]) if r["prediction"] is not None else 0,
                }
                for r in derniers
            ],
        }
    )


@app.get("/", response_class=HTMLResponse)
def page():
    return PAGE_HTML


PAGE_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Détection de fraude - Tableau de bord</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Calibri, Arial, sans-serif; background: #1B2A4A; color: #fff; padding: 32px 40px; }
  h1 { font-size: 26px; font-weight: bold; margin-bottom: 4px; }
  .kicker { color: #E8573F; font-size: 13px; font-weight: bold; letter-spacing: 2px; margin-bottom: 24px; }
  .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; margin-bottom: 28px; }
  .card { background: #22345A; border-radius: 12px; padding: 22px 24px; }
  .card .num { font-size: 42px; font-weight: bold; color: #fff; }
  .card.alert .num { color: #E8573F; }
  .card .lab { font-size: 13px; color: #AEB9D0; margin-top: 6px; }
  .grid2 { display: grid; grid-template-columns: 2fr 1fr; gap: 18px; }
  .panel { background: #22345A; border-radius: 12px; padding: 22px 24px; }
  .panel h2 { font-size: 15px; color: #AEB9D0; font-weight: bold; margin-bottom: 14px; letter-spacing: 1px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 12px; color: #7D8AA8; padding: 6px 8px; border-bottom: 1px solid #33456B; }
  td { font-size: 14px; padding: 8px; border-bottom: 1px solid #2B3D63; }
  .verdict-ok { color: #6FC89B; }
  .verdict-fraude { color: #E8573F; font-weight: bold; }
  .foot { margin-top: 12px; font-size: 12px; color: #7D8AA8; }
  .pulse { display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: #6FC89B; margin-right: 6px; animation: p 1.6s infinite; }
  @keyframes p { 0%,100%{opacity:1} 50%{opacity:.3} }
  .big { font-size: 30px; font-weight: bold; }
  .mut { font-size: 13px; color: #AEB9D0; margin-top:4px; }
</style>
</head>
<body>
  <div class="kicker">DÉTECTION DE FRAUDE EN TEMPS RÉEL</div>
  <h1>Tableau de bord du pipeline</h1>
  <div class="foot"><span class="pulse"></span>Mise à jour automatique toutes les 3 secondes</div>
  <div style="height:20px"></div>

  <div class="cards">
    <div class="card"><div class="num" id="paiements">-</div><div class="lab">Paiements traités</div></div>
    <div class="card alert"><div class="num" id="fraudes">-</div><div class="lab">Fraudes détectées</div></div>
    <div class="card"><div class="num" id="quarantaine">-</div><div class="lab">En quarantaine</div></div>
    <div class="card"><div class="num" id="passages">-</div><div class="lab">Passages du pipeline</div></div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>DERNIERS PAIEMENTS</h2>
      <table>
        <thead><tr><th>Heure</th><th>Montant</th><th>Catégorie</th><th>Verdict</th></tr></thead>
        <tbody id="derniers"></tbody>
      </table>
    </div>
    <div class="panel">
      <h2>PERFORMANCE</h2>
      <div class="big" id="duree">-</div>
      <div class="mut">Durée moyenne de traitement (ms)</div>
      <div style="height:18px"></div>
      <div class="big" id="montant">-</div>
      <div class="mut">Montant total traité</div>
    </div>
  </div>

<script>
async function refresh() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    document.getElementById('paiements').textContent = d.paiements;
    document.getElementById('fraudes').textContent = d.fraudes;
    document.getElementById('quarantaine').textContent = d.quarantaine;
    document.getElementById('passages').textContent = d.passages;
    document.getElementById('duree').textContent = d.duree_moy;
    document.getElementById('montant').textContent =
      d.montant_total.toLocaleString('fr-FR', {maximumFractionDigits:0}) + ' €';
    const tb = document.getElementById('derniers');
    tb.innerHTML = d.derniers.map(p => {
      const v = p.prediction === 1
        ? '<span class="verdict-fraude">FRAUDE</span>'
        : '<span class="verdict-ok">Normal</span>';
      return `<tr><td>${p.heure}</td><td>${Number(p.amt).toFixed(2)} €</td><td>${p.category}</td><td>${v}</td></tr>`;
    }).join('');
  } catch(e) { console.error(e); }
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
