// Base NoSQL (MongoDB) - Stripe Business Case
// Tests des règles de validation et des index ; les documents de test sont supprimés en fin d'exécution

const base = db.getSiblingDB('stripe_nosql');
const maintenant = new Date();
let nbConformes = 0;
let nbTests = 0;

function essai(libelle, attendu, action) {
  let obtenu;
  try { action(); obtenu = 'accepté'; } catch (e) { obtenu = 'refusé'; }
  nbTests += 1;
  if (obtenu === attendu) { nbConformes += 1; }
  print(`${obtenu === attendu ? 'CONFORME    ' : 'NON CONFORME'} | ${libelle} | attendu : ${attendu} | obtenu : ${obtenu}`);
}

// avis_clients : deux structures dans une même collection
essai('Avis noté 4 sur 5', 'accepté', () => base.avis_clients.insertOne({
  _id: 'test_avis_1', type: 'avis', client_id: 'test_client', date: maintenant,
  note: NumberInt(4), commentaire: 'Livraison rapide, chaussures très confortables'
}));
essai('Avis sans note', 'refusé', () => base.avis_clients.insertOne({
  _id: 'test_avis_2', type: 'avis', client_id: 'test_client', date: maintenant
}));
essai('Avis noté 7 sur 5', 'refusé', () => base.avis_clients.insertOne({
  _id: 'test_avis_3', type: 'avis', client_id: 'test_client', date: maintenant, note: NumberInt(7)
}));
essai('Enquête avec réponses, sans note', 'accepté', () => base.avis_clients.insertOne({
  _id: 'test_enquete_1', type: 'enquete', client_id: 'test_client', date: maintenant,
  reponses: [{ question: 'Recommanderiez-vous ce site ?', reponse: 'Oui' }]
}));

// transactions_enrichies : types, formats et bornes du score
essai('Paiement complet avec score', 'accepté', () => base.transactions_enrichies.insertOne({
  _id: 'test_tx_1', client_id: 'test_client', marchand_id: 'test_marchand',
  montant: 80.0, devise: 'EUR', statut: 'reussie', date_heure: maintenant,
  score: { valeur: 0.04, modele: 'test_modele', version: NumberInt(1), decision: 'accepter' }
}));
essai('Paiement avec devise en minuscules', 'refusé', () => base.transactions_enrichies.insertOne({
  _id: 'test_tx_2', client_id: 'test_client', marchand_id: 'test_marchand',
  montant: 80.0, devise: 'eur', statut: 'reussie', date_heure: maintenant
}));
essai('Paiement avec score de 1,5', 'refusé', () => base.transactions_enrichies.insertOne({
  _id: 'test_tx_3', client_id: 'test_client', marchand_id: 'test_marchand',
  montant: 80.0, devise: 'EUR', statut: 'reussie', date_heure: maintenant,
  score: { valeur: 1.5, modele: 'test_modele', version: NumberInt(1), decision: 'bloquer' }
}));
essai('Même paiement envoyé une seconde fois (doublon)', 'refusé', () => base.transactions_enrichies.insertOne({
  _id: 'test_tx_1', client_id: 'test_client', marchand_id: 'test_marchand',
  montant: 80.0, devise: 'EUR', statut: 'reussie', date_heure: maintenant
}));

// documents_externes : XML et binaire
essai('Message bancaire XML sans contenu', 'refusé', () => base.documents_externes.insertOne({
  _id: 'test_doc_1', type: 'message_bancaire', format: 'xml', date_reception: maintenant, references: {}
}));
essai('Message bancaire XML avec contenu', 'accepté', () => base.documents_externes.insertOne({
  _id: 'test_doc_2', type: 'message_bancaire', format: 'xml', date_reception: maintenant,
  references: { transaction_id: 'test_tx_1' },
  contenu_brut: '<Document><Montant devise="EUR">80.00</Montant></Document>',
  champs_extraits: { montant: 80.0, devise: 'EUR' }
}));

// modeles_ml : une seule version active par modèle
essai('Version 1 active', 'accepté', () => base.modeles_ml.insertOne({
  nom: 'test_modele', version: NumberInt(1), date_entrainement: maintenant,
  statut: 'actif', seuil_decision: 0.8, metriques: {}
}));
essai('Version 2 active en même temps', 'refusé', () => base.modeles_ml.insertOne({
  nom: 'test_modele', version: NumberInt(2), date_entrainement: maintenant,
  statut: 'actif', seuil_decision: 0.8, metriques: {}
}));

// journaux_applicatifs : niveau dans la liste autorisée
essai('Journal de niveau inconnu', 'refusé', () => base.journaux_applicatifs.insertOne({
  horodatage: maintenant, niveau: 'GRAVE', source: { service: 'api' }, message: 'test'
}));

// Recherche plein texte en français : « chaussure » doit retrouver « chaussures »
const nbTrouves = base.avis_clients.countDocuments({ $text: { $search: 'chaussure' } });
nbTests += 1;
if (nbTrouves === 1) { nbConformes += 1; }
print(`${nbTrouves === 1 ? 'CONFORME    ' : 'NON CONFORME'} | Recherche « chaussure » dans les avis | attendu : 1 avis | obtenu : ${nbTrouves} avis`);

// Nettoyage
base.avis_clients.deleteMany({ client_id: 'test_client' });
base.transactions_enrichies.deleteMany({ client_id: 'test_client' });
base.documents_externes.deleteMany({ _id: /^test_/ });
base.modeles_ml.deleteMany({ nom: 'test_modele' });

print(`Bilan : ${nbConformes} tests conformes sur ${nbTests}`);
