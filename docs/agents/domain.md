# Documentation du domaine

Comment les skills d'ingénierie doivent exploiter la documentation du domaine de ce dépôt lorsqu'ils explorent le code.

## Avant d'explorer, lire

- **`CONTEXT.md`** à la racine du dépôt, ou
- **`CONTEXT-MAP.md`** à la racine s'il existe : il pointe vers un `CONTEXT.md` par contexte. Lire chacun de ceux qui concernent le sujet.
- **`docs/adr/`** : lire les ADR qui touchent la zone sur laquelle on s'apprête à travailler. Dans un dépôt multi-contexte, consulter aussi `src/<contexte>/docs/adr/` pour les décisions propres à un contexte.

Si l'un de ces fichiers n'existe pas, **continuer sans rien dire**. Ne pas signaler son absence ; ne pas suggérer de le créer d'emblée. Le skill `/domain-modeling` (accessible via `/grill-with-docs` et `/improve-codebase-architecture`) les crée au fil de l'eau, lorsque des termes ou des décisions sont effectivement tranchés.

## Structure des fichiers

Ce dépôt est **mono-contexte** (noms d'ADR donnés à titre d'exemple) :

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-exemple-de-decision.md
│   └── 0002-autre-decision.md
├── src/
```

Dépôt multi-contexte (présence de `CONTEXT-MAP.md` à la racine), pour mémoire :

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← décisions valables pour tout le système
└── src/
    ├── contexte-a/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← décisions propres au contexte
    └── contexte-b/
        ├── CONTEXT.md
        └── docs/adr/
```

## Employer le vocabulaire du glossaire

Lorsqu'une production nomme un concept du domaine (titre d'issue, proposition de refactorisation, hypothèse, nom de test), utiliser le terme tel que défini dans `CONTEXT.md`. Ne pas dériver vers des synonymes que le glossaire écarte explicitement.

Si le concept nécessaire ne figure pas encore dans le glossaire, c'est un signal : soit on invente un vocabulaire que le projet n'utilise pas (à reconsidérer), soit il y a un vrai manque (à noter pour `/domain-modeling`).

## Signaler les conflits avec un ADR

Si une production contredit un ADR existant, le signaler explicitement plutôt que de passer outre en silence :

> _Contredit l'ADR-0001 (<titre>), mais mérite d'être rouvert parce que…_
