"""
Test du chiffrement des échanges avec la base transactionnelle (TLS) - Stripe Business Case

Exécuté depuis un conteneur client, avec le compte de service de ce conteneur (variables
OLTP_UTILISATEUR et OLTP_MOT_DE_PASSE) et le certificat de l'autorité (OLTP_SSLROOTCERT).

Trois essais :
1. connexion chiffrée avec vérification complète (verify-full) : acceptée, protocole affiché ;
2. connexion sans chiffrement (disable) : refusée par le serveur (règle hostnossl ... reject) ;
3. connexion chiffrée vers l'adresse IP du serveur au lieu de son nom : refusée par le client,
   l'adresse ne figurant pas dans le certificat (protection contre l'usurpation de serveur).

Un refus n'est conforme que si sa cause est celle attendue : un serveur arrêté ou injoignable
produit un résultat « erreur », jamais un faux succès.
"""

import os
import socket

import psycopg

HOTE = os.getenv("OLTP_HOTE", "postgres-oltp")
IDENTIFIANTS = dict(dbname=os.getenv("OLTP_BASE", "stripe_oltp"),
                    user=os.environ["OLTP_UTILISATEUR"], password=os.environ["OLTP_MOT_DE_PASSE"])
AUTORITE = os.environ["OLTP_SSLROOTCERT"]
nb_conformes, nb_tests = 0, 0


def essai(libelle, attendu, **options):
    global nb_conformes, nb_tests
    try:
        with psycopg.connect(**IDENTIFIANTS, **options) as connexion:
            version, chiffrement = connexion.execute(
                "SELECT version, cipher FROM pg_stat_ssl WHERE pid = pg_backend_pid()").fetchone()
        obtenu, detail = "acceptée", f"{version}, {chiffrement}"
    except psycopg.OperationalError as erreur:
        message = " ".join(str(erreur).split())
        if "pg_hba.conf rejects" in message and "no encryption" in message:
            obtenu = "refusée par le serveur"
        elif "does not match host name" in message:
            obtenu = "refusée par le client"
        else:
            obtenu = "erreur"
        detail = message[-110:]
    nb_tests += 1
    nb_conformes += obtenu == attendu
    print(f"{'CONFORME    ' if obtenu == attendu else 'NON CONFORME'} | {libelle} | attendu : {attendu} | obtenu : {obtenu} | {detail}")


essai("Connexion chiffrée, serveur vérifié (verify-full)", "acceptée",
      host=HOTE, sslmode="verify-full", sslrootcert=AUTORITE)
essai("Connexion sans chiffrement (disable)", "refusée par le serveur",
      host=HOTE, sslmode="disable")
essai("Connexion chiffrée vers l'adresse IP, absente du certificat", "refusée par le client",
      host=socket.gethostbyname(HOTE), sslmode="verify-full", sslrootcert=AUTORITE)
print(f"Bilan : {nb_conformes} tests conformes sur {nb_tests}")
