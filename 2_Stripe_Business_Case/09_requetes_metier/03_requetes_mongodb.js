// Requêtes métier - Base NoSQL (MongoDB) - Stripe Business Case
//
// Pipelines d'agrégation sur les documents imbriqués (indices, score, événements de session,
// recommandations) et recherche plein texte. Requête transverse aux trois bases : fichiers 04_*.

const base = db.getSiblingDB('stripe_nosql');

function titre(texte) { print(`\n=== ${texte}`); }
// Nombre au format français : virgule décimale
function fr(nombre, decimales) { return Number(nombre).toFixed(decimales).replace('.', ','); }
function ligne(valeurs, largeurs) {
  print(valeurs.map((v, i) => String(v === undefined || v === null ? '-' : v).padEnd(largeurs[i] || 12)).join(' | '));
}

// Q11. Paiements bloqués dans la dernière heure et indices ayant motivé la décision
// Les indices binaires et les seuils (rafale, montant inhabituel) sont lus dans le sous-document indicateurs
titre('Q11. Paiements bloqués dans la dernière heure et indices déclenchés');
const depuisUneHeure = new Date(Date.now() - 3600 * 1000);
ligne(['Paiement', 'Montant', 'Devise', 'Score', 'Pays IP', 'Indices déclenchés'], [10, 10, 6, 6, 7, 40]);
base.transactions_enrichies.aggregate([
  { $match: { 'score.decision': 'bloquer', date_heure: { $gte: depuisUneHeure } } },
  { $sort: { date_heure: -1 } },
  { $limit: 10 },
  { $project: {
      montant: { $toString: '$montant' }, devise: 1, score: '$score.valeur', pays_ip: '$contexte.pays_ip',
      indices: { $concatArrays: [
        { $cond: [{ $eq: ['$indicateurs.pays_ip_inhabituel', 1] }, ['pays IP inhabituel'], []] },
        { $cond: [{ $eq: ['$indicateurs.appareil_inhabituel', 1] }, ['appareil inhabituel'], []] },
        { $cond: [{ $eq: ['$indicateurs.marchand_nouveau', 1] }, ['marchand nouveau'], []] },
        { $cond: [{ $gte: ['$indicateurs.nb_paiements_derniere_heure', 2] }, ['rafale'], []] },
        { $cond: [{ $gte: ['$indicateurs.ecart_au_montant_moyen', 2] },
                  [{ $concat: ['montant x', { $toString: { $round: ['$indicateurs.ecart_au_montant_moyen', 1] } }] }], []] },
        { $cond: [{ $eq: ['$indicateurs.est_nuit', 1] }, ['paiement nocturne'], []] },
      ] },
  } },
]).forEach(p => ligne([p._id.slice(0, 8), p.montant.replace('.', ','), p.devise, fr(p.score, 2), p.pays_ip,
                       p.indices.map(i => i.replace('.', ',')).join(', ') || 'combinaison de faibles signaux'], [10, 10, 6, 6, 7, 40]));

// Q12. Suivi du flux en production sur 24 heures : répartition des décisions et latence médiane
// ($median : accumulateur disponible à partir de MongoDB 7.0). Les paiements traités après un arrêt
// du flux affichent une latence élevée (temps d'attente dans Kafka), d'où le choix de la médiane
titre('Q12. Décisions du modèle et latence du flux temps réel (24 dernières heures)');
ligne(['Décision', 'Paiements', 'Part', 'Score moyen', 'Latence médiane'], [10, 10, 8, 12, 15]);
const depuis24h = new Date(Date.now() - 24 * 3600 * 1000);
const total24h = base.transactions_enrichies.countDocuments({ date_heure: { $gte: depuis24h } });
base.transactions_enrichies.aggregate([
  { $match: { date_heure: { $gte: depuis24h } } },
  { $group: { _id: '$score.decision', nb: { $sum: 1 }, score_moyen: { $avg: '$score.valeur' },
              latence_mediane: { $median: { input: '$latence_ms', method: 'approximate' } } } },
  { $sort: { nb: -1 } },
]).forEach(d => ligne([d._id, d.nb, `${fr(100 * d.nb / total24h, 1)} %`, fr(d.score_moyen, 3), `${Math.round(d.latence_mediane)} ms`], [10, 10, 8, 12, 15]));

