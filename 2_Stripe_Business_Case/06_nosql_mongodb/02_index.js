// Base NoSQL (MongoDB) - Stripe Business Case
// Index : chemins d'accès fréquents, unicité, recherche plein texte et expiration automatique (TTL)

const base = db.getSiblingDB('stripe_nosql');

// Paiements enrichis : historique par client et par marchand, paiements suspects
base.transactions_enrichies.createIndex({ client_id: 1, date_heure: -1 },   { name: 'idx_client_date' });
base.transactions_enrichies.createIndex({ marchand_id: 1, date_heure: -1 }, { name: 'idx_marchand_date' });
base.transactions_enrichies.createIndex(
  { 'score.valeur': -1 },
  { name: 'idx_suspects', partialFilterExpression: { 'score.valeur': { $gte: 0.8 } } }
);

// Profils : repérage des profils récemment modifiés
base.profils_clients.createIndex({ date_maj: -1 }, { name: 'idx_date_maj' });

// Modèles : une seule fiche par couple nom et version, une seule version active par modèle
base.modeles_ml.createIndex({ nom: 1, version: 1 }, { name: 'uq_nom_version', unique: true });
base.modeles_ml.createIndex(
  { nom: 1 },
  { name: 'uq_version_active', unique: true, partialFilterExpression: { statut: 'actif' } }
);

// Sessions : parcours d'un client, visites ayant abouti à un paiement
base.sessions_navigation.createIndex({ client_id: 1, debut: -1 }, { name: 'idx_client_debut' });
base.sessions_navigation.createIndex(
  { transaction_id: 1 },
  { name: 'idx_transaction', partialFilterExpression: { transaction_id: { $exists: true } } }
);

// Avis : par marchand, par client, recherche plein texte en français dans les commentaires
base.avis_clients.createIndex({ marchand_id: 1, date: -1 }, { name: 'idx_marchand_date' });
base.avis_clients.createIndex({ client_id: 1 },             { name: 'idx_client' });
base.avis_clients.createIndex(
  { commentaire: 'text' },
  { name: 'txt_commentaire', default_language: 'french' }
);

// Journaux : suppression automatique 90 jours après l'horodatage (7 776 000 secondes)
base.journaux_applicatifs.createIndex(
  { horodatage: 1 },
  { name: 'ttl_90_jours', expireAfterSeconds: 7776000 }
);
base.journaux_applicatifs.createIndex({ niveau: 1, horodatage: -1 },            { name: 'idx_niveau_date' });
base.journaux_applicatifs.createIndex({ 'source.service': 1, horodatage: -1 }, { name: 'idx_service_date' });

// Documents externes : rattachement à un paiement ou à un litige
base.documents_externes.createIndex({ 'references.transaction_id': 1 }, { name: 'idx_transaction' });
base.documents_externes.createIndex({ 'references.litige_id': 1 },      { name: 'idx_litige' });
base.documents_externes.createIndex({ type: 1, date_reception: -1 },    { name: 'idx_type_date' });

base.getCollectionNames().sort().forEach(function (nom) {
  print(`${nom} : ${base.getCollection(nom).getIndexes().length} index`);
});
