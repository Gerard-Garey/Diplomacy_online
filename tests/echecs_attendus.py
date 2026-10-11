"""Marque d'un défaut connu : échec attendu, renvoyant à son issue (règle des tests de CLAUDE.md).

Même enveloppe que celle de tests/test_promesses.py (`echec_attendu`), le fichier du test étant
donné : sert à tests/test_reference.py et à tests/test_reference_couche_r.py. Quand l'issue est
corrigée, le test réussit, la batterie échoue (succès inattendu) et la marque est retirée.
"""
import functools
import os
import sys
import traceback
import unittest

sys.dont_write_bytecode = True  # ni __pycache__ dans tests/ (#27)


def levee_par(fichier, trace):
    """Vrai si l'exception a été levée par une ligne de `fichier`.

    Les cadres de unittest (assertEqual et ses semblables) sont ignorés : ils
    lèvent pour le compte de la ligne qui les appelle.
    """
    cadres = [c for c, _ in traceback.walk_tb(trace) if "__unittest" not in c.f_globals]
    return bool(cadres) and os.path.abspath(cadres[-1].f_code.co_filename) == os.path.abspath(fichier)


def echec_attendu(issue, fichier):
    """Échec attendu, renvoyant à son issue ; `fichier` : le `__file__` du fichier de tests.

    Seule une assertion fausse écrite dans ce fichier est un échec attendu.
    Toute autre exception (signature changée, clé absente, assertion levée par
    le code testé) est affichée et rendue en succès inattendu, pour que la
    batterie échoue au lieu de la confondre avec le défaut de l'issue : un test
    qui attend un refus là où le code lève aujourd'hui une exception la rattrape
    donc lui-même et en fait une assertion. Pas de subTest dans un test ainsi
    marqué : unittest y remplace l'assertion par une exception interne.
    MONTRER_ECHECS=1 affiche la raison de chaque échec attendu.
    """

    def decorer(test):
        @functools.wraps(test)
        def enveloppe(self):
            try:
                test(self)
            except Exception as e:
                if isinstance(e, AssertionError) and levee_par(fichier, e.__traceback__):
                    if os.environ.get("MONTRER_ECHECS"):
                        raison = " | ".join(str(e).split("\n")[:1])
                        sys.stderr.write("\n#%d %s : %s\n" % (issue, test.__name__, raison))
                    raise
                sys.stderr.write(
                    "\n%s : erreur qui n'est pas l'échec attendu de #%d\n%s"
                    % (self.id(), issue, traceback.format_exc())
                )

        enveloppe.issue = issue
        return unittest.expectedFailure(enveloppe)

    return decorer
