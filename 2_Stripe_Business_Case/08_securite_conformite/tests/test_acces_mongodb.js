// Tests du contrôle d'accès par rôles - Base NoSQL (MongoDB)
//
// Chaque essai ouvre une connexion sous l'identité d'un compte de service (mots de passe lus
// dans les variables d'environnement du conteneur) et tente une opération.
// Interprétation : erreur « Unauthorized » (code 13) = refusé ; succès ou rejet par les règles
// de validation (code 121) = autorisé. Les essais d'insertion autorisée envoient volontairement
// un document incomplet, rejeté par la validation : aucune donnée n'est écrite.

const comptes = {
  svc_generateur: process.env.MONGO_GENERATEUR_PASSWORD,
  svc_flux: process.env.MONGO_FLUX_PASSWORD,
  svc_airflow: process.env.MONGO_ORCHESTRATEUR_PASSWORD,
};
let nbConformes = 0;
let nbTests = 0;

function base(compte) {
  const adresse = `mongodb://${compte}:${comptes[compte]}@localhost:27017/stripe_nosql?authSource=stripe_nosql`;
  return new Mongo(adresse).getDB('stripe_nosql');
}

function essai(compte, libelle, attendu, operation) {
  let obtenu;
  try {
    operation(base(compte));
    obtenu = 'autorisé';
  } catch (e) {
    obtenu = e.code === 13 ? 'refusé' : (e.code === 121 ? 'autorisé' : `erreur ${e.code}`);
  }
  nbTests += 1;
  if (obtenu === attendu) { nbConformes += 1; }
  print(`${obtenu === attendu ? 'CONFORME    ' : 'NON CONFORME'} | ${compte.padEnd(15)} | ${libelle} | attendu : ${attendu} | obtenu : ${obtenu}`);
}

const incomplet = { essai_controle_acces: true };

essai('svc_generateur', 'Insérer une session de navigation', 'autorisé', b => b.sessions_navigation.insertOne(incomplet));
essai('svc_generateur', 'Lire les paiements enrichis', 'refusé', b => b.transactions_enrichies.findOne());
essai('svc_generateur', 'Lire les profils clients', 'refusé', b => b.profils_clients.findOne());
essai('svc_generateur', 'Supprimer une session de navigation', 'refusé', b => b.sessions_navigation.deleteOne({ _id: 'inexistant' }));

essai('svc_flux', 'Lire les paiements enrichis', 'autorisé', b => b.transactions_enrichies.findOne());
essai('svc_flux', 'Insérer un paiement enrichi', 'autorisé', b => b.transactions_enrichies.insertOne(incomplet));
essai('svc_flux', 'Lire les sessions de navigation', 'refusé', b => b.sessions_navigation.findOne());
essai('svc_flux', 'Supprimer un profil client', 'refusé', b => b.profils_clients.deleteOne({ _id: 'inexistant' }));
essai('svc_flux', 'Supprimer la collection des modèles', 'refusé', b => b.modeles_ml.drop());

essai('svc_airflow', 'Lire les journaux applicatifs', 'autorisé', b => b.journaux_applicatifs.findOne());
essai('svc_airflow', 'Lister les collections', 'autorisé', b => b.getCollectionInfos());
essai('svc_airflow', 'Lire les profils clients', 'refusé', b => b.profils_clients.findOne());
essai('svc_airflow', 'Modifier un modèle', 'refusé', b => b.modeles_ml.updateOne({ _id: 'inexistant' }, { $set: { statut: 'actif' } }));

print(`Bilan : ${nbConformes} tests conformes sur ${nbTests}`);
