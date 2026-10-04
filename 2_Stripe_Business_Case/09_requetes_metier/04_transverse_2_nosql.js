// Requête transverse (Q17), volet 2 sur 3 - Base NoSQL (MongoDB) - Stripe Business Case
//
// Fiche enrichie du paiement : décision, indices calculés en temps réel et historique des statuts.
// Paramètre obligatoire : variable d'environnement TRANSACTION_ID.

const base = db.getSiblingDB('stripe_nosql');
const identifiant = process.env.TRANSACTION_ID;
print(`\n=== Q17, volet 2 : la fiche enrichie dans la base NoSQL ${identifiant}`);
const fiche = base.transactions_enrichies.findOne({ _id: identifiant });
if (fiche) {
  const fr = (n, d) => Number(n).toFixed(d).replace('.', ',');
  print(`Date : ${fiche.date_heure.toISOString()} ; traitement : ${fiche.date_traitement.toISOString()} ; latence : ${fiche.latence_ms} ms`);
  print(`Montant : ${fiche.montant.toString().replace('.', ',')} ${fiche.devise} (${fiche.contexte.montant_eur.toString().replace('.', ',')} euros) ; pays IP : ${fiche.contexte.pays_ip} ; appareil : ${fiche.contexte.type_appareil}`);
  print(`Score : ${fr(fiche.score.valeur, 4)} (modèle ${fiche.score.modele}, version ${fiche.score.version}) ; décision : ${fiche.score.decision}`);
  print('Indices calculés au moment du paiement :');
  Object.entries(fiche.indicateurs).forEach(([nom, valeur]) => print(`  ${nom.padEnd(28)} ${Number.isInteger(valeur) ? valeur : fr(valeur, 2)}`));
  print(`Historique des statuts : ${fiche.historique_statuts.map(h => `${h.statut} (${h.date.toISOString()})`).join(' -> ')}`);
} else {
  print('Aucune fiche enrichie pour ce paiement (paiement antérieur à la mise en service du flux temps réel)');
}
