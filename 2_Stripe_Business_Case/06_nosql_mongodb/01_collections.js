// Base NoSQL (MongoDB) - Stripe Business Case
// Création des sept collections avec règles de validation ($jsonSchema)
// Principe : champs essentiels obligatoires et typés, champs complémentaires libres (schéma flexible encadré)

const base = db.getSiblingDB('stripe_nosql');

const MONTANT = { bsonType: ['decimal', 'double', 'int', 'long'], minimum: 0 };
const SCORE   = { bsonType: ['double', 'decimal'], minimum: 0, maximum: 1 };

function creerCollection(nom, schema) {
  if (base.getCollectionNames().includes(nom)) {
    print(`Collection ${nom} déjà présente, création ignorée`);
    return;
  }
  base.createCollection(nom, {
    validator: { $jsonSchema: schema },
    validationLevel: 'strict',
    validationAction: 'error'
  });
  print(`Collection ${nom} créée`);
}

// Paiements reçus en temps réel par Kafka, enrichis des indicateurs et du score de fraude
// _id = identifiant de la transaction dans la base OLTP : écriture idempotente
creerCollection('transactions_enrichies', {
  bsonType: 'object',
  required: ['_id', 'client_id', 'marchand_id', 'montant', 'devise', 'statut', 'date_heure'],
  properties: {
    _id:         { bsonType: 'string', description: 'Identifiant de la transaction (OLTP)' },
    client_id:   { bsonType: 'string', description: 'Référence au client (OLTP)' },
    marchand_id: { bsonType: 'string', description: 'Référence au marchand (OLTP)' },
    montant:     MONTANT,
    devise:      { bsonType: 'string', pattern: '^[A-Z]{3}$' },
    statut:      { enum: ['reussie', 'echouee', 'remboursee', 'contestee'] },
    date_heure:  { bsonType: 'date' },
    contexte:    { bsonType: 'object' },
    indicateurs: { bsonType: 'object', description: 'Variables calculées pour le modèle (features)' },
    score: {
      bsonType: 'object',
      required: ['valeur', 'modele', 'version', 'decision'],
      properties: {
        valeur:   SCORE,
        modele:   { bsonType: 'string' },
        version:  { bsonType: ['int', 'long'] },
        decision: { enum: ['accepter', 'verifier', 'bloquer'] }
      }
    },
    historique_statuts: {
      bsonType: 'array',
      maxItems: 20,
      items: {
        bsonType: 'object',
        required: ['statut', 'date'],
        properties: {
          statut: { enum: ['reussie', 'echouee', 'remboursee', 'contestee'] },
          date:   { bsonType: 'date' }
        }
      }
    }
  }
});

// Habitudes de chaque client, mises à jour à chaque paiement (magasin de variables en ligne)
// _id = identifiant du client dans la base OLTP
creerCollection('profils_clients', {
  bsonType: 'object',
  required: ['_id', 'nb_paiements', 'montant_total_eur', 'date_maj'],
  properties: {
    _id:               { bsonType: 'string', description: 'Identifiant du client (OLTP)' },
    nb_paiements:      { bsonType: ['int', 'long'], minimum: 0 },
    montant_total_eur: MONTANT,
    montant_moyen_eur: MONTANT,
    pays_connus:       { bsonType: 'array', items: { bsonType: 'string', pattern: '^[A-Z]{2}$' } },
    appareils_connus:  { bsonType: 'array', items: { enum: ['mobile', 'ordinateur', 'tablette'] } },
    dernier_paiement:  { bsonType: 'date' },
    date_maj:          { bsonType: 'date' }
  }
});

// Registre des versions du modèle de détection de fraude
creerCollection('modeles_ml', {
  bsonType: 'object',
  required: ['nom', 'version', 'date_entrainement', 'statut', 'seuil_decision', 'metriques'],
  properties: {
    nom:               { bsonType: 'string' },
    version:           { bsonType: ['int', 'long'], minimum: 1 },
    date_entrainement: { bsonType: 'date' },
    statut:            { enum: ['candidat', 'actif', 'archive'] },
    seuil_decision:    SCORE,
    metriques:         { bsonType: 'object', description: 'Performances mesurées à l\'entraînement et en production' }
  }
});