// Q13. Personnalisation : recommandations et préférences du client le plus actif
// Les recommandations sont calculées en temps réel par le consommateur et stockées dans le profil
titre('Q13. Recommandations de produits du client le plus actif');
const profil = base.profils_clients.find({ 'recommandations.0': { $exists: true } }).sort({ nb_paiements: -1 }).limit(1).toArray()[0];
if (profil) {
  print(`Client ${profil._id} : ${profil.nb_paiements} paiements, montant moyen ${fr(profil.montant_moyen_eur, 2)} euros`);
  print(`Catégories préférées : ${Object.entries(profil.categories_preferees).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${c} (${n})`).join(', ')}`);
  print(`Modèle : ${profil.recommandations_modele.nom}, version ${profil.recommandations_modele.version}`);
  ligne(['Rang', 'Produit recommandé', 'Score', 'Origine'], [5, 38, 7, 12]);
  profil.recommandations.forEach((r, i) => ligne([i + 1, r.produit_id, fr(r.score, 3), r.origine], [5, 38, 7, 12]));
} else {
  print('Aucun profil avec recommandations');
}

// Q14. Entonnoir de conversion strict des visites des sept derniers jours
// Chaque session contient la liste de ses événements : un seul document lu par visite.
// Entonnoir strict : chaque étape ne compte que les visites ayant franchi toutes les étapes précédentes
// (consultation, puis ajout au panier, puis paiement), définition standard d'un entonnoir de conversion
titre('Q14. Entonnoir de conversion des visites (sept derniers jours)');
const etapes = base.sessions_navigation.aggregate([
  { $match: { debut: { $gte: new Date(Date.now() - 7 * 24 * 3600 * 1000) } } },
  { $project: {
      a_consulte: { $in: ['page_vue', '$evenements.type'] },
      a_ajoute: { $in: ['ajout_panier', '$evenements.type'] },
      a_paye: { $in: ['paiement', '$evenements.type'] },
      anonyme: { $eq: ['$client_id', null] },
  } },
  { $group: { _id: null, visites: { $sum: 1 },
              consultations: { $sum: { $cond: ['$a_consulte', 1, 0] } },
              ajouts_panier: { $sum: { $cond: [{ $and: ['$a_consulte', '$a_ajoute'] }, 1, 0] } },
              paiements: { $sum: { $cond: [{ $and: ['$a_consulte', '$a_ajoute', '$a_paye'] }, 1, 0] } },
              anonymes: { $sum: { $cond: ['$anonyme', 1, 0] } } } },
]).toArray()[0];
if (etapes) {
  ligne(['Étape', 'Visites', 'Part des visites', 'Passage depuis l\'étape précédente'], [30, 9, 16, 34]);
  let precedent = etapes.visites;
  [['1. Visites', etapes.visites], ['2. Consultation de page', etapes.consultations],
   ['3. Ajout au panier', etapes.ajouts_panier], ['4. Paiement', etapes.paiements]]
    .forEach(([libelle, nb]) => {
      ligne([libelle, nb, `${fr(100 * nb / etapes.visites, 1)} %`, `${fr(100 * nb / precedent, 1)} %`], [30, 9, 16, 34]);
      precedent = nb;
    });
  print(`Visiteurs non connectés : ${etapes.anonymes} visites (${fr(100 * etapes.anonymes / etapes.visites, 1)} %)`);
} else {
  print('Aucune visite sur la période');
}

// Q15. Avis clients : marchands les mieux et les moins bien notés, puis recherche plein texte
// L'index texte en français retrouve « livraison » sous ses formes fléchies (livrer, livré...)
titre('Q15. Note moyenne par marchand (au moins 5 avis)');
ligne(['Marchand', 'Avis', 'Note moyenne'], [38, 6, 12]);
const notes = base.avis_clients.aggregate([
  { $match: { type: 'avis' } },
  { $group: { _id: '$marchand_id', nb: { $sum: 1 }, note: { $avg: '$note' } } },
  { $match: { nb: { $gte: 5 } } },
  { $sort: { note: -1 } },
]).toArray();
notes.slice(0, 3).concat(notes.slice(-3)).forEach(n => ligne([n._id, n.nb, fr(n.note, 2)], [38, 6, 12]));
print('\nAvis mentionnant la livraison (recherche plein texte, triés par pertinence) :');
base.avis_clients.aggregate([
  { $match: { $text: { $search: 'livraison' } } },
  { $sort: { pertinence: { $meta: 'textScore' } } },
  { $limit: 3 },
  { $project: { note: 1, commentaire: 1 } },
]).forEach(a => print(`  ${a.note} sur 5 : ${a.commentaire}`));
print(`Total : ${base.avis_clients.countDocuments({ $text: { $search: 'livraison' } })} avis`);

// Q16. Pièces des dossiers de litige : messages bancaires XML et justificatifs PDF (GridFS)
// Regroupement par litige grâce à la référence commune litige_id
titre('Q16. Composition des dossiers de litige');
const dossiers = base.documents_externes.aggregate([
  { $group: { _id: '$references.litige_id', formats: { $addToSet: '$format' },
              motif: { $max: '$champs_extraits.motif' } } },
  { $group: { _id: { complet: { $setIsSubset: [['xml', 'pdf'], '$formats'] } }, nb: { $sum: 1 } } },
]).toArray();
dossiers.forEach(d => print(`${d._id.complet ? 'Message XML et justificatif PDF' : 'Message XML seul'} : ${d.nb} litiges`));
print('Motifs extraits des messages XML :');
base.documents_externes.aggregate([
  { $match: { format: 'xml' } },
  { $group: { _id: '$champs_extraits.motif', nb: { $sum: 1 } } },
  { $sort: { nb: -1 } },
]).forEach(m => print(`  ${m._id} : ${m.nb}`));
