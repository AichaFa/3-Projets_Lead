"""
Génération des certificats TLS de la base transactionnelle - Stripe Business Case

Produit, dans le dossier du script :
- ca.crt / ca.key           : autorité de certification propre au projet (clé privée gardée localement) ;
- serveur.crt / serveur.key : certificat du serveur PostgreSQL de la base transactionnelle, signé
                              par cette autorité.

Le certificat du serveur porte les noms par lesquels il est joint (postgres-oltp sur le réseau Docker,
localhost depuis la machine hôte) : les clients en mode verify-full vérifient à la fois la signature
de l'autorité et la correspondance du nom, ce qui protège contre l'usurpation du serveur.

Clés à courbe elliptique P-256 (sécurité équivalente à RSA 3072 bits, clés plus courtes).
Les clés privées (*.key) sont exclues du dépôt Git ; seuls les certificats publics peuvent y figurer.
Script répétable : des certificats existants ne sont pas écrasés.
"""

import ipaddress
import os
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DUREE_AUTORITE = timedelta(days=3650)
DUREE_SERVEUR = timedelta(days=825)      # durée maximale admise pour un certificat de serveur
NOMS_SERVEUR = ["postgres-oltp", "localhost"]


def chemin(nom):
    return os.path.join(DOSSIER, nom)


def enregistrer_cle(cle, nom):
    with open(chemin(nom), "wb") as fichier:
        fichier.write(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))


def enregistrer_certificat(certificat, nom):
    with open(chemin(nom), "wb") as fichier:
        fichier.write(certificat.public_bytes(serialization.Encoding.PEM))


def nom_distinctif(nom_commun):
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Stripe Business Case"),
        x509.NameAttribute(NameOID.COMMON_NAME, nom_commun),
    ])


def generer():
    if os.path.exists(chemin("serveur.crt")):
        print("Certificats déjà présents : aucune génération")
        return
    maintenant = datetime.now(timezone.utc)

    # Autorité de certification : certificat auto-signé, habilité à signer d'autres certificats
    cle_autorite = ec.generate_private_key(ec.SECP256R1())
    sujet_autorite = nom_distinctif("Autorite de certification Stripe Business Case")
    autorite = (
        x509.CertificateBuilder()
        .subject_name(sujet_autorite).issuer_name(sujet_autorite)
        .public_key(cle_autorite.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant).not_valid_after(maintenant + DUREE_AUTORITE)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle_autorite.public_key()), critical=False)
        .sign(cle_autorite, hashes.SHA256())
    )

    # Certificat du serveur, signé par l'autorité, valable pour les noms de NOMS_SERVEUR
    cle_serveur = ec.generate_private_key(ec.SECP256R1())
    noms = [x509.DNSName(n) for n in NOMS_SERVEUR] + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    serveur = (
        x509.CertificateBuilder()
        .subject_name(nom_distinctif(NOMS_SERVEUR[0])).issuer_name(sujet_autorite)
        .public_key(cle_serveur.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant).not_valid_after(maintenant + DUREE_SERVEUR)
        .add_extension(x509.SubjectAlternativeName(noms), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_agreement=True,
                                     content_commitment=False, data_encipherment=False, key_cert_sign=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(cle_autorite.public_key()), critical=False)
        .sign(cle_autorite, hashes.SHA256())
    )

    enregistrer_cle(cle_autorite, "ca.key")
    enregistrer_certificat(autorite, "ca.crt")
    enregistrer_cle(cle_serveur, "serveur.key")
    enregistrer_certificat(serveur, "serveur.crt")
    print(f"Autorité de certification valable jusqu'au {maintenant + DUREE_AUTORITE:%d/%m/%Y}")
    print(f"Certificat du serveur valable jusqu'au {maintenant + DUREE_SERVEUR:%d/%m/%Y} pour : {', '.join(NOMS_SERVEUR)}, 127.0.0.1")


if __name__ == "__main__":
    generer()