// Visites sur les sites marchands : une fiche par session, liste bornée d'événements
// client_id facultatif : un visiteur non connecté reste anonyme
creerCollection('sessions_navigation', {
  bsonType: 'object',
  required: ['_id', 'debut', 'appareil', 'evenements'],
  properties: {
    _id:            { bsonType: 'string', description: 'Identifiant de session' },
    client_id:      { bsonType: ['string', 'null'] },
    marchand_id:    { bsonType: 'string' },
    debut:          { bsonType: 'date' },
    fin:            { bsonType: 'date' },
    appareil: {
      bsonType: 'object',
      required: ['type'],
      properties: { type: { enum: ['mobile', 'ordinateur', 'tablette'] } }
    },
    evenements: {
      bsonType: 'array',
      maxItems: 500,
      items: {
        bsonType: 'object',
        required: ['type', 'horodatage'],
        properties: {
          type:       { enum: ['page_vue', 'recherche', 'clic', 'ajout_panier', 'paiement'] },
          horodatage: { bsonType: 'date' },
          page:       { bsonType: 'string' }
        }
      }
    },
    transaction_id: { bsonType: 'string', description: 'Référence au paiement si la visite aboutit' }
  }
});

// Retours clients : avis notés ou réponses à des enquêtes, de structures différentes
creerCollection('avis_clients', {
  bsonType: 'object',
  required: ['type', 'client_id', 'date'],
  properties: {
    type:        { enum: ['avis', 'enquete'] },
    client_id:   { bsonType: 'string' },
    marchand_id: { bsonType: 'string' },
    date:        { bsonType: 'date' },
    note:        { bsonType: ['int', 'long'], minimum: 1, maximum: 5 },
    commentaire: { bsonType: 'string', maxLength: 5000 },
    reponses: {
      bsonType: 'array',
      items: { bsonType: 'object', required: ['question', 'reponse'] }
    }
  },
  anyOf: [
    { properties: { type: { enum: ['avis'] } },    required: ['note'] },
    { properties: { type: { enum: ['enquete'] } }, required: ['reponses'] }
  ]
});

// Journaux techniques des serveurs ; suppression automatique après 90 jours (index TTL, voir 02_index.js)
creerCollection('journaux_applicatifs', {
  bsonType: 'object',
  required: ['horodatage', 'niveau', 'source', 'message'],
  properties: {
    horodatage: { bsonType: 'date' },
    niveau:     { enum: ['DEBUG', 'INFO', 'AVERTISSEMENT', 'ERREUR', 'CRITIQUE'] },
    source: {
      bsonType: 'object',
      required: ['service'],
      properties: { service: { bsonType: 'string' }, hote: { bsonType: 'string' } }
    },
    message:    { bsonType: 'string' },
    code_http:  { bsonType: ['int', 'long'], minimum: 100, maximum: 599 },
    duree_ms:   { bsonType: ['int', 'long', 'double'], minimum: 0 }
  }
});

// Documents reçus de l'extérieur : messages bancaires XML (texte brut + champs extraits),
// justificatifs binaires (PDF, images) stockés dans GridFS (seau « fichiers »)
creerCollection('documents_externes', {
  bsonType: 'object',
  required: ['type', 'format', 'date_reception', 'references'],
  properties: {
    type:             { enum: ['message_bancaire', 'piece_justificative'] },
    format:           { enum: ['xml', 'json', 'pdf', 'image'] },
    date_reception:   { bsonType: 'date' },
    references: {
      bsonType: 'object',
      properties: {
        transaction_id: { bsonType: 'string' },
        litige_id:      { bsonType: 'string' }
      }
    },
    contenu_brut:     { bsonType: 'string', description: 'Texte original du message (XML ou JSON)' },
    champs_extraits:  { bsonType: 'object', description: 'Informations utiles extraites du message' },
    fichier_gridfs_id:{ bsonType: 'objectId', description: 'Référence au fichier binaire dans GridFS' },
    taille_octets:    { bsonType: ['int', 'long'], minimum: 0 }
  },
  anyOf: [
    { properties: { format: { enum: ['xml', 'json'] } },   required: ['contenu_brut'] },
    { properties: { format: { enum: ['pdf', 'image'] } },  required: ['fichier_gridfs_id'] }
  ]
});

print('Collections présentes : ' + base.getCollectionNames().sort().join(', '));
