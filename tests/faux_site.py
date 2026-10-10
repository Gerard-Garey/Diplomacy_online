"""Doublure du site pour l'envoi d'un message et sa relecture (issue #5, volet de fond).

Reproduit ce que le bot de dialogue voit de webDiplomacy, d'après le code
d'amont : game/sendmessage (api.php, classe SendMessage) rend le message relu
dans la table, sous la clé "messages" ; le statut de partie
(api/responses/game_state.php) range tous les messages d'un tour dans sa phase
"Diplomacy" ; un message est stocké après msg_escape (objects/database.php) :
sauts de ligne en "<br />", puis htmlentities(ENT_NOQUOTES, 'UTF-8'). Ce dernier
point est recopié ici (echapper) et n'est contrôlé par aucun test contre l'amont.

Sert à tests/test_etat_dialogue.py et à tests/banc_promesses.py.
"""
import json
from html.entities import codepoint2name
from unittest import mock

# Comportements d'un envoi. Les quatre derniers sont des échecs en apparence : le
# message est stocké ou non selon le nom.
SUCCES = "succès"
SOURDINE = "sourdine"
EXCEPTION = "exception, non stocké"
EXCEPTION_STOCKE = "exception, stocké"
ERREUR_500 = "500, non stocké"
ERREUR_500_STOCKE = "500, stocké"
HTML = "200 non JSON, non stocké"
JSON_PUIS_HTML = "200 JSON suivi de HTML, stocké"


def echapper(texte):
    """msg_escape du site, hors échappement SQL."""
    texte = texte.replace("\r\n", "<br />").replace("\n", "<br />").replace("\r", "<br />")
    # htmlentities(ENT_NOQUOTES) : toute entité nommée sauf les guillemets.
    texte = "".join(
        "&%s;" % codepoint2name[ord(c)] if ord(c) in codepoint2name and c not in "\"'" else c
        for c in texte
    )
    return texte.replace("&lt;br /&gt;", "<br />")


class FauxSite:
    """Table des messages d'une partie, route d'envoi et statut de partie.

    `comportements` : file des comportements des prochains envois (constantes
    ci-dessus) ; vide, l'envoi réussit. `horloge` avance d'une seconde par envoi.
    `pendant_l_envoi`, si elle est donnée, est appelée à chaque envoi, avant la
    réponse, avec le JSON envoyé.
    """

    def __init__(self, horloge=1759400500, quatre_octets_en_point_d_interrogation=False):
        self.horloge = horloge
        self.messages = []  # lignes stockées : fromCountryID, toCountryID, message, timeSent
        self.comportements = []
        self.envois = []  # JSON de chaque appel à la route d'envoi
        self.pendant_l_envoi = None
        self.quatre_octets = quatre_octets_en_point_d_interrogation

    def stocker(self, de, vers, texte, time_sent=None):
        """Insère un message comme le ferait le site ; rend la ligne."""
        if time_sent is None:
            self.horloge += 1
            time_sent = self.horloge
        if self.quatre_octets:
            # Table en utf8 à trois octets : hypothèse non vérifiée, voir _message_key.
            texte = "".join("?" if ord(c) > 0xFFFF else c for c in texte)
        ligne = {
            "fromCountryID": de, "toCountryID": vers, "message": echapper(texte),
            "timeSent": time_sent, "phaseMarker": "Diplomacy",
        }
        self.messages.append(ligne)
        return ligne

    def post_req(self, url, params, json_envoye, api_key):
        """Doublure de fairdiplomacy_external.webdip_api.post_req."""
        self.envois.append(dict(json_envoye))
        if self.pendant_l_envoi:
            self.pendant_l_envoi(json_envoye)
        comportement = self.comportements.pop(0) if self.comportements else SUCCES
        if comportement == SOURDINE:
            return mock.Mock(status_code=200, content=json.dumps({"messages": []}).encode())
        ligne = None
        if comportement in (SUCCES, EXCEPTION_STOCKE, ERREUR_500_STOCKE, JSON_PUIS_HTML):
            ligne = self.stocker(json_envoye["countryID"], json_envoye["toCountryID"], json_envoye["message"])
        if comportement in (EXCEPTION, EXCEPTION_STOCKE):
            raise ConnectionError("connexion coupée (doublure)")
        if comportement in (ERREUR_500, ERREUR_500_STOCKE):
            return mock.Mock(status_code=500, content=b"<html>Internal Server Error</html>")
        if comportement == HTML:
            return mock.Mock(status_code=200, content=b"<html>maintenance</html>")
        corps = json.dumps({"messages": [{
            "fromCountryID": ligne["fromCountryID"], "message": ligne["message"],
            "timeSent": ligne["timeSent"], "toCountryID": ligne["toCountryID"], "turn": 0,
        }]})
        if comportement == JSON_PUIS_HTML:
            corps += "<br /><b>Warning</b>: doublure"
        return mock.Mock(status_code=200, content=corps.encode())

    def statut(self, ctx=None):
        """Doublure de get_status_json : tous les messages, dans la phase Diplomacy du tour."""
        return {"phases": [
            {"turn": 0, "phase": "Diplomacy", "messages": [dict(m) for m in self.messages]},
            {"turn": 0, "phase": "Retreats"},
        ]}

    def textes_envoyes(self):
        return [envoi["message"] for envoi in self.envois]
