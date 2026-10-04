// Base NoSQL (MongoDB) - Stripe Business Case
// Contrôle d'accès par rôles (RBAC) : rôles sur mesure par collection et comptes de service
//
// Chaque rôle liste, collection par collection, les seules opérations autorisées.
// Aucun rôle de service ne peut supprimer de document (action « remove » jamais accordée).
// Mots de passe lus dans les variables d'environnement du conteneur (process.env).
// Script répétable : un rôle ou un compte existant est mis à jour au lieu d'être recréé.

const base = db.getSiblingDB('stripe_nosql');
const NOM_BASE = 'stripe_nosql';

function droits(collections, actions) {
  return collections.map(function (collection) {
    return { resource: { db: NOM_BASE, collection: collection }, actions: actions };
  });
}

// Opérations nécessaires au stockage de fichiers dans GridFS (seau de fichiers ou de modèles)
function droitsGridFS(seau, actions) {
  return droits([seau + '.files', seau + '.chunks'], actions.concat(['listIndexes', 'createIndex']));
}

function definirRole(nom, privileges) {
  if (base.getRole(nom)) {
    base.updateRole(nom, { privileges: privileges, roles: [] });
    print(`Rôle ${nom} mis à jour`);
  } else {
    base.createRole({ role: nom, privileges: privileges, roles: [] });
    print(`Rôle ${nom} créé`);
  }
}

function definirCompte(nom, variable, role) {
  const motDePasse = process.env[variable];
  if (!motDePasse) {
    throw new Error(`Variable d'environnement ${variable} absente`);
  }
  if (base.getUser(nom)) {
    base.updateUser(nom, { pwd: motDePasse, roles: [{ role: role, db: NOM_BASE }] });
    print(`Compte ${nom} mis à jour`);
  } else {
    base.createUser({ user: nom, pwd: motDePasse, roles: [{ role: role, db: NOM_BASE }] });
    print(`Compte ${nom} créé`);
  }
}

// Application de paiement : écriture des données de navigation, avis, journaux et documents reçus
definirRole('role_generateur_nosql', [].concat(
  droits(['sessions_navigation', 'avis_clients', 'journaux_applicatifs', 'documents_externes'], ['insert']),
  droitsGridFS('fichiers', ['find', 'insert'])
));

// Flux temps réel et apprentissage : paiements enrichis, profils, registre et fichiers des modèles,
// signalement des erreurs et alertes dans les journaux
definirRole('role_flux_nosql', [].concat(
  droits(['transactions_enrichies', 'profils_clients', 'modeles_ml'], ['find', 'insert', 'update']),
  droits(['journaux_applicatifs'], ['insert']),
  droitsGridFS('modeles', ['find', 'insert'])
));

// Orchestrateur : contrôles de conformité (lecture des index et des règles de validation) et
// trace du résultat dans les journaux
definirRole('role_orchestrateur_nosql', [].concat(
  [{ resource: { db: NOM_BASE, collection: '' }, actions: ['listCollections'] }],
  droits(['journaux_applicatifs'], ['find', 'insert', 'listIndexes'])
));

definirCompte('svc_generateur', 'MONGO_GENERATEUR_PASSWORD', 'role_generateur_nosql');
definirCompte('svc_flux', 'MONGO_FLUX_PASSWORD', 'role_flux_nosql');
definirCompte('svc_airflow', 'MONGO_ORCHESTRATEUR_PASSWORD', 'role_orchestrateur_nosql');
